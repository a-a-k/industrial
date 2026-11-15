"""CP-SAT incumbent-pool generation followed by direct probability ranking."""
import argparse
from pathlib import Path
import resource
import time
from .cpsat import generate as cp_generate
from .generator import BudgetStop,decode,from_conditions,initial_genome,objective_key
from industrial.common import actions_only,canonical,digest,execute,read_json,read_rows,write_json
from industrial.inputs import scenarios
from industrial.plan_campaign import plan_identity
from industrial.production import check_physics,outcomes,product_ledger


def evaluate(plan,bank,deadline,folder,remaining_s):
    end=time.perf_counter()+remaining_s;folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/'dataset.json',plan);write_json(folder/'scenarios.json',bank)
    remaining=end-time.perf_counter()
    if remaining<=0:raise BudgetStop('candidate input preparation exhausted the budget')
    process=execute([str(Path('build/simulator').resolve()),'des',str(folder/'dataset.json'),
        str(folder/'scenarios.json'),str(folder/'des.jsonl'),'MISSION',str(deadline),str(plan['delta'])],timeout=remaining)
    if process['status']=='TIMEOUT':raise BudgetStop('candidate execution exhausted the remaining budget')
    if process['status']!='OK':raise ValueError('candidate simulator failed: '+str(process))
    trajectories={r['scenario_id']:r for r in read_rows(folder/'des.jsonl')}
    if set(trajectories)!={s['id'] for s in bank}:raise ValueError('incomplete candidate trajectories')
    for scenario in bank:
        if time.perf_counter()>=end:raise BudgetStop('candidate checking exhausted the remaining budget')
        check_physics(plan,scenario,trajectories[scenario['id']])
    labels=outcomes(product_ledger(plan,bank,trajectories),
        [j['id'] for j in plan['jobs'] if not j.get('optional',False)],deadline)
    if any(v is None for v in labels.values()):raise ValueError('unknown calibration outcome')
    if time.perf_counter()>=end:raise BudgetStop('candidate accounting exhausted the remaining budget')
    return dict(nominal_makespan=plan['planned_makespan'],p_f1=sum(labels.values())/len(bank),p_f2=None,
        F1=dict(samples=len(bank),successes=sum(labels.values()),outcomes=labels,processes=[process]))


def generate(problem_path,folder,seed=1701):
    started=time.perf_counter();problem=read_json(problem_path);spec=problem['spec']
    root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    data=problem.get('dataset')
    if data is None:data=from_conditions(problem['conditions'])
    budget=spec['search']['total_budget_s'];finish=started+budget-5
    bank=scenarios(data,'F1',spec['search_split'],spec['search_replications_per_law'])
    write_json(root/'search-calendars.json.gz',{'F1':bank})
    cp=cp_generate(data,root/'cp',spec['pool_cp_budget_s'],seed,started,pool_limit=spec['pool_limit'])
    nominal=read_json(root/'cp/schedule.json');pool=read_json(root/'cp/pool.json')
    # Both mandatory references are evaluated before optional intermediate incumbents.
    genomes=[initial_genome(data),initial_genome(nominal)]
    genomes.extend(row['genome'] for row in reversed(pool['candidates']))
    unique={}
    for genome in genomes:
        plan=decode(data,genome);key=plan_identity(plan)
        unique.setdefault(key,(genome,plan))
    records=[];best=None;stopping='all_unique_candidates_evaluated';mandatory=set()
    for candidate in (decode(data,initial_genome(data)),nominal):mandatory.add(plan_identity(candidate))
    for index,(key,(genome,plan)) in enumerate(unique.items()):
        folder=root/f'candidate-{index:03d}';write_json(folder/'schedule.json',plan)
        remaining=finish-time.perf_counter()
        if remaining<=0:stopping='wall_budget';break
        try:score=evaluate(plan,bank,problem['deadline'],folder,remaining)
        except BudgetStop as error:
            records.append(dict(plan_sha256=key,status='BUDGET_CENSORED',error=str(error)))
            stopping='candidate_budget_censored';break
        row=dict(plan_sha256=key,status='OK',genome=genome,score=score)
        records.append(row)
        if best is None or (objective_key(score,'deadline_f1'),key)<(objective_key(best['score'],'deadline_f1'),best['plan_sha256']):best=row
    mandatory_scored=mandatory<={r['plan_sha256'] for r in records if r['status']=='OK'}
    selected=[]
    if best is not None:
        plan=decode(data,best['genome']);write_json(root/'schedule.json',plan)
        selected=[dict(best,file='schedule.json',saved_plan_sha256=digest(canonical(plan)))]
    result=dict(status='PASS' if best is not None and mandatory_scored else 'PARTIAL',
        backend='CP-SAT-pool-Monte-Carlo',objective='deadline_f1',seed=seed,budget_s=budget,
        total_interface_s=time.perf_counter()-started,cp=cp,pool_limit=spec['pool_limit'],
        pool_solutions_seen=pool['solutions_seen'],pool_omitted=pool['omitted'],
        unique_candidates=len(unique),evaluated_candidates=sum(r['status']=='OK' for r in records),
        mandatory_original_and_nominal_evaluated=mandatory_scored,stopping_reason=stopping,
        selected=selected,candidates=records,reference_C0=data['nominal_makespan'],deadline=problem['deadline'],
        calibration_sha256=digest(canonical(bank)),
        cpu_self_s=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,
        cpu_children_s=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime+resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    if result['total_interface_s']>budget:result['status']='BUDGET_EXCEEDED'
    write_json(root/'result.json',result)
    return result


if __name__=='__main__':
    actions_only();parser=argparse.ArgumentParser();parser.add_argument('input')
    parser.add_argument('--folder',required=True);parser.add_argument('--seed',type=int,default=1701)
    args=parser.parse_args();generate(args.input,args.folder,args.seed)
