"""Close current selectable-objective acceptance; execution is Actions-only."""
import argparse
import csv
import os
from pathlib import Path
import shutil
import sys
from .common import actions_only,canonical,digest,read_json,write_json
from .end_to_end import run
from .inputs import scenarios
from .plan_campaign import paired_difference
from .production import simulate,check_physics,compare,product_ledger,outcomes,export_observations
from .releases import fetch
from planning.generator import from_conditions,validate_problem

ROOT=Path('output/objectives')
SOURCES=('industrial/plan.py','planning/generator.py','planning/cpsat.py',
         'industrial/plan_campaign.py','industrial/production.py','industrial/inputs.py')


def spec():return read_json('provenance/objectives_closure.json')
def fingerprint():return {p:digest(Path(p).read_bytes()) for p in SOURCES}
def identity(data):
    fields=('id','job','release','predecessors','machine','work','planned_start','planned_end','optional')
    return digest(canonical(dict(operations=[{k:o[k] for k in fields if k in o} for o in data['operations']],
        queues=data['queues'],jobs=data['jobs'],delta=data['delta'])))


def conditions(data):
    result={k:v for k,v in data.items() if k not in ('queues','nominal_makespan','planned_makespan')}
    result['machines']=len(data['queues'])
    result['operations']=[{k:v for k,v in o.items() if k not in ('machine','work','planned_start','planned_end')}
                          for o in data['operations']]
    return result


def save_plan(folder,data):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);write_json(folder/'schedule.json',data)
    with (folder/'schedule.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['id','job','machine','work','planned_start','planned_end'],extrasaction='ignore')
        writer.writeheader();writer.writerows(data['operations'])


def add(plans,data,alias):
    validate_problem(data);key=identity(data)
    plans.setdefault(key,dict(dataset=data,aliases=[],nominal_makespan=max(o['planned_end'] for o in data['operations'])))['aliases'].append(alias)


def collect(folder,record,original):
    plans={};add(plans,original,'original')
    add(plans,read_json(f'results/cpsat/schedules/{record["instance"]}.json'),'full_cp')
    for case in record['results']:
        label=case['case'];add(plans,read_json(folder/label/'cp-seed/schedule.json'),label+':prefix')
        for index,entry in enumerate(case['result']['selected']):
            data=read_json(folder/label/entry['file'])
            if digest(canonical(data))!=entry['saved_plan_sha256']:raise ValueError('selected plan hash mismatch')
            add(plans,data,f'{label}:{index}')
    return plans


def generate(instance):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True)
    if instance not in cfg['instances']:raise ValueError('unregistered instance')
    source,receipt=fetch(cfg['preflight'],'output/objectives-preflight')
    if read_json(source/'preflight.json')['status']!='PASS':raise ValueError('preflight unavailable')
    data=read_json(source/instance/'dataset.json');raw=conditions(data);rebuilt=from_conditions(raw)
    if identity(data)!=identity(rebuilt) or rebuilt['nominal_makespan']!=data['nominal_makespan']:
        raise ValueError('raw conditions did not reproduce the frozen inexpensive reference')
    problem=dict(conditions=raw,spec=cfg,deadline=data['nominal_makespan']*11//10)
    write_json(ROOT/'problem.json',problem);write_json(ROOT/'original.json',data);results=[]
    for seed in cfg['seeds']:
        for objective in cfg['objectives']:
            label=f'{seed}-{objective}';folder=ROOT/label
            process=run([sys.executable,'-m','industrial.plan',str(ROOT/'problem.json'),'--folder',str(folder),
                         '--objective',objective,'--seed',str(seed)],timeout=300)
            result=read_json(folder/'result.json') if (folder/'result.json').exists() else dict(status='UNAVAILABLE')
            if process['status']!='OK':result=dict(result,status='UNAVAILABLE')
            results.append(dict(case=label,seed=seed,objective=objective,process=process,result=result))
            write_json(ROOT/'progress.json',dict(instance=instance,results=results))
    record=dict(status='PASS' if len(results)==6 and all(c['result']['status']=='PASS' for c in results) else 'PARTIAL',
        instance=instance,results=results,implementation=fingerprint(),spec=cfg,
        problem_sha256=digest(canonical(problem)),preflight_receipt=receipt,
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(ROOT/'generation.json',record)
    if record['status']!='PASS':raise ValueError('generation incomplete; holdout remains closed')


def sealed(registry):
    cfg=spec();entries={};seal=[]
    for index,tag in enumerate(registry['generations']):
        folder,receipt=fetch(tag,f'output/objectives-generation-{index}');record=read_json(folder/'generation.json')
        if record['status']!='PASS' or record['spec']!=cfg or record['implementation']!=fingerprint():
            raise ValueError('incomplete or changed generation')
        if record['instance'] in entries:raise ValueError('duplicate instance')
        problem=read_json(folder/'problem.json')
        if 'dataset' in problem or digest(canonical(problem))!=record['problem_sha256']:
            raise ValueError('raw input checksum mismatch')
        expected={(s,o) for s in cfg['seeds'] for o in cfg['objectives']}
        if {(c['seed'],c['objective']) for c in record['results']}!=expected or len(record['results'])!=6:
            raise ValueError('not the full registered matrix')
        plans=collect(folder,record,read_json(folder/'original.json'))
        entries[record['instance']]=(folder,record,plans)
        seal.append(dict(instance=record['instance'],tag=tag,archive_sha256=receipt['archive_sha256'],
                         plans=sorted(plans),cases=[c['case'] for c in record['results']]))
    if set(entries)!=set(cfg['instances']):raise ValueError('all 18 generations must be frozen before holdout')
    return entries,seal


def validate(instance,registry):
    from .binding import fit
    from .statistics import lower,upper
    from .targets import query_full_r
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);entries,seal=sealed(registry)
    total_plans=sum(len(p) for _,_,p in entries.values())
    total_selected=sum(len(c['result']['selected']) for _,r,_ in entries.values() for c in r['results'])
    rate_alpha=cfg['family_alpha']/(4*total_plans)
    pair_alpha=cfg['family_alpha']/(8*total_selected)
    write_json(ROOT/'seal.json',dict(generations=seal,distinct_plans=total_plans,selected=total_selected,
                                    rate_endpoint_alpha=rate_alpha,pair_endpoint_alpha=pair_alpha))
    source,generation,plans=entries[instance];data=read_json(source/'original.json');deadline=data['nominal_makespan']*11//10
    jobs=[j['id'] for j in data['jobs'] if not j.get('optional',False)]
    banks={law:scenarios(data,law,cfg['validation_split'],cfg['validation_replications_per_law']) for law in cfg['laws']}
    write_json(ROOT/'holdout-calendars.json.gz',banks);results=[]
    for key,entry in plans.items():
        plan=entry['dataset'];planroot=ROOT/'plans'/key;save_plan(planroot,plan);regimes={}
        for law,bank in banks.items():
            folder=planroot/law;outputs={};processes=[];mismatches=[]
            subset=sorted(bank,key=lambda s:digest(('current-objectives-S1|'+s['id']).encode()))[:cfg['tsfg_validation_subset_per_law']]
            for engine in ('des','dag','tsfg'):
                current=subset if engine=='tsfg' else bank
                output,ps=simulate(plan,current,folder/engine,engine,deadline,chunk=16 if engine=='tsfg' else 128)
                outputs[engine]=output;processes.extend(ps)
                for scenario in current:
                    if scenario['id'] in output:
                        try:check_physics(plan,scenario,output[scenario['id']])
                        except Exception as error:mismatches.append(dict(engine=engine,attempt=scenario['id'],error=str(error)))
            for engine in ('dag','tsfg'):
                for aid in outputs[engine].keys() & outputs['des'].keys():
                    try:compare(outputs['des'][aid],outputs[engine][aid])
                    except Exception as error:mismatches.append(dict(engine=engine,attempt=aid,error=str(error)))
            ledger=product_ledger(plan,bank,outputs['des']);write_json(folder/'product-ledger.json.gz',ledger)
            labels=outcomes(ledger,jobs,deadline)
            complete=(len(outputs['des'])==len(outputs['dag'])==len(bank) and len(outputs['tsfg'])==len(subset)
                and not mismatches and all(p['status']=='OK' for p in processes) and all(v is not None for v in labels.values()))
            full_r=None
            if complete:
                model,_,_=fit(export_observations(plan,bank,outputs['des'],deadline),deadline)
                full_r=query_full_r(model);write_json(folder/'model.json.gz',model)
                if full_r['lower']!=full_r['upper'] or full_r['guaranteed']!=sum(labels.values()):
                    mismatches.append(dict(error='R differs from independent whole-batch result'));complete=False
            k=sum(v is True for v in labels.values());n=len(bank)
            regimes[law]=dict(status='COMPLETE' if complete else 'PARTIAL',samples=n,successes=k,
                probability=k/n if complete else None,simultaneous95=[lower(k,n,rate_alpha),upper(k,n,rate_alpha)] if complete else None,
                outcomes=labels,full_R=full_r,processes=processes,mismatches=mismatches,
                des_completed=len(outputs['des']),dag_completed=len(outputs['dag']),tsfg_completed=len(outputs['tsfg']))
            write_json(folder/'result.json',regimes[law])
        results.append(dict(plan_sha256=key,aliases=entry['aliases'],nominal_makespan=entry['nominal_makespan'],regimes=regimes))
        write_json(ROOT/'progress.json',dict(instance=instance,plans=results))
    by_alias={alias:r for r in results for alias in r['aliases']};comparisons=[]
    for case in generation['results']:
        baseline=by_alias[case['case']+':prefix']
        for i,_ in enumerate(case['result']['selected']):
            alias=case['case']+f':{i}';candidate=by_alias[alias]
            laws={law:paired_difference(candidate['regimes'][law]['outcomes'],baseline['regimes'][law]['outcomes'],pair_alpha) for law in cfg['laws']}
            same=candidate['plan_sha256']==baseline['plan_sha256']
            if all(r['regimes'][law]['status']=='COMPLETE' for r in (candidate,baseline) for law in cfg['laws']):
                c=[min(candidate['regimes'][law]['simultaneous95'][i] for law in cfg['laws']) for i in (0,1)]
                b=[min(baseline['regimes'][law]['simultaneous95'][i] for law in cfg['laws']) for i in (0,1)]
                worst_interval=[0.,0.] if same else [c[0]-b[1],c[1]-b[0]]
                worst_difference=min(candidate['regimes'][l]['probability'] for l in cfg['laws'])-min(baseline['regimes'][l]['probability'] for l in cfg['laws'])
            else:worst_interval=None;worst_difference=None
            comparisons.append(dict(alias=alias,objective=case['objective'],identical_to_prefix=same,laws=laws,
                worst_difference=worst_difference,worst_simultaneous95=worst_interval,
                nominal_difference=candidate['nominal_makespan']-baseline['nominal_makespan']))
    complete=all(v['status']=='COMPLETE' for r in results for v in r['regimes'].values())
    write_json(ROOT/'validation.json',dict(status='PASS' if complete else 'PARTIAL',instance=instance,plans=results,
        comparisons=comparisons,deadline=deadline,reference_C0=data['nominal_makespan'],generation=generation,
        seal=read_json(ROOT/'seal.json'),commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))
    if not complete:raise ValueError('external acceptance incomplete; retain all failures')


def report(registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);records=[];receipts=[];missing=[]
    for index,tag in enumerate(registry['validations']):
        try:
            folder,receipt=fetch(tag,f'output/objectives-validation-{index}');record=read_json(folder/'validation.json')
            records.append(record);receipts.append(dict(tag=tag,**receipt))
            for plan in record['plans']:
                shutil.copytree(folder/'plans'/plan['plan_sha256'],ROOT/'plans'/'current'/record['instance']/plan['plan_sha256'],
                    ignore=shutil.ignore_patterns('F1','F2'),dirs_exist_ok=True)
        except Exception as error:missing.append(dict(tag=tag,error=str(error)))
    complete=(len(records)==3 and {r['instance'] for r in records}==set(cfg['instances']) and not missing
              and all(r['status']=='PASS' for r in records))
    rows=[];costs=[];catalog=[]
    for record in records:
        instance=record['instance']
        for plan in record['plans']:
            probs={l:plan['regimes'][l]['probability'] for l in cfg['laws']}
            for alias in plan['aliases']:
                catalog.append(dict(version='current',instance=instance,alias=alias,plan_sha256=plan['plan_sha256'],
                    file=f'plans/current/{instance}/{plan["plan_sha256"]}/schedule.json'))
                for law,value in plan['regimes'].items():
                    rows.append(dict(instance=instance,alias=alias,plan_sha256=plan['plan_sha256'],law=law,
                        nominal_makespan=plan['nominal_makespan']/100,deadline=record['deadline']/100,
                        samples=value['samples'],successes=value['successes'],probability=value['probability'],
                        lower=value['simultaneous95'][0] if value['simultaneous95'] else None,
                        upper=value['simultaneous95'][1] if value['simultaneous95'] else None,status=value['status']))
        for case in record['generation']['results']:
            result=case['result'];costs.append(dict(instance=instance,case=case['case'],status=result['status'],
                generation_process_s=case['process']['wall_s'],observed_prefix_window_s=result.get('preparation_s'),
                cp_model_and_solver_s=result.get('cp_seed',{}).get('model_build_and_search_s'),
                evaluated=result.get('stats',{}).get('evaluated'),failures=result.get('stats',{}).get('failures'),
                censored=result.get('stats',{}).get('budget_censored_evaluations'),stopping=result.get('stopping_reason')))
    legacy=[]
    for index,tag in enumerate(cfg['legacy_generation_tags']):
        folder,receipt=fetch(tag,f'output/legacy-generation-{index}');generation=read_json(folder/'generation.json')
        for case in generation['results']:
            for i,selected in enumerate(case['result']['selected']):
                data=read_json(folder/case['case']/selected['file'])
                if digest(canonical(data))!=selected['saved_plan_sha256']:raise ValueError('legacy selected checksum mismatch')
                dest=ROOT/'plans'/'historical-v1'/generation['instance']/case['case']/str(i);save_plan(dest,data)
                catalog.append(dict(version='historical-v1',instance=generation['instance'],alias=f'{case["case"]}:{i}',
                    plan_sha256=identity(data),file=str((dest/'schedule.json').relative_to(ROOT))))
        legacy.append(dict(tag=tag,source_commit=generation['commit'],archive_sha256=receipt['archive_sha256']))
    def csv_file(name,values):
        if not values:return
        with (ROOT/name).open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
    csv_file('plans.csv',rows);csv_file('costs.csv',costs);csv_file('catalog.csv',catalog)
    curves=[]
    with Path('results/industrial/forecasts.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            if row['regime']=='same_regime' and row['mode']=='available' and row['target']=='execution':
                curves.append(dict(instance=row['condition'].split('-')[0],law=row['condition'].split('-')[1],
                    deadline_percent_C0=int(row['deadline_label']),holdout_success=float(row['validation_frequency']),
                    simulated_prediction=float(row['validation_frequency'])+float(row['signed_error']),
                    sample_scope='original E5; 512 calibration and 1024 independent test, shared deadlines'))
    csv_file('deadline-risk.csv',curves)
    allcomparisons=[dict(instance=r['instance'],**c) for r in records for c in r['comparisons']]
    same=sum(c['identical_to_prefix'] for c in allcomparisons)
    confirmed_worst=[c for c in allcomparisons if c['objective']=='worst_regime' and c['worst_simultaneous95'] and c['worst_simultaneous95'][0]>0]
    result=dict(status='COMPLETE' if complete else 'PARTIAL',registered_generations=18,
        completed_generations=len(costs),selected_comparisons=len(allcomparisons),identical_to_prefix=same,
        confirmed_worst_improvements=len(confirmed_worst),missing=missing,comparisons=allcomparisons,
        historical_exports=sum(c['version']=='historical-v1' for c in catalog),current_catalog_entries=sum(c['version']=='current' for c in catalog),
        receipts=receipts,legacy=legacy,validation=records,profile=cfg)
    write_json(ROOT/'RESULT.json',result)
    lines=['# Производственные краш-тесты и генерация планов','',
        f'Текущая дополнительная проверка: **{result["status"]}**. Выполнено {len(costs)}/18 генераций.',
        '', 'Виртуальный краш-тест задаёт технологические операции, станки, длительности, зависимости и срок. Затем генерирует поломки, исполняет план и считает долю сценариев, в которых вся обязательная партия готова к сроку. Это расчёт риска при принятых условиях, а не обещание исхода отдельного будущего заказа и не оценка по реальной истории предприятия.',
        '', 'F1: независимые поломки станков. F2: смесь независимых и общих поломок с теми же маргинальными законами. В начале все станки исправны, среднее время работы 2 C0, ремонта 0,1 C0, экспоненциальные длительности округляются вверх к шагу 0,05. Замена F1 на F2 меняет совместные отказы и требует расчёта именно для F2.',
        '', '## Что показали исходные краш-тесты', '',
        'Сроки служат критериями, не отменяют работу. По каждой траектории оцениваются C0, 1,1 C0 и 1,25 C0. Неустановленный окончательный исход к остановке остаётся неизвестным; незавершение к сроку означает нарушение срока. Вычислительный тайм-аут учитывается отдельно.',
        '', '| Задача | Режим | Успех к C0, % | К 1,1 C0, % | К 1,25 C0, % |', '|---|---|---:|---:|---:|']
    for instance in cfg['instances']:
        for law in cfg['laws']:
            by={r['deadline_percent_C0']:r for r in curves if r['instance']==instance and r['law']==law}
            lines.append(f'| {instance} | {law} | '+ ' | '.join(f'{100*by[d]["holdout_success"]:.2f}' for d in (100,110,125))+' |')
    lines+=['', 'Это результаты исходного списка операций: даже допустимый без поломок план может часто срывать срок. Таблица показывает, какой запас по сроку меняет риск при каждом режиме отказов. Полные данные и оценка по отдельному моделируемому банку — в `deadline-risk.csv`.',
        '', 'E1–E5 выполнены: 30 720 стохастических траекторий DES/DAG и заранее выделенные 2560 проверок S1, без расхождений исполнения. Проверки вычислителя включают полные свидетели, 65 координат с восемью неизвестными и промышленную схему до 1454 координат. При полном наблюдении SIMPAT R совпадает со счётчиком успешных виртуальных прогонов, что проверяет корректность агрегации; дополнительная предсказательная сила из этого не следует.',
        '', 'В E5 средняя абсолютная разница прогноза и независимой тестовой частоты при том же законе — 2,43 п.п. для F1 и 1,75 п.п. для F2. Перенос оценки F1 на F2 даёт 20,71 п.п.: предположение о характере поломок существенно. Это не ошибка прямого моделирования F2. При искусственно неполной регистрации метод возвращает границы вместо необоснованной точечной уверенности; они могут быть широкими.',
        '', 'E6: исходная серия при 300 с остаётся PARTIAL (39/41 условий, 24 тайм-аута). Отдельные повторы с пределом 1200 с завершили оставшиеся два условия. Сокращение файла представления не означает такое же ускорение подготовки или полного расчёта; положительное ускорение не было требованием E6.',
        '', '## Генерация из условий с выбираемой целью', '',
        'Доступны минимальная номинальная длительность (`nominal`), вероятность срока в F1 (`deadline_f1`), худшая из вероятностей F1/F2 (`worst_regime`) и набор компромиссов длительности/F1/F2 (`pareto`). Поиск назначает станки и порядок операций; готовое расписание во входе этой серии отсутствует. Глобальный оптимум стохастических целей не доказан.',
        '', 'Текущие nominal и deadline_f1 проверены ранее отдельно. Здесь проверены оставшиеся worst_regime и pareto. Все варианты ниже зафиксированы до открытия нового общего банка; 6144 уникальных историй повторяются для разных планов и не умножают размер выборки. DES/DAG выполняют весь банк, исходный S1 — 128 заранее выбранных историй каждого закона/задачи. Внешняя проверка включает физический баланс и независимый результат всей партии.',
        '', '| Задача | Вариант | Длительность без отказов | Успех F1, % | Успех F2, % |', '|---|---|---:|---:|---:|']
    for record in records:
        for plan in record['plans']:
            aliases=', '.join(plan['aliases']);p=plan['regimes']
            values=[f'{100*p[l]["probability"]:.2f}' if p[l]['probability'] is not None else 'UNAVAILABLE' for l in cfg['laws']]
            lines.append(f'| {record["instance"]} | {aliases} | {plan["nominal_makespan"]/100:g} | {values[0]} | {values[1]} |')
    lines+=['', f'Из {len(allcomparisons)} возвращённых представителей {same} физически совпали с собственным CP-prefix. Подтверждённых улучшений худшего режима по совместным границам: {len(confirmed_worst)}. Числа, парные выигрыши/потери и границы приведены в RESULT.json; один только лучший калибровочный балл преимуществом не считается.',
        '', 'CP-prefix — фактически затраченная общая начальная часть вызова. Полный CP-план — ранее зафиксированный сильный ориентир; его исторические затраты 0,350/235,078/235,089 с для Mk01/05/10 не являются новым парным измерением. Изменение качества относительно исходного плана не приписывается новой математике: генератор использует стандартные CP-SAT и поиск с прямой оценкой сценариев.',
        '', 'Для worst_regime сравниваются оба закона. Для Pareto публикуются все калибровочно выбранные представители, без отбора по тесту. Это найденные компромиссы, не доказанный глобальный фронт. Отсутствие внешнего выигрыша относительно дешёвого prefix оставляет пользу дополнительного поиска неподтверждённой.',
        '', 'Ранее проверенный deadline_f1 совпал с коротким CP-prefix в 7 из 9 случаев; для двух остальных подтверждённого выигрыша не получено. Полный CP был лучше по F1 на Mk10. Поэтому оснований заявлять преимущество добавочного поиска над сильными простыми средствами пока нет.',
        '', '## Воспроизводимые результаты и планы', '',
        '`catalog.csv` связывает каждый возвращённый вариант с настоящими schedule.json и schedule.csv. `plans/historical-v1/` содержит все старые цели с исторической версией; `plans/current/` — текущие результаты и контроли. Одинаковые физические планы могут соответствовать нескольким целям. `plans.csv` содержит внешние вероятности и совместные границы; `costs.csv` — полное время вызова, наблюдённое окно CP-prefix, завершённые/ошибочные/оборванные оценки. Подготовка окружения и весь runner-бюджет сохранены в provenance/budget.json и workflow logs.',
        '', f'Экспортировано исторических представителей: {result["historical_exports"]}. Техническая завершённость, физическая допустимость, внешнее качество и вычислительная цена сообщаются раздельно. Результаты относятся к перечисленным синтетическим законам и задачам; перенос на конкретное производство требует его операций и обоснованных условий поломок.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    actions_only();parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('generate','validate','report'))
    parser.add_argument('--instance');parser.add_argument('--registry',default='{}');args=parser.parse_args()
    import json
    registry=json.loads(args.registry)
    if args.stage=='generate':generate(args.instance)
    elif args.stage=='validate':validate(args.instance,registry)
    else:report(registry)
