"""A fixed strong planning baseline and a fresh paired production holdout."""
import csv
import os
from pathlib import Path
import shutil
import sys
from .common import actions_only,canonical,digest,execute,read_json,write_json
from .inputs import scenarios
from .production import simulate,check_physics,compare,product_ledger,outcomes
from .plan_campaign import plan_identity,paired_difference
from .releases import fetch

INSTANCES=('Mk01','Mk05','Mk10')
PROFILE=dict(version='cpsat-baseline-v1',instances=INSTANCES,ortools='9.15.6755',seed=1701,
    budget_s=240,workers=1,validation_split='cpsat-holdout-v1',replications_per_law=1024,
    tsfg_subset=128,deadline_multiplier=[11,10],references=['original','heuristic','cpsat'])


def generate(preflight,cp_python,environment):
    root=Path('output/cpsat-plans');root.mkdir(parents=True,exist_ok=True)
    source,_=fetch(preflight,'output/cpsat-preflight')
    if read_json(source/'preflight.json')['status']!='PASS':raise ValueError('preflight unavailable')
    old_refs=read_json('results/plan-generation/nominal-reference.json')['instances']
    refs={r['instance']:r for r in old_refs};results=[]
    for instance in INSTANCES:
        folder=root/instance;folder.mkdir();original=read_json(source/instance/'dataset.json')
        previous=read_json(Path('results/plans')/(instance+'.json'))
        if plan_identity(previous)!=refs[instance]['plan_sha256']:raise ValueError('prior plan identity changed')
        write_json(folder/'original.json',original);write_json(folder/'heuristic.json',previous)
        write_json(folder/'problem.json',dict(dataset=original))
        process=execute([cp_python,'-m','planning.cpsat',str(folder/'problem.json'),str(folder/'cp'),
            '--budget','240','--seed','1701'])
        entry=dict(instance=instance,process=process,status='UNAVAILABLE')
        if process['status']=='OK':
            result=read_json(folder/'cp/result.json');plan=read_json(folder/'cp/schedule.json');controls=[]
            if process['wall_s']>240:result['status']='BUDGET_EXCEEDED'
            scenario=dict(id='cpsat-nominal-'+instance,failures=[],work_overrides=[]);trajectories=[]
            for engine in ('des','dag','tsfg'):
                rows,ps=simulate(plan,[scenario],folder/'nominal'/engine,engine,5*original['nominal_makespan']//4)
                controls.extend(ps)
                if scenario['id'] not in rows:raise ValueError('CP nominal execution unavailable')
                trajectory=rows[scenario['id']];check_physics(plan,scenario,trajectory);trajectories.append(trajectory)
                if trajectory['cmax']!=plan['planned_makespan']:raise ValueError('CP nominal result differs from independent execution')
            compare(trajectories[0],trajectories[1]);compare(trajectories[0],trajectories[2])
            entry.update(status=result['status'],solver=result,nominal_processes=controls,
                plan_sha256=digest(canonical(plan)),plan_identity=plan_identity(plan),
                heuristic_nominal_makespan=previous['planned_makespan'],original_nominal_makespan=original['nominal_makespan'])
        results.append(entry);write_json(root/'progress.json',dict(results=results))
    status='PASS' if len(results)==3 and all(r['status']=='PASS' for r in results) else 'PARTIAL'
    write_json(root/'generation.json',dict(status=status,profile=PROFILE,results=results,preflight=preflight,
        cp_environment=environment,previous_report='plan-report-43709977990-1',
        role='all candidates frozen before the new holdout',commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))
    if status!='PASS':raise SystemExit('CP generation incomplete; no fresh holdout opened')


def validate(generation_tag):
    root=Path('output/cpsat-validation');root.mkdir(parents=True,exist_ok=True)
    source,receipt=fetch(generation_tag,'output/cpsat-frozen-plans');generation=read_json(source/'generation.json')
    if generation['status']!='PASS' or generation['profile']!=dict(PROFILE,instances=list(INSTANCES)):
        raise ValueError('CP candidates or protocol not frozen')
    write_json(root/'freeze.json',dict(release=generation_tag,archive_sha256=receipt['archive_sha256']))
    records=[]
    for instance in INSTANCES:
        original=read_json(source/instance/'original.json');deadline=11*original['nominal_makespan']//10
        plans={'original':original,'heuristic':read_json(source/instance/'heuristic.json'),
            'cpsat':read_json(source/instance/'cp/schedule.json')}
        for law in ('F1','F2'):
            bank=scenarios(original,law,PROFILE['validation_split'],1024)
            chosen=sorted(bank,key=lambda s:digest(('CP-S1-v1|'+s['id']).encode()))[:128]
            write_json(root/instance/law/'scenarios.json.gz',bank)
            for label,plan in plans.items():
                folder=root/instance/law/label;outputs={};processes=[];errors=[]
                for engine in ('des','dag','tsfg'):
                    current=chosen if engine=='tsfg' else bank
                    trajectories,ps=simulate(plan,current,folder/engine,engine,deadline,chunk=16 if engine=='tsfg' else 128)
                    processes.extend(ps);outputs[engine]=trajectories
                    for scenario in current:
                        if scenario['id'] not in trajectories:continue
                        try:check_physics(plan,scenario,trajectories[scenario['id']])
                        except Exception as error:errors.append(str(error))
                for engine in ('dag','tsfg'):
                    for aid in outputs[engine].keys() & outputs['des'].keys():
                        try:compare(outputs['des'][aid],outputs[engine][aid])
                        except Exception as error:errors.append(str(error))
                ledger=product_ledger(plan,bank,outputs['des']);write_json(folder/'product-ledger.json.gz',ledger)
                labels=outcomes(ledger,[j['id'] for j in plan['jobs']],deadline)
                complete=(len(outputs['des'])==len(outputs['dag'])==1024 and len(outputs['tsfg'])==128
                    and not errors and all(p['status']=='OK' for p in processes) and all(v is not None for v in labels.values()))
                row=dict(instance=instance,law=law,plan=label,status='COMPLETE' if complete else 'PARTIAL',
                    deadline=deadline,nominal_makespan=max(o['planned_end'] for o in plan['operations']),
                    samples=1024,successes=sum(v is True for v in labels.values()),outcomes=labels,processes=processes,errors=errors)
                records.append(row);write_json(folder/'result.json',row)
                write_json(root/'progress.json',dict(records=records))
    status='PASS' if len(records)==18 and all(r['status']=='COMPLETE' for r in records) else 'PARTIAL'
    write_json(root/'validation.json',dict(status=status,generation=generation,records=records,
        generation_release=generation_tag,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))


def report():
    root=Path('output/cpsat-report');root.mkdir(parents=True,exist_ok=True)
    validation=read_json('output/cpsat-validation/validation.json');generation=validation['generation'];rows=validation['records']
    by_key={(r['instance'],r['law'],r['plan']):r for r in rows};comparisons=[]
    for instance in INSTANCES:
        for law in ('F1','F2'):
            current=by_key[instance,law,'cpsat']
            for name in ('original','heuristic'):
                baseline=by_key[instance,law,name]
                comparisons.append(dict(instance=instance,law=law,reference=name,
                    **paired_difference(current['outcomes'],baseline['outcomes'],alpha=.05/48)))
    result=dict(status='COMPLETE' if validation['status']=='PASS' else 'PARTIAL',profile=PROFILE,
        generation=generation['results'],comparisons=comparisons,unique_validation_scenarios=6144,
        global_stochastic_optimality_claimed=False,new_optimizer_claimed=False,
        environment=generation['cp_environment'],commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'RESULT.json',result);write_json(root/'validation.json.gz',validation)
    fields=['instance','law','plan','status','nominal_makespan','deadline','samples','successes']
    with (root/'plans.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    lines=['# Сильный планировщик CP-SAT','',f"Статус: **{result['status']}**.",'',
        'Стандартный CP-SAT сравнивается с исходным планом и предыдущим лучшим эвристическим вариантом. '
        'Назначения, предшествование и непересечение операций задаются обычной моделью FJSP. '
        'Все планы зафиксированы до нового проверочного банка. Станки, сроки и нормировка отказов сохранены.',
        '', '| Экземпляр | CP статус | Длительность исходная / эвристика / CP | CP нижняя граница | Время CP, с |','|---|---|---:|---:|---:|']
    for r in generation['results']:
        s=r['solver']
        lines.append(f"| {r['instance']} | {s['solver_status']} | {r['original_nominal_makespan']/100:g} / {r['heuristic_nominal_makespan']/100:g} / "
            f"{s['planned_makespan']/100:g} | {s['lower_bound_ticks']/100:g} | {r['process']['wall_s']:.3f} |")
    lines += ['', '| Экземпляр | Режим | Исходный | Эвристика | CP |', '|---|---|---:|---:|---:|']
    for instance in INSTANCES:
        for law in ('F1','F2'):
            values=[by_key[instance,law,label] for label in ('original','heuristic','cpsat')]
            lines.append(f"| {instance} | {law} | "+' | '.join(f"{100*r['successes']/1024:.2f}%" if r['status']=='COMPLETE' else '—' for r in values)+' |')
    lines += ['', '| Экземпляр | Режим | CP относительно | Изменение, п.п. | Совместная 95%-я область, п.п. |','|---|---|---|---:|---:|']
    for r in comparisons:
        if r['status']=='OK':
            lo,hi=r['outer95'];lines.append(f"| {r['instance']} | {r['law']} | {r['reference']} | {100*r['difference']:+.2f} | [{100*lo:+.2f}; {100*hi:+.2f}] |")
    lines += ['', 'Для двенадцати фиксированных сравнений использованы 48 односторонних биномиальных границ с alpha=0,05/48. '
        'Совместное покрытие не ниже 95%; повторение сценариев по планам не увеличивает n. '
        'FEASIBLE означает найденное допустимое решение, а не доказанный оптимум. OPTIMAL относится только к номинальной задаче.',
        'Новая среда OR-Tools изолирована от исходной научной среды. Время включает построение модели и сохранение результата; '
        'одноразовая сборка среды, компиляции и независимая проверка учтены в общем runner-бюджете. '
        'Дорогой прежний эвристический план не использовался как hint. Новизна оптимизатора и глобальная стохастическая оптимальность не заявляются.']
    (root/'REPORT_RU.md').write_text('\n'.join(lines)+'\n')


def export(generation_tag):
    source,receipt=fetch(generation_tag,'output/cpsat-export-input')
    generation=read_json(source/'generation.json')
    if generation['status']!='PASS':raise ValueError('incomplete frozen plans')
    root=Path('output/cpsat-report/schedules');root.mkdir(parents=True,exist_ok=True)
    for instance in INSTANCES:
        original=source/instance/'cp/schedule.json';plan=read_json(original)
        shutil.copyfile(original,root/(instance+'.json'))
        with (root/(instance+'.csv')).open('w',newline='') as stream:
            fields=['id','job','machine','work','planned_start','planned_end']
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
            writer.writeheader();writer.writerows(plan['operations'])
    write_json(root/'provenance.json',dict(release=generation_tag,
        archive_sha256=receipt['archive_sha256'],times='integer ticks; 100 ticks per original time unit',
        machine_indices='zero based',original_reference_C0_preserved=True))


if __name__=='__main__':
    actions_only();task=sys.argv[1]
    if task=='generate':generate(sys.argv[2],sys.argv[3],sys.argv[4])
    elif task=='validate':validate(sys.argv[2])
    elif task=='report':report()
    elif task=='export':export(sys.argv[2])
    else:raise SystemExit('unknown CP baseline stage')
