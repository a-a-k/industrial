"""Read-only audit of retained CP pools; never imports holdout outcomes."""
import csv
import math
import os
from pathlib import Path
from .common import actions_only,canonical,digest,read_json,write_json
from .plan_campaign import plan_identity
from .releases import fetch
from planning.generator import decode,from_conditions,initial_genome

ROOT=Path('output/decision-options')
SOURCE_RUN='43730898043-1'
INSTANCES=('Mk01','Mk05','Mk10')
SEEDS=(1701,1702,1703)


def physical(plan):
    keys=('id','job','machine','work','planned_start','planned_end','release','predecessors')
    return digest(canonical(dict(operations=[{k:o[k] for k in keys} for o in plan['operations']],
        queues=plan['queues'],jobs=plan['jobs'],delta=plan['delta'])))


def features(plan,deadline):
    ops=plan['operations'];children=[set() for _ in ops]
    for op in ops:
        for p in op['predecessors']:children[p].add(op['id'])
    loads=[]
    for queue in plan['queues']:
        loads.append(sum(ops[i]['work'] for i in queue))
        for a,b in zip(queue,queue[1:]):children[a].add(b)
    latest={}
    for i in sorted(range(len(ops)),key=lambda i:(ops[i]['planned_start'],i),reverse=True):
        if any(ops[i]['planned_end']>ops[j]['planned_start'] for j in children[i]):raise ValueError('infeasible precedence')
        latest[i]=min([deadline,*[latest[j] for j in children[i]]])-ops[i]['work']
    floats=[latest[o['id']]-o['planned_start'] for o in ops]
    total=sum(o['work'] for o in ops);repair_mean=.1*plan['nominal_makespan']
    return dict(nominal_makespan=max(o['planned_end'] for o in ops),maximum_machine_load=max(loads),
        squared_machine_load=sum(v*v for v in loads),minimum_deadline_float=min(floats),
        work_weighted_deadline_float=sum(o['work']*floats[o['id']] for o in ops)/total,
        repair_exposure_proxy=sum(o['work']*math.exp(-max(0,floats[o['id']])/repair_mean) for o in ops))


def structural(plan):
    """Simple machine relabelings are identical under homogeneous F1/F2."""
    ops=plan['operations'];children=[set() for _ in ops]
    for o in ops:
        for p in o['predecessors']:children[p].add(o['id'])
    for queue in plan['queues']:
        for a,b in zip(queue,queue[1:]):children[a].add(b)
    order=sorted(range(len(ops)),key=lambda i:(ops[i]['planned_start'],i))
    cmax=max(o['planned_end'] for o in ops);latest={}
    for i in reversed(order):latest[i]=min([cmax,*[latest[j] for j in children[i]]])-ops[i]['work']
    critical={i for i in order if latest[i]==ops[i]['planned_start']}
    events=[];ways={i:0 for i in critical};incoming={i:0 for i in critical}
    for i in critical:
        events.extend([(ops[i]['planned_start'],1),(ops[i]['planned_end'],-1)])
        for j in children[i]:
            if j in critical and ops[i]['planned_end']==ops[j]['planned_start']:incoming[j]+=1
    width=active=0
    for _,change in sorted(events):active+=change;width=max(width,active)
    for i in order:
        if i not in critical:continue
        if not incoming[i]:ways[i]=1
        for j in children[i]:
            if j in critical and ops[i]['planned_end']==ops[j]['planned_start']:ways[j]+=ways[i]
    paths=sum(ways[i] for i in critical if ops[i]['planned_end']==cmax)
    keys=('id','job','work','planned_start','planned_end','release','predecessors')
    quotient=digest(canonical(dict(operations=[{k:o[k] for k in keys} for o in ops],
        anonymous_queues=sorted(tuple(q) for q in plan['queues']),jobs=plan['jobs'],delta=plan['delta'])))
    return dict(machine_relabeling_class=quotient,critical_operations=len(critical),
        critical_width=width,critical_path_log2=math.log2(paths),
        assignment_sha256=digest(canonical([(o['machine'],o['work']) for o in ops])))


def structures():
    import gzip
    ROOT.mkdir(parents=True,exist_ok=True);summaries=[];allrows=[];receipts=[]
    def extent(rows,key):return [min(r[key] for r in rows),max(r[key] for r in rows)] if rows else None
    for instance in INSTANCES:
        tag=f'objectives-generate-{instance}-43810873992-1'
        source,receipt=fetch(tag,f'output/structure-source-{instance}');receipts.append(dict(tag=tag,**receipt))
        generation=read_json(source/'generation.json');problem=read_json(source/'problem.json')
        if generation['status']!='PASS':raise ValueError('unavailable generation')
        data=from_conditions(problem['conditions']);deadline=problem['deadline']
        for case in generation['results']:
            folder=source/case['case'];prefix=read_json(folder/'cp-seed/schedule.json')
            base=features(prefix,deadline);base_structure=structural(prefix);rows=[];seen=set()
            for selected in case['result']['selected']:
                if digest(canonical(read_json(folder/selected['file'])))!=selected['saved_plan_sha256']:
                    raise ValueError('selected input changed')
            with gzip.open(folder/'search-trace.jsonl.gz','rt',encoding='utf-8') as stream:
                import json
                for line in stream:
                    record=json.loads(line)
                    if record['status']!='OK' or record['plan_sha256'] in seen:continue
                    seen.add(record['plan_sha256']);plan=decode(data,record['genome'])
                    if plan_identity(plan)!=record['plan_sha256']:raise ValueError('trace decoding mismatch')
                    score=record['score'];value=features(plan,deadline)
                    if value['nominal_makespan']!=score['nominal_makespan']:raise ValueError('trace score mismatch')
                    # Exactly the preregistered 5% band around the paid CP prefix.
                    if 20*value['nominal_makespan']>21*base['nominal_makespan']:continue
                    rows.append(dict(instance=instance,case=case['case'],physical_sha256=physical(plan),**value,**structural(plan),
                        cal_f1_successes=score['F1']['successes'],cal_f2_successes=score['F2']['successes'],cal_samples=score['F1']['samples']))
            same=[r for r in rows if r['nominal_makespan']==base['nominal_makespan']]
            fixed=[r for r in same if r['assignment_sha256']==base_structure['assignment_sha256']]
            summaries.append(dict(instance=instance,case=case['case'],unique_evaluated=len(seen),near_nominal=len(rows),
                cp_nominal_makespan=base['nominal_makespan'],same_nominal=len(same),
                same_nominal_resource_classes=len({r['machine_relabeling_class'] for r in same}),
                fixed_assignment_same_nominal=len(fixed),fixed_assignment_resource_classes=len({r['machine_relabeling_class'] for r in fixed}),
                critical_width_range=extent(same,'critical_width'),maximum_load_range=extent(same,'maximum_machine_load'),
                repair_exposure_range=extent(same,'repair_exposure_proxy'),cal_f1_success_range=extent(same,'cal_f1_successes'),
                fixed_assignment_critical_width_range=extent(fixed,'critical_width'),
                fixed_assignment_cal_f1_success_range=extent(fixed,'cal_f1_successes'),
                historical_generation_process=case['process'],historical_prefix_preparation_s=case['result']['preparation_s']))
            allrows.extend(rows);write_json(ROOT/'progress.json',summaries)
    with (ROOT/'structures.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(allrows[0]));writer.writeheader();writer.writerows(allrows)
    result=dict(status='COMPLETE',scope='archival structural feasibility analysis; no new trajectories or holdout access',
        band='20*C_nom <= 21*paid_CP_prefix_C_nom; no free best from later risk search',
        summaries=summaries,receipts=receipts,
        source_warning='these genomes were produced by risk-directed search; they cannot be used as an independent pool to prove the value of risk information',
        symmetry_scope='operation-label-preserving global permutations of exchangeable machines only; not a proof of distributional difference for remaining classes',
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(ROOT/'STRUCTURES.json',result)
    lines=['# Разнообразие расписаний при одинаковой номинальной длительности','',
        'Архивный анализ исходных геномов: новые планы не оптимизируются и производственные траектории не исполняются. Проверочные исходы не читаются. Рабочие счётчики используются только как разведочные сведения.',
        'Опорная длительность принадлежит уже оплаченному CP-prefix каждого старого вызова. Простые перестановки одинаковых станков объединяются. Сохранение разных классов не доказывает различную истинную надёжность.',
        '', '| Задача | Вызов | Планы с тем же номиналом | После объединения перестановок станков | Из них с прежними назначениями | Ширина критических ветвей | Рабочие успехи F1 из64 |',
        '|---|---|---:|---:|---:|---|---|']
    for r in summaries:
        lines.append(f'| {r["instance"]} | {r["case"]} | {r["same_nominal"]} | {r["same_nominal_resource_classes"]} | '
            f'{r["fixed_assignment_same_nominal"]} | {r["critical_width_range"]} | {r["cal_f1_success_range"]} |')
    lines+=['', 'Планы здесь получены прошлым поиском с учётом рисков. Дорогой такой пул нельзя бесплатно дать одному методу или объявить независимым свидетельством полезности краш-тестов.',
        'Анализ проверяет наличие структурных альтернатив для будущего контролируемого опыта. Он не устанавливает внешний выигрыш и не измеряет цену нового независимого генератора пула.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def audit():
    ROOT.mkdir(parents=True,exist_ok=True);cases=[];rows=[]
    for instance in INSTANCES:
        for seed in SEEDS:
            tag=f'planner-pair-{instance}-{seed}-{SOURCE_RUN}'
            source,receipt=fetch(tag,f'output/decision-source-{instance}-{seed}')
            generation=read_json(source/'generation.json');problem=read_json(source/'problem.json')
            if generation['status']!='PASS':raise ValueError('unavailable frozen generation')
            data=from_conditions(problem['conditions']);rank=source/'cp_pool_mc'
            pool=read_json(rank/'cp/pool.json');result=read_json(rank/'result.json')
            actual_cp=read_json(rank/'cp/schedule.json');actual_mc=read_json(source/'cp_pool_mc.json')
            if digest(canonical(actual_mc))!=result['selected'][0]['saved_plan_sha256']:
                raise ValueError('selected schedule checksum mismatch')
            plans={};old_keys={}
            def add(plan):
                key=physical(plan);old=plan_identity(plan)
                if old in old_keys and old_keys[old]!=key:raise ValueError('ambiguous historical identity')
                old_keys[old]=key;plans[key]=plan
            add(data);add(actual_cp)
            for candidate in pool['candidates']:
                add(decode(data,candidate['genome']))
            add(decode(data,pool['final_genome']))
            for saved in rank.glob('candidate-*/schedule.json'):
                plan=read_json(saved);key=physical(plan)
                if key not in plans or digest(canonical(plan))!=digest(canonical(plans[key])):
                    raise ValueError('retained genome differs from actual saved schedule')
            calibration={}
            for candidate in result['candidates']:
                if candidate['status']!='OK':continue
                key=old_keys[candidate['plan_sha256']];score=candidate['score']
                if score['F1']['samples']!=64:raise ValueError('changed training sample count')
                calibration[key]=dict(successes=score['F1']['successes'],samples=64,p=score['p_f1'])
            mc_key=physical(actual_mc);cp_key=physical(actual_cp)
            if mc_key not in plans or mc_key not in calibration:raise ValueError('selected plan absent from retained pool')
            values={k:features(p,problem['deadline']) for k,p in plans.items()}
            best=min(v['nominal_makespan'] for v in values.values())
            minima=sorted(k for k,v in values.items() if v['nominal_makespan']==best)
            nominal=cp_key if cp_key in minima else minima[0]
            mc=calibration[mc_key];nom=calibration.get(nominal)
            record=dict(instance=instance,seed=seed,release=tag,archive_sha256=receipt['archive_sha256'],
                generation_commit=generation['commit'],retained_cp_incumbents=len(pool['candidates']),
                cp_solutions_seen=pool['solutions_seen'],cp_omitted=pool['omitted'],distinct_physical_plans=len(plans),
                minimum_nominal_makespan=best,minimum_nominal_ties=len(minima),
                nominal_key=nominal,mc_key=mc_key,cp_final_key=cp_key,identical=nominal==mc_key,
                nominal_calibration=nom,mc_calibration=mc,
                calibration_difference=None if nom is None else mc['p']-nom['p'],
                nominal_features=values[nominal],mc_features=values[mc_key],
                generation_process=next(r['process'] for r in generation['records'] if r['method']=='cp_pool_mc'),
                shared_cp_record=result['cp'],all_candidates_evaluated=result['stopping_reason']=='all_unique_candidates_evaluated')
            cases.append(record)
            for key,value in values.items():
                rows.append(dict(instance=instance,seed=seed,physical_sha256=key,**value,
                    calibration_successes=calibration[key]['successes'] if key in calibration else None,
                    calibration_samples=64 if key in calibration else None,nominal_selected=key==nominal,
                    mc_selected=key==mc_key,actual_cp_final=key==cp_key))
            write_json(ROOT/'progress.json',cases)
    with (ROOT/'candidates.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    report=dict(status='COMPLETE',scope='archival decision audit only; no new execution, optimization or holdout',
        source_run=SOURCE_RUN,cases=cases,identical_cases=sum(c['identical'] for c in cases),
        different_cases=sum(not c['identical'] for c in cases),
        nominal_rule='minimum decoded makespan over retained capped pool plus original/final; prefer actual CP final among ties, else physical SHA',
        calibration_role='exploratory training evidence; no external utility claim',
        static_features_role='descriptive load/slack/repair-exposure diagnostics, not validated decision algorithms',
        source_fingerprint={p:digest(Path(p).read_bytes()) for p in ('industrial/decision_options.py','planning/generator.py')},
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(ROOT/'AUDIT.json',report)
    lines=['# Выбор по краш-тестам и по длительности из одного пула','',
        'Архивный аудит: новые планы, сценарии поломок и проверочные исходы не создаются и не читаются.',
        'Номинальный выбор получает весь сохранённый пул CP, исходный и конечный планы. Усечённый пул не объявляется всеми когда-либо найденными решениями.',
        '', '| Задача | Seed | Разных планов | Равных лучших по длительности | Выборы совпали | Рабочая частота: nominal / MC |',
        '|---|---:|---:|---:|---|---:|']
    for c in cases:
        nom=c['nominal_calibration'];mc=c['mc_calibration'];p='нет оценки' if nom is None else f'{100*nom["p"]:.2f}%'
        lines.append(f'| {c["instance"]} | {c["seed"]} | {c["distinct_physical_plans"]} | {c["minimum_nominal_ties"]} | {c["identical"]} | {p} / {100*mc["p"]:.2f}% |')
    lines+=['',f'Физически одинаковый выбор: {report["identical_cases"]}/9. Разный выбор: {report["different_cases"]}/9.',
        '', 'Совпадение расписания означает одинаковый производственный исход при любой общей истории воздействий. Для такого случая новая проверка не установит пользу отбора по краш-тестам.',
        'Разный выбор и лучший рабочий балл ещё не устанавливают внешнего выигрыша. Нужны заранее зафиксированные правила, сильные дешёвые контроли, новый независимый результат и полная сопоставимая цена.',
        'Исторические затраты в AUDIT.json не являются новым парным измерением затрат двух правил. Суммарный runner-бюджет включает подготовку этого аудита.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    import argparse
    actions_only();parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('audit','structures'),default='audit',nargs='?')
    args=parser.parse_args()
    if args.stage=='structures':structures()
    else:audit()
