"""Frozen common-prefix control; no new optimizer execution."""
import csv
import os
from pathlib import Path
import shutil
import sys
from .common import actions_only,canonical,digest,read_json,write_json
from .inputs import scenarios
from .plan_campaign import paired_difference,plan_identity
from .planner_comparison import implementations,profile as source_profile,run_suffix
from .production import check_physics,compare,outcomes,product_ledger,simulate
from .releases import fetch


def profile():return read_json('provenance/prefix_comparison.json')
def physical(plan):return digest(canonical([(o['id'],o['machine'],o['work'],o['planned_start'],o['planned_end']) for o in plan['operations']]))


def seal():
    spec=profile();root=Path('output/prefix-seal');root.mkdir(parents=True,exist_ok=True);entries=[]
    for instance in spec['instances']:
        for seed in spec['seeds']:
            tag=f"planner-pair-{instance}-{seed}-{spec['source_generation_run']}"
            source,receipt=fetch(tag,f'output/prefix-source-{instance}-{seed}')
            gen=read_json(source/'generation.json')
            if gen['status']!='PASS' or gen['profile']!=source_profile() or gen['implementation']!=implementations():
                raise ValueError('unavailable or changed source generation')
            folder=root/instance/str(seed);folder.mkdir(parents=True)
            shutil.copyfile(source/'original.json',root/instance/'original.json');methods={}
            for row in gen['records']:
                method=row['method'];plan=read_json(source/(method+'.json'))
                if digest(canonical(plan))!=row['plan_sha256']:raise ValueError('source plan checksum mismatch')
                shutil.copyfile(source/(method+'.json'),folder/(method+'.json'))
                methods[method]=dict(wall_s=row['process']['wall_s'],cost_type='complete measured optimization process',
                    physical_sha256=physical(plan),result=row['result'])
            hybrid=next(r for r in gen['records'] if r['method']=='hybrid');hr=hybrid['result']
            prefix=read_json(source/'hybrid/cp-seed/schedule.json')
            shutil.copyfile(source/'hybrid/cp-seed/schedule.json',folder/'cp_short.json')
            overhead=max(0.,hybrid['process']['wall_s']-hr['total_interface_s'])
            prefix_wall=hr['preparation_s']+overhead
            if prefix_wall>=hybrid['process']['wall_s']:raise ValueError('prefix accounting cannot invent a cheaper full hybrid')
            methods['cp_short']=dict(wall_s=prefix_wall,cost_type=spec['cp_short_cost'],
                observed_preparation_s=hr['preparation_s'],allocated_process_overhead_s=overhead,
                cp_only_wall_s=hr['cp_seed']['model_build_and_search_s'],cp_only_cpu_s=hr['cp_seed']['cpu_s'],
                physical_sha256=physical(prefix))
            for method in spec['methods']:
                plan=read_json(folder/(method+'.json'))
                with (folder/(method+'.csv')).open('w',newline='') as stream:
                    fields=['id','job','machine','work','planned_start','planned_end']
                    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
                    writer.writeheader();writer.writerows(plan['operations'])
            entries.append(dict(instance=instance,seed=seed,generation_release=tag,
                archive_sha256=receipt['archive_sha256'],methods=methods))
    write_json(root/'seal.json',dict(status='SEALED',profile=spec,entries=entries,
        role='all four-method plans frozen before new common holdout',commit=os.environ['GITHUB_SHA']))


def validate(instance):
    spec=profile();root=Path('output/prefix-validation');root.mkdir(parents=True,exist_ok=True)
    source,receipt=fetch('prefix-seal-'+run_suffix(),'output/prefix-frozen')
    sealed=read_json(source/'seal.json')
    if sealed['status']!='SEALED' or sealed['profile']!=spec or len(sealed['entries'])!=9:raise ValueError('invalid four-method freeze')
    data=read_json(source/instance/'original.json');deadline=11*data['nominal_makespan']//10
    plans={plan_identity(data):dict(plan=data,aliases=['original'])}
    for entry in sealed['entries']:
        if entry['instance']!=instance:continue
        for method in spec['methods']:
            plan=read_json(source/instance/str(entry['seed'])/(method+'.json'))
            if physical(plan)!=entry['methods'][method]['physical_sha256']:raise ValueError('frozen physical schedule changed')
            plans.setdefault(plan_identity(plan),dict(plan=plan,aliases=[]))['aliases'].append(f"{entry['seed']}:{method}")
    banks={law:scenarios(data,law,spec['validation_split'],1024) for law in spec['laws']};results=[]
    for key,entry in plans.items():
        plan=entry['plan'];folder=root/key;write_json(folder/'schedule.json',plan);regimes={}
        for law,bank in banks.items():
            chosen=sorted(bank,key=lambda s:digest(('prefix-S1|'+s['id']).encode()))[:128]
            outputs={};processes=[];errors=[]
            for engine in ('des','dag','tsfg'):
                current=chosen if engine=='tsfg' else bank
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
        results.append(dict(plan_identity=key,aliases=entry['aliases'],regimes=regimes,
            nominal_makespan=plan.get('planned_makespan',plan['nominal_makespan'])))
        write_json(root/'progress.json',dict(instance=instance,plans=results))
    status='PASS' if all(r['status']=='COMPLETE' for p in results for r in p['regimes'].values()) else 'PARTIAL'
    write_json(root/'validation.json',dict(status=status,instance=instance,profile=spec,plans=results,
        entries=[e for e in sealed['entries'] if e['instance']==instance],seal_archive_sha256=receipt['archive_sha256'],
        commit=os.environ['GITHUB_SHA']))
    if status!='PASS':raise SystemExit('incomplete four-method validation')


def report():
    spec=profile();root=Path('output/prefix-report');root.mkdir(parents=True,exist_ok=True)
    records=[];rows=[];comparisons=[];equality=[];missing=[]
    for instance in spec['instances']:
        tag='prefix-validation-'+instance+'-'+run_suffix()
        try:
            source,_=fetch(tag,'output/prefix-report-'+instance);validation=read_json(source/'validation.json')
            if validation['profile']!=spec:raise ValueError('validation protocol changed')
        except Exception as error:missing.append(dict(instance=instance,error=str(error)));continue
        records.append(validation);aliases={a:p for p in validation['plans'] for a in p['aliases']}
        for entry in validation['entries']:
            seed=entry['seed'];methods=entry['methods']
            for method in spec['methods']:
                plan=aliases[f'{seed}:{method}'];cost=methods[method]
                rows.append(dict(instance=instance,seed=seed,method=method,wall_s=cost['wall_s'],
                    cost_type=cost['cost_type'],nominal_makespan=plan['nominal_makespan']/100,
                    F1=plan['regimes']['F1']['successes']/1024,F2=plan['regimes']['F2']['successes']/1024))
            same=methods['hybrid']['physical_sha256']==methods['cp_short']['physical_sha256']
            equality.append(dict(instance=instance,seed=seed,hybrid_equals_prefix=same,
                hybrid_wall_s=methods['hybrid']['wall_s'],prefix_attributed_wall_s=methods['cp_short']['wall_s'],
                minimum_extra_wall_s=methods['hybrid']['wall_s']-methods['cp_short']['wall_s']))
            for law in spec['laws']:
                a=aliases[f'{seed}:hybrid']['regimes'][law]
                for baseline in ('cp_nominal','cp_pool_mc','cp_short'):
                    b=aliases[f'{seed}:{baseline}']['regimes'][law]
                    comparisons.append(dict(instance=instance,seed=seed,law=law,baseline=baseline,
                        **paired_difference(a['outcomes'],b['outcomes'],alpha=.05/216),
                        hybrid_wall_s=methods['hybrid']['wall_s'],baseline_wall_s=methods[baseline]['wall_s'],
                        baseline_cost_type=methods[baseline]['cost_type']))
    complete=len(records)==3 and all(r['status']=='PASS' for r in records) and len(comparisons)==54 and all(r['status']=='OK' for r in comparisons) and not missing
    result=dict(status='COMPLETE' if complete else 'PARTIAL',profile=spec,missing=missing,
        comparisons=comparisons,prefix_equalities=equality,hybrid_equals_prefix_count=sum(r['hybrid_equals_prefix'] for r in equality),
        registered_conditions=9,local_search_advantage_at_no_greater_cost_claimed=False,
        cp_short_standalone_runtime_claimed=False,unique_validation_scenarios=6144,
        optimizer_runs_repeated=False,original_cost_criterion_relaxed=False,
        completed_runner_hours_before_report=read_json('output/budget.json')['completed_s']/3600,
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'RESULT.json',result);write_json(root/'evidence.json.gz',records)
    if rows:
        with (root/'plans.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# Короткий CP как обязательный контроль','',f"Статус проверки: **{result['status']}**.",'',
        'CP-short — фактически исполненный и сохранённый общий префикс hybrid. Его цена — наблюдённое окно подготовки '
        'с явно отнесёнными накладными расходами запуска/завершения; это не независимый standalone runtime.',
        'Все планы извлечены из прежних зафиксированных выпусков. Новых оптимизаций нет; '
        'четыре способа проверены на новом общем банке после отдельной фиксации.',
        '', '| Экземпляр | Seed | Метод | Длительность | F1, % | F2, % | Время / отнесённое окно, с |','|---|---:|---|---:|---:|---:|---:|']
    for row in rows:lines.append(f"| {row['instance']} | {row['seed']} | {row['method']} | {row['nominal_makespan']:g} | {100*row['F1']:.2f} | {100*row['F2']:.2f} | {row['wall_s']:.3f} |")
    lines+=['',f"Hybrid вернул точное физическое расписание своего CP-префикса в {result['hybrid_equals_prefix_count']} из 9 условий.",
        'При таком совпадении локальный поиск не улучшает полезный результат и добавляет расход. '
        'Любой прирост вероятности относительно префикса имеет дополнительную цену; прежний критерий затрат не ослабляется.',
        '', '| Экземпляр | Seed | Закон | Hybrid относительно | Изменение, п.п. | Совместная 95%-я область, п.п. |','|---|---:|---|---|---:|---:|']
    for row in comparisons:
        if row['status']=='OK':
            lo,hi=row['outer95'];lines.append(f"| {row['instance']} | {row['seed']} | {row['law']} | {row['baseline']} | {100*row['difference']:+.2f} | [{100*lo:+.2f}; {100*hi:+.2f}] |")
    lines+=['', '54 фиксированных сравнения используют 216 односторонних точных биномиальных границ alpha=0,05/216. '
        'Совместное покрытие не ниже 95%; повторение seeds не увеличивает n=1024 на экземпляр и закон. '
        'Удачный seed по проверочным исходам не выбирается.',
        'Новизна оптимизатора и преимущество SIMPAT не заявляются. Сырые RSS относятся к жизненному циклу процесса, включая историю запуска.',
        f"До задания отчёта израсходовано {result['completed_runner_hours_before_report']:.3f} из 72 runner-часов."]
    for item in missing:lines.append('- '+str(item))
    (root/'REPORT_RU.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    actions_only();task=sys.argv[1]
    if task=='seal':seal()
    elif task=='validate':validate(sys.argv[2])
    elif task=='report':report()
    else:raise SystemExit('unknown prefix-control stage')
