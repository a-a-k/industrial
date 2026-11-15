"""Generate and independently test schedules under selectable objectives."""
import argparse
import csv
import gzip
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time
from planning.generator import BudgetStop,decode,from_conditions,search,validate_problem
from .common import actions_only,canonical,digest,execute,read_json,read_rows,write_json
from .inputs import scenarios
from .production import simulate,product_ledger,outcomes,check_physics,compare
from .releases import fetch


def plan_identity(plan):
    return digest(canonical(dict(assignments=[(o['machine'],o['work']) for o in plan['operations']],queues=plan['queues'])))


def search_one(problem_path,folder,objective,seed):
    started=time.perf_counter();root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    problem=read_json(problem_path)
    if 'dataset' not in problem:problem=dict(problem,dataset=from_conditions(problem['conditions']))
    data=problem['dataset'];spec=problem['spec'];validate_problem(data)
    deadline=problem['deadline'];n=spec['search_replications_per_law']
    needed=[] if objective=='nominal' else (['F1'] if objective=='deadline_f1' else spec['laws'])
    calendars={law:scenarios(data,law,spec['search_split'],n) for law in needed}
    write_json(root/'search-calendars.json.gz',calendars)
    work=root/'last-evaluation';failures=0
    def evaluate(plan,which,remaining_s):
        nonlocal failures
        evaluation_end=time.perf_counter()+remaining_s
        score=dict(nominal_makespan=max(o['planned_end'] for o in plan['operations']),p_f1=None,p_f2=None)
        if which=='nominal':return score
        try:
            for law in (['F1'] if which=='deadline_f1' else spec['laws']):
                if work.exists():shutil.rmtree(work)
                work.mkdir(parents=True);write_json(work/'dataset.json',plan);write_json(work/'scenarios.json',calendars[law])
                remaining=evaluation_end-time.perf_counter()
                if remaining<=0:raise BudgetStop('no time left for a complete candidate evaluation')
                process=execute([str(Path('build/simulator').resolve()),'des',str(work/'dataset.json'),
                    str(work/'scenarios.json'),str(work/'des.jsonl'),'MISSION',str(deadline),str(plan['delta'])],timeout=remaining)
                processes=[process]
                if process['status']=='TIMEOUT':raise BudgetStop('native candidate computation censored at the remaining search budget')
                trajectories={r['scenario_id']:r for r in read_rows(work/'des.jsonl')} if (work/'des.jsonl').exists() else {}
                if len(trajectories)!=n or any(p['status']!='OK' for p in processes):
                    raise ValueError('candidate evaluation unavailable: '+json.dumps(processes))
                for scenario in calendars[law]:
                    if time.perf_counter()>=evaluation_end:raise BudgetStop('candidate checking censored at search budget')
                    check_physics(plan,scenario,trajectories[scenario['id']])
                labels=outcomes(product_ledger(plan,calendars[law],trajectories),[j['id'] for j in plan['jobs'] if not j.get('optional',False)],deadline)
                if len(labels)!=n or any(v is None for v in labels.values()):raise ValueError('unknown candidate outcomes')
                score['p_'+law.lower()]=sum(labels.values())/n
                score[law]=dict(samples=n,successes=sum(labels.values()),outcomes=labels,processes=processes)
        except BudgetStop:
            if work.exists():shutil.copytree(work,root/'budget-censored-evaluation')
            raise
        except Exception:
            failures+=1
            if work.exists():shutil.copytree(work,root/f'failed-evaluation-{failures:04d}')
            raise
        return score
    prep_s=time.perf_counter()-started
    with gzip.open(root/'search-trace.jsonl.gz','wt',encoding='utf-8') as trace:
        result=search(data,objective,evaluate,plan_identity,max(0,spec['search']['total_budget_s']-prep_s-5),seed,
            max_evaluations=spec['search']['max_evaluations'],trace=lambda row:trace.write(json.dumps(row,separators=(',',':'))+'\n'))
    for index,entry in enumerate(result['selected']):
        plan=decode(data,entry['genome']);entry['file']=f'plan-{index:02d}.json'
        entry['saved_plan_sha256']=digest(canonical(plan));write_json(root/entry['file'],plan)
    if work.exists():shutil.rmtree(work)
    result.update(status='PASS' if result['selected'] and not result['stats']['failures'] else 'PARTIAL',
        preparation_s=prep_s,total_s=time.perf_counter()-started,
        cpu_self_s=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,
        cpu_children_s=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime+resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        problem_sha256=digest(canonical(problem)),deadline=deadline,reference_C0=data['nominal_makespan'])
    write_json(root/'result.json',result)


def generate(preflight,instance):
    root=Path('output/plans');root.mkdir(parents=True,exist_ok=True)
    spec=read_json('provenance/plan_generation.json')
    if instance not in spec['instances']:raise ValueError('unregistered generation instance')
    source,_=fetch(preflight,'output/plan-preflight')
    if read_json(source/'preflight.json')['status']!='PASS':raise ValueError('production preflight unavailable')
    data=read_json(source/instance/'dataset.json');mult=spec['deadline_multiplier']
    problem=dict(dataset=data,deadline=data['nominal_makespan']*mult[0]//mult[1],spec=spec)
    write_json(root/'problem.json',problem);results=[]
    for seed in spec['seeds']:
        for objective in spec['objectives']:
            label=f'{seed}-{objective}';folder=root/label
            process=execute([sys.executable,'-m','industrial.plan_campaign','search',str(root/'problem.json'),
                '--folder',str(folder),'--objective',objective,'--seed',str(seed)])
            result=read_json(folder/'result.json') if process['status']=='OK' else dict(status='UNAVAILABLE')
            if process['wall_s']>spec['search']['total_budget_s']:result['status']='BUDGET_EXCEEDED'
            results.append(dict(case=label,objective=objective,seed=seed,process=process,result=result))
            write_json(root/'progress.json',dict(instance=instance,results=results))
    report=dict(status='PASS' if all(r['result']['status']=='PASS' for r in results) else 'PARTIAL',
        instance=instance,preflight=preflight,problem_sha256=digest(canonical(problem)),results=results,
        implementation={name:digest(Path(name).read_bytes()) for name in ('planning/generator.py','industrial/plan_campaign.py')},
        role='generated schedules frozen before new holdout',commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'generation.json',report)


def paired_difference(candidate,baseline):
    from .statistics import lower,upper
    if set(candidate)!=set(baseline) or any(v is None for v in [*candidate.values(),*baseline.values()]):
        return dict(status='UNAVAILABLE')
    n=len(candidate);gain=sum(candidate[k] and not baseline[k] for k in candidate)
    loss=sum(baseline[k] and not candidate[k] for k in candidate)
    return dict(status='OK',samples=n,gain=gain,loss=loss,difference=(gain-loss)/n,
        outer95=[lower(gain,n,.0125)-upper(loss,n,.0125),upper(gain,n,.0125)-lower(loss,n,.0125)],
        confidence_scope='one fixed plan comparison and regime; four one-sided 98.75% binomial bounds')


def validate(registry_path,instance):
    from .binding import fit
    from .production import export_observations
    from .statistics import outer
    from .targets import query_full_r
    spec=read_json('provenance/plan_generation.json');registry=read_json(registry_path)
    root=Path('output/plan-validation');root.mkdir(parents=True,exist_ok=True)
    generations={};folders={};seal=[]
    for index,tag in enumerate(registry['generations']):
        folder,receipt=fetch(tag,f'output/generation-{index}');record=read_json(folder/'generation.json')
        if record['status']!='PASS':raise ValueError('incomplete generation cannot open a holdout')
        if record['instance'] in generations:raise ValueError('duplicate generation instance')
        for name,sha in record['implementation'].items():
            if digest(Path(name).read_bytes())!=sha:raise ValueError('generator changed after plan freezing')
        problem=read_json(folder/'problem.json')
        if problem['spec']!=spec or digest(canonical(problem))!=record['problem_sha256']:
            raise ValueError('generation protocol or input changed')
        generations[record['instance']]=record;folders[record['instance']]=folder
        seal.append(dict(instance=record['instance'],release=tag,archive_sha256=receipt['archive_sha256']))
    if set(generations)!=set(spec['instances']):raise ValueError('all generation instances must be frozen first')
    write_json(root/'plan-seal.json',dict(generations=seal,role='all immutable generated plans before new holdout'))
    source=folders[instance];generation=generations[instance];problem=read_json(source/'problem.json')
    data=problem['dataset'];deadline=problem['deadline'];jobs=[j['id'] for j in data['jobs'] if not j.get('optional',False)]
    plans={plan_identity(data):dict(dataset=data,aliases=['original'],nominal_makespan=data['nominal_makespan'])}
    for result in generation['results']:
        for index,selected in enumerate(result['result']['selected']):
            plan=read_json(source/result['case']/selected['file']);key=plan_identity(plan)
            if key!=selected['plan_sha256'] or digest(canonical(plan))!=selected['saved_plan_sha256']:
                raise ValueError('generated plan checksum mismatch')
            row=plans.setdefault(key,dict(dataset=plan,aliases=[],nominal_makespan=plan['planned_makespan']))
            row['aliases'].append(f'{result["case"]}:{index}')
    calendars={law:scenarios(data,law,spec['validation_split'],spec['validation_replications_per_law']) for law in spec['laws']}
    write_json(root/'holdout-calendars.json.gz',calendars);results=[]
    for key,entry in plans.items():
        plan=entry['dataset'];validate_problem(plan);planroot=root/key;planroot.mkdir(parents=True)
        write_json(planroot/'schedule.json',plan)
        with (planroot/'schedule.csv').open('w',newline='') as stream:
            fields=['id','job','machine','work','planned_start','planned_end']
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(plan['operations'])
        regimes={}
        for law,bank in calendars.items():
            outputs={};processes=[];mismatches=[];labels={};folder=planroot/law
            selected=sorted(bank,key=lambda s:digest(('TSFG-plan-v1|'+s['id']).encode()))[:spec['tsfg_validation_subset_per_law']]
            for engine in ('des','dag','tsfg'):
                current=selected if engine=='tsfg' else bank
                output,ps=simulate(plan,current,folder/engine,engine,deadline,chunk=16 if engine=='tsfg' else 128)
                outputs[engine]=output;processes.extend(ps)
                for scenario in current:
                    if scenario['id'] not in output:continue
                    try:check_physics(plan,scenario,output[scenario['id']])
                    except Exception as error:mismatches.append(dict(engine=engine,attempt=scenario['id'],error=str(error)))
            for engine in ('dag','tsfg'):
                for aid in outputs[engine].keys() & outputs['des'].keys():
                    try:compare(outputs['des'][aid],outputs[engine][aid])
                    except Exception as error:mismatches.append(dict(engine=engine,attempt=aid,error=str(error)))
            ledger=product_ledger(plan,bank,outputs['des']);write_json(folder/'product-ledger.json.gz',ledger)
            labels=outcomes(ledger,jobs,deadline)
            complete=(len(outputs['des'])==len(outputs['dag'])==len(bank) and len(outputs['tsfg'])==len(selected)
                and not mismatches and all(p['status']=='OK' for p in processes)
                and all(v is not None for v in labels.values()))
            full_r=None
            if complete:
                model,_,_=fit(export_observations(plan,bank,outputs['des'],deadline),deadline)
                full_r=query_full_r(model);write_json(folder/'model.json.gz',model)
                if full_r['lower']!=full_r['upper'] or full_r['guaranteed']!=sum(labels.values()):
                    mismatches.append(dict(error='generated-plan model R differs from external batch result'));complete=False
            successes=sum(v is True for v in labels.values())
            regimes[law]=dict(status='COMPLETE' if complete else 'PARTIAL',samples=len(bank),successes=successes,
                probability=successes/len(bank) if complete else None,ci95=outer(successes,successes,len(bank)) if complete else None,
                outcomes=labels,full_R=full_r,processes=processes,mismatches=mismatches,
                des_completed=len(outputs['des']),dag_completed=len(outputs['dag']),tsfg_completed=len(outputs['tsfg']))
            write_json(folder/'result.json',regimes[law])
        results.append(dict(plan_sha256=key,aliases=entry['aliases'],nominal_makespan=entry['nominal_makespan'],regimes=regimes))
        write_json(root/'progress.json',dict(instance=instance,plans=results))
    by_alias={alias:r for r in results for alias in r['aliases']};comparisons=[]
    for row in results:
        for alias in row['aliases']:
            if alias=='original':continue
            seed=alias.split('-')[0];references={'original':by_alias['original'], 'nominal':by_alias[f'{seed}-nominal:0']}
            for reference,baseline in references.items():
                for law in spec['laws']:
                    comparisons.append(dict(plan=alias,reference=reference,law=law,
                        **paired_difference(row['regimes'][law]['outcomes'],baseline['regimes'][law]['outcomes'])))
    write_json(root/'validation.json',dict(status='PASS' if all(v['status']=='COMPLETE' for r in results for v in r['regimes'].values()) else 'PARTIAL',
        instance=instance,deadline=deadline,reference_C0=data['nominal_makespan'],generations=seal,plans=results,
        comparisons=comparisons,holdout_split=spec['validation_split'],generation=generation,
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))


def report(registry_path):
    registry=read_json(registry_path);root=Path('output/plan-report');root.mkdir(parents=True,exist_ok=True)
    records=[];rows=[];comparisons=[];missing=[]
    for index,tag in enumerate(registry['validations']):
        try:
            folder,_=fetch(tag,f'output/plan-report-input-{index}');record=read_json(folder/'validation.json')
        except Exception as error:missing.append(dict(release=tag,error=str(error)));continue
        records.append(record)
        for plan in record['plans']:
            for alias in plan['aliases']:
                for law,value in plan['regimes'].items():
                    ci=value['ci95'] or [None,None]
                    rows.append(dict(instance=record['instance'],plan=alias,plan_sha256=plan['plan_sha256'],law=law,
                        status=value['status'],nominal_makespan=plan['nominal_makespan']/100,
                        deadline=record['deadline']/100,samples=value['samples'],successes=value['successes'],
                        probability=value['probability'],ci95_lower=ci[0],ci95_upper=ci[1]))
        comparisons.extend(dict(instance=record['instance'],**row) for row in record['comparisons'])
    spec=read_json('provenance/plan_generation.json')
    complete=(len(records)==len(spec['instances']) and {r['instance'] for r in records}==set(spec['instances'])
        and all(r['status']=='PASS' for r in records) and not missing)
    result=dict(status='COMPLETE' if complete else 'PARTIAL',registry=registry,missing=missing,
        instances=[r['instance'] for r in records],evaluated_distinct_plans=sum(len(r['plans']) for r in records),
        per_regime_holdout=spec['validation_replications_per_law'],global_optimality_claimed=False,
        new_optimizer_or_model_advantage_claimed=False,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'RESULT.json',result);write_json(root/'registry.json',registry)
    write_json(root/'evidence.json.gz',records);write_json(root/'paired-comparisons.json',comparisons)
    if rows:
        with (root/'plans.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# Генерация производственных планов','',f"Статус: **{result['status']}**.",'',
        'Генерируются назначения операций и очередность на тех же станках. Срок и законы отказов нормированы исходным C0. '
        'Результаты относятся к лучшим найденным планам при заданном бюджете, без доказательства глобальной оптимальности.',
        '', '| Экземпляр | Вариант | Режим | Безотказная длительность | Успехов | Вероятность |', '|---|---|---|---:|---:|---:|']
    for row in rows:
        probability='—' if row['probability'] is None else f"{row['probability']:.6f}"
        lines.append(f"| {row['instance']} | {row['plan']} | {row['law']} | {row['nominal_makespan']:g} | {row['successes']}/{row['samples']} | {probability} |")
    lines += ['', '## Полная стоимость поиска','',
        '| Экземпляр | Seed | Цель | Время, с | Оценено | Cache hits | Ошибки | Остановка |','|---|---:|---|---:|---:|---:|---:|---|']
    for record in records:
        for entry in record['generation']['results']:
            r=entry['result'];s=r.get('stats',{})
            lines.append(f"| {record['instance']} | {entry['seed']} | {entry['objective']} | {r.get('total_s',0):.3f} | "
                f"{s.get('evaluated',0)} | {s.get('cache_hits',0)} | {s.get('failures',0)} | {r.get('stopping_reason','UNAVAILABLE')} |")
    lines += ['', 'Парные изменения относительно исходного и nominal-плана сохранены в paired-comparisons.json; '
        'интервалы относятся к отдельному сравнению и режиму, без общей гарантии для всех строк. '
        'Одинаковые сценарии и повторения поиска не увеличивают размер независимой проверочной выборки.',
        'Использован обычный поиск с прямой оценкой частоты успеха. При полных наблюдениях full-model R даёт ту же частоту; '
        'преимущество SIMPAT или новизна оптимизатора не заявляются. Pareto означает ограниченный найденный набор, а не полный фронт.',
        'Фактические улучшения и ухудшения следует читать вместе с неопределённостью и добавочной ценой поиска. '
        'Отсутствие подтверждённого выигрыша не заменяется различием внутренних fitness.',
        '', 'E1–E6 публикуются и принимаются отдельно.']
    for item in missing:lines.append('- '+json.dumps(item,ensure_ascii=False))
    (root/'REPORT_RU.md').write_text('\n'.join(lines)+'\n')


def main():
    actions_only();p=argparse.ArgumentParser();p.add_argument('task',choices=['generate','search','validate','report'])
    p.add_argument('input',nargs='?');p.add_argument('--instance');p.add_argument('--preflight')
    p.add_argument('--folder');p.add_argument('--objective');p.add_argument('--seed',type=int)
    a=p.parse_args()
    if a.task=='generate':generate(a.preflight,a.instance)
    elif a.task=='search':search_one(a.input,a.folder,a.objective,a.seed)
    elif a.task=='validate':validate(a.input,a.instance)
    else:report(a.input)


if __name__=='__main__':main()
