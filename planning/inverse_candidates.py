"""Bounded standard CP candidates with exact physical distance constraints."""
import argparse
from copy import deepcopy
from functools import reduce
from math import gcd
from pathlib import Path
import time
from industrial.common import actions_only,read_json,write_json
from industrial.inverse_math import distance,normalize


def generate(base,folder,cap,objective,budget_s=35,seed=1907):
    started=time.perf_counter()
    from ortools.sat.python import cp_model
    import ortools
    normalized=normalize(base)
    if normalized!=base:raise ValueError('base is not earliest')
    if objective not in ('nominal','load'):raise ValueError('unregistered CP objective')
    step=reduce(gcd,[a['work'] for o in base['operations'] for a in o['alternatives']])
    horizon=(base['nominal_makespan']*11//10)//step
    model=cp_model.CpModel();starts={};ends={};choices={};original={};groups=[[] for _ in base['queues']]
    loads=[[] for _ in groups]
    for o in base['operations']:
        i=o['id'];starts[i]=model.new_int_var(0,horizon,f'start-{i}');ends[i]=model.new_int_var(0,horizon,f'end-{i}')
        selected=[]
        for k,a in enumerate(o['alternatives']):
            present=model.new_bool_var(f'assignment-{i}-{k}');choices[i,k]=present;selected.append(present)
            groups[a['machine']].append(model.new_optional_interval_var(starts[i],a['work']//step,ends[i],present,f'op-{i}-{k}'))
            loads[a['machine']].append((a['work']//step)*present)
            if a['machine']==o['machine']:original[i]=present
            model.add_hint(present,int(a['machine']==o['machine']))
        model.add_exactly_one(selected)
        model.add_hint(starts[i],o['planned_start']//step);model.add_hint(ends[i],o['planned_end']//step)
    for o in base['operations']:
        for p in o['predecessors']:model.add(ends[p]<=starts[o['id']])
    for group in groups:model.add_no_overlap(group)
    reversals=[]
    for q in base['queues']:
        for k,a in enumerate(q):
            for b in q[k+1:]:
                reverse=model.new_bool_var(f'reversed-{a}-{b}');reversals.append(reverse)
                model.add(reverse<=original[a]);model.add(reverse<=original[b]);model.add_hint(reverse,0)
                model.add(ends[b]<=starts[a]).only_enforce_if(reverse)
                model.add(ends[a]<=starts[b]).only_enforce_if([original[a],original[b],reverse.Not()])
    edits=sum(1-original[i] for i in original)+sum(reversals);model.add(edits<=cap)
    cmax=model.new_int_var(0,horizon,'makespan');model.add_max_equality(cmax,list(ends.values()))
    maximum_load=model.new_int_var(0,horizon,'maximum-load');model.add_max_equality(maximum_load,[sum(v) for v in loads])
    primary,secondary=(cmax,maximum_load) if objective=='nominal' else (maximum_load,cmax)
    model.minimize((primary*(horizon+1)+secondary)*(cap+1)+edits)
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1;solver.parameters.random_seed=seed
    remaining=budget_s-(time.perf_counter()-started)-2
    if remaining<=0:raise TimeoutError('CP model build exhausted process budget')
    solver.parameters.max_time_in_seconds=remaining;status=solver.solve(model);name=solver.status_name(status)
    if status in (cp_model.INFEASIBLE,cp_model.MODEL_INVALID):raise ValueError('known feasible hint rejected: '+name)
    plan=deepcopy(base);origin='base fallback'
    if status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        for o in plan['operations']:
            i=o['id'];a=next(a for k,a in enumerate(o['alternatives']) if solver.boolean_value(choices[i,k]))
            o.update(machine=a['machine'],work=a['work'])
        plan['queues']=[sorted([o['id'] for o in plan['operations'] if o['machine']==m],
            key=lambda i:(solver.value(starts[i]),i)) for m in range(len(groups))]
        plan=normalize(plan);origin='CP-SAT with exact structural distance'
    actual=distance(base,plan)
    if actual['total']>cap or plan['planned_makespan']>base['nominal_makespan']*11//10:raise ValueError('candidate violates physical budget')
    if actual['total']==0 and plan!=base:raise ValueError('hidden time compression at zero physical distance')
    if status in (cp_model.OPTIMAL,cp_model.FEASIBLE) and actual['total']!=solver.value(edits):
        raise ValueError('CP structural distance differs from actual physical distance')
    if status==cp_model.OPTIMAL and plan['planned_makespan']//step!=solver.value(cmax):
        raise ValueError('earliest normalization contradicts claimed bounded optimum')
    root=Path(folder);root.mkdir(parents=True,exist_ok=True);write_json(root/'schedule.json',plan)
    write_json(root/'result.json',dict(status='PASS',solver_status=name,origin=origin,cap=cap,objective=objective,
        actual_distance=actual,budget_s=budget_s,wall_s=time.perf_counter()-started,ortools=ortools.__version__,
        bounded_objective_optimality_proved=status==cp_model.OPTIMAL,stochastic_optimality_claimed=False,
        solver_tick=step,workers=1,normalization='exact solver assignments and machine order; all earliest times recomputed'))


if __name__=='__main__':
    actions_only();p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('folder');p.add_argument('--cap',type=int,required=True)
    p.add_argument('--objective',required=True);p.add_argument('--budget',type=float,default=35);p.add_argument('--seed',type=int,default=1907)
    args=p.parse_args();generate(read_json(args.input),args.folder,args.cap,args.objective,args.budget,args.seed)
