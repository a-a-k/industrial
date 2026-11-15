"""Frozen three-method probability-search comparison and independent holdout."""
import csv
from copy import deepcopy
import os
from pathlib import Path
import shutil
import sys
from .common import actions_only,canonical,digest,execute,read_json,rng,write_json
from .inputs import scenarios
from .plan_campaign import paired_difference,plan_identity
from .production import check_physics,compare,outcomes,product_ledger,simulate
from .releases import fetch


SOURCES=('planning/cpsat.py','planning/generator.py','planning/rerank.py',
    'industrial/plan.py','industrial/plan_campaign.py','industrial/inputs.py')


def profile():return read_json('provenance/planner_comparison.json')
def implementations():return {p:digest(Path(p).read_bytes()) for p in SOURCES}
def run_suffix():return os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
def generation_tag(instance,seed):return f'planner-pair-{instance}-{seed}-{run_suffix()}'


def verify():
    root=Path('output/planner-verification');root.mkdir(parents=True,exist_ok=True)
    write_json(root/'verification.json',dict(status='PASS',profile=profile(),implementation=implementations(),
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))


def generate(instance,seed,cp_python):
    spec=profile();root=Path('output/planner-pair');root.mkdir(parents=True,exist_ok=True)
    if instance not in spec['instances'] or seed not in spec['seeds']:raise ValueError('undeclared pair')
    verified,_=fetch('planner-verification-'+run_suffix(),'output/pair-verification')
    proof=read_json(verified/'verification.json')
    if proof['status']!='PASS' or proof['implementation']!=implementations():raise ValueError('unverified source')
    source,_=fetch(spec['preflight'],'output/pair-preflight');data=read_json(source/instance/'dataset.json')
    if read_json(source/'preflight.json')['status']!='PASS':raise ValueError('unavailable preflight')
    conditions=deepcopy(data);conditions['machines']=len(conditions.pop('queues'))
    conditions.pop('nominal_makespan')
    for op in conditions['operations']:
        for key in ('machine','work','planned_start','planned_end'):op.pop(key)
    deadline=data['nominal_makespan']*11//10
    problem=dict(conditions=conditions,deadline=deadline,spec=spec)
    write_json(root/'problem.json',problem);write_json(root/'original.json',data)
    calibration_hash=digest(canonical(scenarios(data,'F1',spec['search_split'],64)))
    order=list(spec['methods']);rng('planner-comparison-order',instance,seed).shuffle(order);records=[]
    for method in order:
        folder=root/method
        if method=='cp_pool_mc':module='planning.rerank';objective=[]
        else:module='industrial.plan';objective=['--objective','nominal' if method=='cp_nominal' else spec['objective']]
        command=[cp_python,'-m',module,str(root/'problem.json'),'--folder',str(folder),'--seed',str(seed),*objective]
        process=execute(command);record=dict(method=method,process=process,status='UNAVAILABLE')
        if process['status']=='OK':
            result=read_json(folder/'result.json')
            status=result['status'] if process['wall_s']<=240 else 'BUDGET_EXCEEDED'
            path=folder/('plan-00.json' if method=='hybrid' else 'schedule.json')
            if status=='PASS':
                plan=read_json(path);shutil.copyfile(path,root/(method+'.json'))
                if plan['nominal_makespan']!=data['nominal_makespan']:raise ValueError('failure normalization changed')
                if method!='cp_nominal':
                    actual=read_json(folder/'search-calendars.json.gz')['F1']
                    if digest(canonical(actual))!=calibration_hash:raise ValueError('different calibration information')
                record.update(plan_identity=plan_identity(plan),plan_sha256=digest(canonical(plan)),
                    physical_sha256=digest(canonical([(o['id'],o['machine'],o['work'],o['planned_start'],o['planned_end']) for o in plan['operations']])),
                    nominal_makespan=plan['planned_makespan'])
            record.update(status=status,result=result)
        records.append(record);write_json(root/'progress.json',dict(instance=instance,seed=seed,records=records))
    status='PASS' if len(records)==3 and all(r['status']=='PASS' for r in records) else 'PARTIAL'
    write_json(root/'generation.json',dict(status=status,instance=instance,seed=seed,profile=spec,
        implementation=implementations(),calibration_sha256=calibration_hash,method_order=order,records=records,
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))
    if status!='PASS':raise SystemExit('a required method did not complete; holdout remains closed')


def seal():
    root=Path('output/planner-seal');root.mkdir(parents=True,exist_ok=True);spec=profile();entries=[]
    for instance in spec['instances']:
        for seed in spec['seeds']:
            tag=generation_tag(instance,seed);source,receipt=fetch(tag,f'output/seal-{instance}-{seed}')
            generation=read_json(source/'generation.json')
            if (generation['status']!='PASS' or generation['profile']!=spec
                    or generation['implementation']!=implementations()):raise ValueError('all pairs must be frozen and qualified')
            entries.append(dict(instance=instance,seed=seed,release=tag,archive_sha256=receipt['archive_sha256']))
    write_json(root/'seal.json',dict(status='SEALED',profile=spec,generations=entries,
        role='all nine pairs before any new holdout',commit=os.environ['GITHUB_SHA']))


def validate(instance):
    spec=profile();root=Path('output/planner-validation');root.mkdir(parents=True,exist_ok=True)
    frozen,_=fetch('planner-seal-'+run_suffix(),'output/validation-seal');sealed=read_json(frozen/'seal.json')
    if sealed['status']!='SEALED' or sealed['profile']!=spec or len(sealed['generations'])!=9:raise ValueError('incomplete freeze')
    plans={};generations=[];data=None
    for entry in sealed['generations']:
        if entry['instance']!=instance:continue
        source,receipt=fetch(entry['release'],f"output/validate-source-{entry['seed']}")
        if receipt['archive_sha256']!=entry['archive_sha256']:raise ValueError('generation archive changed')
        generation=read_json(source/'generation.json');generations.append(generation)
        data=read_json(source/'original.json');plans.setdefault(plan_identity(data),dict(plan=data,aliases=['original']))
        for method in spec['methods']:
            plan=read_json(source/(method+'.json'));row=next(r for r in generation['records'] if r['method']==method)
            if digest(canonical(plan))!=row['plan_sha256']:raise ValueError('selected plan changed')
            plans.setdefault(plan_identity(plan),dict(plan=plan,aliases=[]))['aliases'].append(f"{generation['seed']}:{method}")
    if len(generations)!=3:raise ValueError('missing generation seed')
    deadline=11*data['nominal_makespan']//10;results=[]
    banks={law:scenarios(data,law,spec['validation_split'],1024) for law in spec['laws']}
    for key,entry in plans.items():
        plan=entry['plan'];folder=root/key;write_json(folder/'schedule.json',plan)
        with (folder/'schedule.csv').open('w',newline='') as stream:
            fields=['id','job','machine','work','planned_start','planned_end'];writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
            writer.writeheader();writer.writerows(plan['operations'])
        regimes={}
        for law,bank in banks.items():
            subset=sorted(bank,key=lambda s:digest(('planner-comparison-S1|'+s['id']).encode()))[:128]
            outputs={};processes=[];errors=[]
            for engine in ('des','dag','tsfg'):
                current=subset if engine=='tsfg' else bank
                trajectories,ps=simulate(plan,current,folder/law/engine,engine,deadline,chunk=16 if engine=='tsfg' else 128)
                outputs[engine]=trajectories;processes.extend(ps)
                for scenario in current:
                    if scenario['id'] not in trajectories:continue
                    try:check_physics(plan,scenario,trajectories[scenario['id']])
                    except Exception as error:errors.append(str(error))
            for engine in ('dag','tsfg'):
                for aid in outputs[engine].keys() & outputs['des'].keys():
                    try:compare(outputs['des'][aid],outputs[engine][aid])
                    except Exception as error:errors.append(str(error))
            ledger=product_ledger(plan,bank,outputs['des']);write_json(folder/law/'product-ledger.json.gz',ledger)
            labels=outcomes(ledger,[j['id'] for j in plan['jobs']],deadline)
            complete=(len(outputs['des'])==len(outputs['dag'])==1024 and len(outputs['tsfg'])==128
                and not errors and all(p['status']=='OK' for p in processes) and all(v is not None for v in labels.values()))
            regimes[law]=dict(status='COMPLETE' if complete else 'PARTIAL',outcomes=labels,
                samples=1024,successes=sum(v is True for v in labels.values()),processes=processes,errors=errors)
            write_json(folder/law/'result.json',regimes[law])
        results.append(dict(plan_identity=key,aliases=entry['aliases'],nominal_makespan=plan['planned_makespan'] if 'planned_makespan' in plan else plan['nominal_makespan'],regimes=regimes))
        write_json(root/'progress.json',dict(instance=instance,plans=results))
    status='PASS' if all(r['status']=='COMPLETE' for p in results for r in p['regimes'].values()) else 'PARTIAL'
    write_json(root/'validation.json',dict(status=status,instance=instance,profile=spec,plans=results,
        generations=generations,seal=sealed,deadline=deadline,commit=os.environ['GITHUB_SHA']))
    if status!='PASS':raise SystemExit('required independent validation incomplete')


def report(source_run=None):
    spec=profile();root=Path('output/planner-report');root.mkdir(parents=True,exist_ok=True)
    suffix=source_run or run_suffix()
    if len(suffix.split('-'))!=2 or not all(p.isdigit() for p in suffix.split('-')):raise ValueError('invalid source run suffix')
    records=[];missing=[];comparisons=[];rows=[];benefits=[];identical=[];identical_costs=[]
    for instance in spec['instances']:
        tag='planner-validation-'+instance+'-'+suffix
        try:
            source,_=fetch(tag,'output/report-'+instance);validation=read_json(source/'validation.json')
            if validation['profile']!=spec:raise ValueError('validation protocol mismatch')
        except Exception as error:missing.append(dict(instance=instance,error=str(error)));continue
        records.append(validation);by_alias={a:p for p in validation['plans'] for a in p['aliases']}
        for generation in validation['generations']:
            seed=generation['seed'];methods={r['method']:r for r in generation['records']}
            for method,r in methods.items():
                details=r['result'];p=by_alias[f'{seed}:{method}'];row=dict(instance=instance,seed=seed,method=method,
                    optimizer_wall_s=r['process']['wall_s'],nominal_makespan=p['nominal_makespan']/100,
                    F1=p['regimes']['F1']['successes']/1024,F2=p['regimes']['F2']['successes']/1024,
                    cpu_self_s=details.get('cpu_self_s',details.get('cpu_s')),
                    cpu_children_s=details.get('cpu_children_s',0),peak_rss_bytes=details.get('peak_rss_bytes'),
                    preparation_s=details.get('preparation_s'),
                    evaluated_candidates=details.get('evaluated_candidates',details.get('stats',{}).get('evaluated')),
                    stopping_reason=details.get('stopping_reason',details.get('solver_status')))
                rows.append(row)
            for law in spec['laws']:
                a=by_alias[f'{seed}:hybrid']['regimes'][law];local=[]
                for baseline in ('cp_nominal','cp_pool_mc'):
                    b=by_alias[f'{seed}:{baseline}']['regimes'][law]
                    value=paired_difference(a['outcomes'],b['outcomes'],alpha=.05/144)
                    value.update(instance=instance,seed=seed,law=law,baseline=baseline,
                        hybrid_wall_s=methods['hybrid']['process']['wall_s'],baseline_wall_s=methods[baseline]['process']['wall_s'])
                    value['no_greater_actual_wall_cost']=value['hybrid_wall_s']<=value['baseline_wall_s']
                    comparisons.append(value);local.append(value)
                if law=='F1' and all(v['status']=='OK' and v['outer95'][0]>0 and v['no_greater_actual_wall_cost'] for v in local):
                    benefits.append(dict(instance=instance,seed=seed))
            for baseline in ('cp_nominal','cp_pool_mc'):
                if methods['hybrid']['physical_sha256']==methods[baseline]['physical_sha256']:
                    hw=methods['hybrid']['process']['wall_s'];bw=methods[baseline]['process']['wall_s']
                    identical_costs.append(dict(instance=instance,seed=seed,baseline=baseline,
                        faster_method='hybrid' if hw<bw else baseline if bw<hw else 'equal',
                        hybrid_wall_s=hw,baseline_wall_s=bw,hybrid_to_baseline_wall_ratio=hw/bw))
                    if hw<bw:identical.append(dict(instance=instance,seed=seed,baseline=baseline))
    complete=len(records)==3 and all(r['status']=='PASS' for r in records) and len(comparisons)==36 and all(r['status']=='OK' for r in comparisons) and not missing
    result=dict(status='COMPLETE' if complete else 'PARTIAL',profile=spec,missing=missing,
        clear_benefit_conditions=benefits,exact_same_plan_lower_cost=identical,
        hybrid_exact_same_plan_lower_cost=identical,identical_schedule_cost_comparisons=identical_costs,
        registered_conditions=9,all_registered_conditions_show_clear_benefit=len(benefits)==9,
        comparisons=comparisons,unique_validation_scenarios=6144,
        optimizer_novelty_claimed=False,SIMPAT_superiority_claimed=False,
        completed_runner_hours_before_report=read_json('output/budget.json')['completed_s']/3600,
        source_run=suffix,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'RESULT.json',result);write_json(root/'evidence.json.gz',records)
    if rows:
        with (root/'plans.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# Поиск по вероятности против готовых альтернатив','',f"Статус проверки: **{result['status']}**.",'',
        'Первичная цель — вероятность выполнить всю партию к прежнему сроку в F1. Станки, исходный C0, '
        'срок, законы и калибровочная информация одинаковы. Каждый метод получил верхний бюджет 240 секунд. '
        'Фактические затраты различаются и показаны отдельно; подготовка и остановки входят в них.',
        '', '| Экземпляр | Seed | Метод | Длительность | F1, % | F2, % | Затраты поиска, с |','|---|---:|---|---:|---:|---:|---:|']
    for r in rows:lines.append(f"| {r['instance']} | {r['seed']} | {r['method']} | {r['nominal_makespan']:g} | {100*r['F1']:.2f} | {100*r['F2']:.2f} | {r['optimizer_wall_s']:.3f} |")
    lines+=['', '| Экземпляр | Seed | Закон | Hybrid относительно | Изменение, п.п. | Совместная 95%-я область, п.п. | Hybrid не дороже |','|---|---:|---|---|---:|---:|---|']
    for r in comparisons:
        if r['status']=='OK':
            lo,hi=r['outer95'];lines.append(f"| {r['instance']} | {r['seed']} | {r['law']} | {r['baseline']} | {100*r['difference']:+.2f} | [{100*lo:+.2f}; {100*hi:+.2f}] | {r['no_greater_actual_wall_cost']} |")
    lines+=['',f"Объявленный критерий улучшения вероятности при не большей фактической цене против обоих baseline выполнен в {len(benefits)} из 9 зарегистрированных условий.",
        f"Совпадения физического расписания: {len(identical_costs)}; из них hybrid дешевле в {len(identical)} сравнений.",
        'Отсутствие значимого различия вероятностей не объявляется эквивалентностью. '
        'Результат относится к фиксированным экземплярам и seed; удачный seed по проверочным исходам не выбирается.',
        'Все планы зафиксированы до нового holdout. Для 36 сравнений использованы 144 односторонние биномиальные границы '
        'с alpha=0,05/144; совместное покрытие не ниже 95%. Повторные планы и seeds не увеличивают n=1024 на закон и экземпляр.',
        'cp_nominal — обычный CP-SAT; cp_pool_mc — его кандидаты с прямым MC-отбором; hybrid — CP с локальным поиском. '
        'Новизна оптимизатора и преимущество SIMPAT не заявляются. Качество worst-regime и Pareto этой проверкой не установлено.',
        f"До отчётного задания израсходовано {result['completed_runner_hours_before_report']:.3f} из 72 runner-часов. "
        'Общая установка среды, сборки, квалификация и независимая проверка включены в кампанию; времена методов указаны отдельно.']
    lines+=['', '| Экземпляр | Seed | Совпавший baseline | Более быстрый способ | Hybrid, с | Baseline, с |', '|---|---:|---|---|---:|---:|']
    for row in identical_costs:
        lines.append(f"| {row['instance']} | {row['seed']} | {row['baseline']} | {row['faster_method']} | {row['hybrid_wall_s']:.3f} | {row['baseline_wall_s']:.3f} |")
    for item in missing:lines.append('- '+str(item))
    (root/'REPORT_RU.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    actions_only();task=sys.argv[1]
    if task=='verify':verify()
    elif task=='generate':generate(sys.argv[2],int(sys.argv[3]),sys.argv[4])
    elif task=='seal':seal()
    elif task=='validate':validate(sys.argv[2])
    elif task=='report':report(sys.argv[2] if len(sys.argv)>2 else None)
    else:raise SystemExit('unknown comparison stage')
