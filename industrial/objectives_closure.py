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
    expected=canonical(conditions(original))
    for entry in plans.values():
        data=entry['dataset']
        if canonical(conditions(data))!=expected or data['nominal_makespan']!=original['nominal_makespan']:
            raise ValueError('plan changed the conditions or reference C0')
        ops=data['operations'];flat=[i for queue in data['queues'] for i in queue]
        if sorted(flat)!=list(range(len(ops))):raise ValueError('machine queues do not cover exactly the operations')
        for machine,queue in enumerate(data['queues']):
            end=0
            for i in queue:
                op=ops[i]
                if (op['machine']!=machine or not any(a['machine']==machine and a['work']==op['work'] for a in op['alternatives'])
                    or op['planned_end']-op['planned_start']!=op['work']
                    or any(type(op[k]) is not int or op[k]%data['delta'] for k in ('planned_start','planned_end'))
                    or op['planned_start']<max([end,op['release'],*[ops[p]['planned_end'] for p in op['predecessors']]])):
                    raise ValueError('infeasible nominal operation or machine order')
                end=op['planned_end']
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
            elif process['wall_s']>cfg['search']['total_budget_s']:result=dict(result,status='BUDGET_EXCEEDED')
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
        if any(c['process']['status']!='OK' or c['process']['wall_s']>cfg['search']['total_budget_s']
               or c['result']['status']!='PASS' for c in record['results']):
            raise ValueError('full fresh-process budget exceeded or generation unavailable')
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
    shutil.copyfile(source/'problem.json',ROOT/'problem.json')
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


def external_relation(candidate,reference,laws,paired=None):
    """Describe frozen points; infer only from registered simultaneous bounds."""
    if candidate['plan_sha256']==reference['plan_sha256']:
        return dict(status='IDENTICAL',empirical_relation='identical',worst_difference=0.,worst_interval=[0.,0.])
    if any(r['regimes'][l]['status']!='COMPLETE' for r in (candidate,reference) for l in laws):
        return dict(status='UNAVAILABLE')
    nominal=candidate['nominal_makespan']-reference['nominal_makespan']
    differences=[reference['nominal_makespan']-candidate['nominal_makespan']]
    intervals=[]
    for law in laws:
        c,b=candidate['regimes'][law],reference['regimes'][law]
        differences.append(c['probability']-b['probability'])
        intervals.append(paired[law]['outer95'] if paired else
                         [c['simultaneous95'][0]-b['simultaneous95'][1],c['simultaneous95'][1]-b['simultaneous95'][0]])
    empirical=('candidate_dominates' if all(d>=0 for d in differences) and any(d>0 for d in differences)
        else 'reference_dominates' if all(d<=0 for d in differences) and any(d<0 for d in differences)
        else 'same_estimated_point' if all(d==0 for d in differences) else 'tradeoff')
    favor_candidate=nominal<0 or any(lo>0 for lo,hi in intervals)
    favor_reference=nominal>0 or any(hi<0 for lo,hi in intervals)
    if nominal<=0 and all(lo>=0 for lo,hi in intervals) and favor_candidate:status='CONFIRMED_DOMINATES'
    elif nominal>=0 and all(hi<=0 for lo,hi in intervals) and favor_reference:status='CONFIRMED_DOMINATED'
    elif favor_candidate and favor_reference:status='CONFIRMED_TRADEOFF'
    else:status='INCONCLUSIVE'
    c=[min(candidate['regimes'][l]['simultaneous95'][i] for l in laws) for i in (0,1)]
    b=[min(reference['regimes'][l]['simultaneous95'][i] for l in laws) for i in (0,1)]
    return dict(status=status,empirical_relation=empirical,nominal_difference=nominal,
        probability_differences=intervals,pareto_confidence_family='registered paired comparisons' if paired else 'registered rates',
        worst_confidence_family='registered rates; separate family from paired comparisons',
        worst_difference=min(candidate['regimes'][l]['probability'] for l in laws)-min(reference['regimes'][l]['probability'] for l in laws),
        worst_interval=[c[0]-b[1],c[1]-b[0]])


def report(registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);records=[];receipts=[];missing=[]
    for index,tag in enumerate(registry['validations']):
        try:
            folder,receipt=fetch(tag,f'output/objectives-validation-{index}');record=read_json(folder/'validation.json')
            records.append(record);receipts.append(dict(tag=tag,**receipt))
            (ROOT/'inputs'/record['instance']).mkdir(parents=True,exist_ok=True)
            shutil.copyfile(folder/'problem.json',ROOT/'inputs'/record['instance']/'problem.json')
            for plan in record['plans']:
                shutil.copytree(folder/'plans'/plan['plan_sha256'],ROOT/'plans'/'current'/record['instance']/plan['plan_sha256'],
                    ignore=shutil.ignore_patterns('F1','F2'),dirs_exist_ok=True)
        except Exception as error:missing.append(dict(tag=tag,error=str(error)))
    complete=(len(records)==3 and {r['instance'] for r in records}==set(cfg['instances']) and not missing
              and all(r['status']=='PASS' for r in records))
    if records and any(r['seal']!=records[0]['seal'] for r in records):raise ValueError('different sealed plan families')
    expected_tags=set(registry['generations'])
    if len(expected_tags)!=3:raise ValueError('all three generation releases required in report registry')
    for record in records:
        if {g['tag'] for g in record['seal']['generations']}!=expected_tags:
            raise ValueError('validation belongs to a different generation registry')
        generation=record['generation']
        if generation['spec']!=cfg or generation['implementation']!=fingerprint():
            raise ValueError('validation belongs to different protocol or participant versions')
        if len(generation['results'])!=6 or any(c['result']['status']!='PASS' or c['process']['status']!='OK'
            or c['process']['wall_s']>cfg['search']['total_budget_s'] for c in generation['results']):
            raise ValueError('not a complete within-budget generation matrix')
    rows=[];costs=[];catalog=[]
    for record in records:
        instance=record['instance']
        for plan in record['plans']:
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
    csv_file('plans.csv',rows);csv_file('costs.csv',costs)
    prior_seal=read_json('results/cp-prefix/seal.json');prior_count=0
    for entry in prior_seal['entries']:
        for method,objective in (('cp_nominal','nominal'),('hybrid','deadline_f1')):
            data=read_json(f'results/cp-prefix/schedules/{entry["instance"]}/{entry["seed"]}/{method}.json')
            physical=digest(canonical([(o['id'],o['machine'],o['work'],o['planned_start'],o['planned_end']) for o in data['operations']]))
            if physical!=entry['methods'][method]['physical_sha256']:raise ValueError('previous current-interface plan changed')
            dest=ROOT/'plans'/'current-prior'/entry['instance']/f'{entry["seed"]}-{objective}';save_plan(dest,data)
            catalog.append(dict(version='current-prior',instance=entry['instance'],alias=f'{entry["seed"]}-{objective}:0',
                plan_sha256=identity(data),file=str((dest/'schedule.json').relative_to(ROOT))));prior_count+=1
    csv_file('catalog.csv',catalog)
    shutil.copyfile('results/cp-prefix/plans.csv',ROOT/'prior-validation.csv')
    write_json(ROOT/'prior-seal.json',prior_seal)
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
    quality=[]
    for record in records:
        by_alias={a:p for p in record['plans'] for a in p['aliases']}
        for comparison in record['comparisons']:
            alias=comparison['alias'];candidate=by_alias[alias];case=alias.rsplit(':',1)[0]
            quality.append(dict(instance=record['instance'],alias=alias,objective=comparison['objective'],
                prefix=external_relation(candidate,by_alias[case+':prefix'],cfg['laws'],comparison['laws']),
                full_cp=external_relation(candidate,by_alias['full_cp'],cfg['laws'])))
    write_json(ROOT/'external-quality.json',quality)
    same=sum(c['identical_to_prefix'] for c in allcomparisons)
    confirmed_worst=[c for c in allcomparisons if c['objective']=='worst_regime' and c['worst_simultaneous95'] and c['worst_simultaneous95'][0]>0]
    pareto_confirmed=[q for q in quality if q['objective']=='pareto' and q['prefix']['status'] in ('CONFIRMED_DOMINATES','CONFIRMED_TRADEOFF')]
    from collections import Counter
    process_status=Counter(p['status'] for r in records for plan in r['plans'] for law in cfg['laws']
                           for p in plan['regimes'][law]['processes'])
    measured={engine:sum(plan['regimes'][law][engine+'_completed'] for r in records for plan in r['plans'] for law in cfg['laws'])
              for engine in ('des','dag','tsfg')}
    result=dict(status='COMPLETE' if complete else 'PARTIAL',registered_generations=18,
        completed_generations=len(costs),selected_comparisons=len(allcomparisons),identical_to_prefix=same,
        confirmed_worst_improvements=len(confirmed_worst),missing=missing,comparisons=allcomparisons,
        confirmed_pareto_improvements_or_tradeoffs=len(pareto_confirmed),
        historical_exports=sum(c['version']=='historical-v1' for c in catalog),current_catalog_entries=sum(c['version']=='current' for c in catalog),
        prior_current_exports=prior_count,distinct_plans=sum(len(r['plans']) for r in records),
        measured_trajectories=measured,compute_status=dict(process_status),
        execution_mismatches=sum(len(plan['regimes'][law]['mismatches']) for r in records for plan in r['plans'] for law in cfg['laws']),
        receipts=receipts,legacy=legacy,validation=records,external_quality=quality,profile=cfg)
    write_json(ROOT/'RESULT.json',result)
    lines=['# Производственные краш-тесты и генерация планов','']
    if complete:
        largest=next(r for r in records if r['instance']=='Mk10')
        by_alias={a:p for p in largest['plans'] for a in p['aliases']}
        original,cp=by_alias['original']['regimes']['F1'],by_alias['full_cp']['regimes']['F1']
        lines+=[f'Краш-тесты показали существенное различие риска у планов для одних станков и срока. На Mk10 при независимых поломках исходный план выполнил всю партию в {original["successes"]} из {original["samples"]} испытаний ({100*original["probability"]:.2f}%), ранее зафиксированный план стандартного CP-SAT — в {cp["successes"]} ({100*cp["probability"]:.2f}%). Срок {largest["deadline"]/100:g} и состав партии сохранены. Это оценка производственного риска при заданном законе, а не процент точных предсказаний для реального завода.',
            '', f'Дополнительный поиск с учётом поломок завершён, но его преимущество над собственным коротким CP-SAT не установлено: подтверждённых улучшений худшего режима {len(confirmed_worst)}, подтверждённых Pareto-улучшений или компромиссов {len(pareto_confirmed)}. Сам факт получения разных расписаний не означает, что они лучше дешёвого контроля. Генератор, краш-тест и структурный анализ имеют отдельные результаты.', '']
    lines+=[
        f'Текущая дополнительная проверка: **{result["status"]}**. Выполнено {len(costs)}/18 генераций.',
        '', f'Внешняя проверка охватила {result["distinct_plans"]} различных расписаний с контролями. Завершённые траектории: DES {measured["des"]}, DAG {measured["dag"]}, S1 {measured["tsfg"]}. Расхождения: {result["execution_mismatches"]}. Статусы вычислительных процессов: {dict(process_status)}.',
        '', 'Виртуальный краш-тест задаёт технологические операции, станки, длительности, зависимости и срок. Затем генерирует поломки, исполняет план и считает долю сценариев, в которых вся обязательная партия готова к сроку. Это расчёт риска при принятых условиях, а не обещание исхода отдельного будущего заказа и не оценка по реальной истории предприятия.',
        '', 'F1: независимые поломки станков. F2: смесь независимых и общих поломок с теми же маргинальными законами. В начале все станки исправны, среднее время работы до округления 2 C0, ремонта 0,1 C0; экспоненциальные длительности округляются вверх к шагу 0,05. Замена F1 на F2 меняет совместные отказы и требует расчёта именно для F2.',
        '', '## Что показали исходные краш-тесты', '',
        'Сроки служат критериями, не отменяют работу. По каждой траектории оцениваются C0, 1,1 C0 и 1,25 C0. Неустановленный окончательный исход к остановке остаётся неизвестным; незавершение к сроку означает нарушение срока. Вычислительный тайм-аут учитывается отдельно.',
        '', '| Задача | Режим | Успех к C0, % | К 1,1 C0, % | К 1,25 C0, % |', '|---|---|---:|---:|---:|']
    for instance in sorted({r['instance'] for r in curves}):
        for law in cfg['laws']:
            by={r['deadline_percent_C0']:r for r in curves if r['instance']==instance and r['law']==law}
            lines.append(f'| {instance} | {law} | '+ ' | '.join(f'{100*by[d]["holdout_success"]:.2f}' for d in (100,110,125))+' |')
    lines+=['', 'Это результаты исходного списка операций: даже допустимый без поломок план может часто срывать срок. Таблица показывает, какой запас по сроку меняет риск при каждом режиме отказов. Полные данные и оценка по отдельному моделируемому банку — в `deadline-risk.csv`.',
        '', 'В этой серии F2 часто даёт большую вероятность готовности всей партии, чем F1. Одинаковая статистика отдельного станка не задаёт риск всего плана: совпадающие во времени остановки и разнесённые остановки по-разному проходят через технологические зависимости. Это результат именно этих двух законов, а не универсальное утверждение о пользе общих отказов.',
        '', 'E1–E5 выполнены: 30 720 стохастических траекторий DES/DAG и заранее выделенные 2560 проверок S1, без расхождений исполнения. Проверки вычислителя включают полные свидетели, 65 координат с восемью неизвестными и промышленную схему до 1454 координат. При полном наблюдении SIMPAT R совпадает со счётчиком успешных виртуальных прогонов, что проверяет корректность агрегации; дополнительная предсказательная сила из этого не следует.',
        '', 'В E5 средняя абсолютная разница прогноза и независимой тестовой частоты при том же законе — 2,43 п.п. для F1 и 1,75 п.п. для F2. Перенос оценки F1 на F2 даёт 20,71 п.п.: предположение о характере поломок существенно. Это не ошибка прямого моделирования F2. При искусственно неполной регистрации метод возвращает границы вместо необоснованной точечной уверенности; они могут быть широкими.',
        '', 'E6: исходная серия при 300 с остаётся PARTIAL (39/41 условий, 24 тайм-аута). Отдельные повторы с пределом 1200 с завершили оставшиеся два условия. Сокращение файла представления не означает такое же ускорение подготовки или полного расчёта; положительное ускорение не было требованием E6.',
        '', 'Аудит разделил два разных пути сокращения. Проекция после построения полной модели оставила почти всё время подготовки. Прямое сокращённое построение в отдельной паре на одном runner заняло 107,74 с против 240,78 с для полного, при том же точном интервале R: примерно в 2,23 раза быстрее. Это ускорение обработки готовых журналов, не всего виртуального исполнения. Исправления граничных наблюдений и терминального контракта прошли 40 квалификационных тестов; архивные результаты сохранены.',
        '', '## Генерация из условий с выбираемой целью', '',
        'Доступны минимальная номинальная длительность (`nominal`), вероятность срока в F1 (`deadline_f1`), худшая из вероятностей F1/F2 (`worst_regime`) и набор компромиссов длительности/F1/F2 (`pareto`). Поиск назначает станки и порядок операций; готовое расписание во входе этой серии отсутствует. Глобальный оптимум стохастических целей не доказан.',
        '', 'Внутри поиска каждый кандидат проходит 64 виртуальных сценария каждого нужного закона. По этому рабочему банку генератор выбирает возвращаемые планы. Затем планы фиксируются и испытываются на 1024 новых сценариях каждого закона, которые в подборе не участвовали. Калибровка здесь означает первый набор виртуальных прогонов при заданных условиях, а не историю реального завода.',
        '', 'Текущие nominal и deadline_f1 проверены ранее отдельно. Здесь проверены оставшиеся worst_regime и pareto. Все варианты ниже зафиксированы до открытия нового общего банка; 6144 уникальных историй повторяются для разных планов и не умножают размер выборки. DES/DAG выполняют весь банк, исходный S1 — 128 заранее выбранных историй каждого закона/задачи. Внешняя проверка включает физический баланс и независимый результат всей партии.',
        '', '| Задача | Вариант | Длительность без отказов | Успех F1, % | Успех F2, % |', '|---|---|---:|---:|---:|']
    for record in records:
        for plan in record['plans']:
            aliases=', '.join(plan['aliases']);p=plan['regimes']
            values=[f'{100*p[l]["probability"]:.2f}' if p[l]['probability'] is not None else 'UNAVAILABLE' for l in cfg['laws']]
            lines.append(f'| {record["instance"]} | {aliases} | {plan["nominal_makespan"]/100:g} | {values[0]} | {values[1]} |')
    lines+=['', f'Из {len(allcomparisons)} возвращённых представителей {same} физически совпали с собственным CP-prefix. Подтверждённых улучшений худшего режима по совместным границам: {len(confirmed_worst)}. Числа, парные выигрыши/потери и границы приведены в RESULT.json; один только лучший калибровочный балл преимуществом не считается.',
        '', 'CP-prefix — фактически затраченная общая начальная часть вызова. Полный CP-план — ранее зафиксированный сильный ориентир; его исторические затраты 0,350/235,078/235,089 с для Mk01/05/10 не являются новым парным измерением. Изменение качества относительно исходного плана не приписывается новой математике: генератор использует стандартные CP-SAT и поиск с прямой оценкой сценариев.',
        '', 'Для worst_regime сравниваются оба закона. Для Pareto публикуются все калибровочно выбранные представители, без отбора по тесту. Они недоминируемы по рабочему банку, но на новых сценариях это свойство может не сохраниться. Доказанный глобальный фронт не получен. Отсутствие внешнего выигрыша относительно дешёвого prefix оставляет пользу дополнительного поиска неподтверждённой.',
        '', 'В `external-quality.json` каждому возвращённому представителю сопоставлены prefix и полный CP. Отдельно записаны наблюдаемые отношения точек и подтверждённые совместными границами доминирование, проигрыш или компромисс. INCONCLUSIVE означает недостаток оснований для такого вывода; это не доказанное равенство. Для prefix используется заранее объявленное семейство парных сравнений, для полного CP — семейство границ вероятностей. Эти два семейства имеют отдельные 95%-е гарантии.',
        '', 'Ранее проверенный deadline_f1 совпал с коротким CP-prefix в 7 из 9 случаев; для двух остальных подтверждённого выигрыша не получено. Полный CP был лучше по F1 на Mk10. В том отдельном сравнении преимущество дополнительного поиска не установлено. Новые worst/Pareto оцениваются отдельно по приведённым выше внешним результатам.',
        '', '## Цена нового поиска', '',
        '| Задача | Полный вызов генератора, с | Наблюдённое окно CP-prefix, с |', '|---|---:|---:|']
    for instance in cfg['instances']:
        values=[r for r in costs if r['instance']==instance]
        if values:
            lines.append(f'| {instance} | {min(r["generation_process_s"] for r in values):.2f}–{max(r["generation_process_s"] for r in values):.2f} | '
                         f'{min(r["observed_prefix_window_s"] for r in values):.3f}–{max(r["observed_prefix_window_s"] for r in values):.3f} |')
    lines+=['', 'Диапазоны охватывают все шесть вызовов каждого экземпляра. Время полного процесса включает подготовку входа, CP-SAT, виртуальные оценки кандидатов, выбор и сохранение результата. Окно prefix относится к тому же вызову; отдельным standalone измерением оно не является. Общая подготовка окружения и внешняя проверка дополнительно расходуют runner-время.',
        '', f'Ошибочных оценок кандидатов: {sum(r["failures"] or 0 for r in costs)}; оборванных по бюджету оценок: {sum(r["censored"] or 0 for r in costs)}. Причины остановки вызовов: {dict(Counter(r["stopping"] for r in costs))}. Предел итераций включает повторных кандидатов из кэша и не означает столько же различных расписаний.',
        '', '## Воспроизводимые результаты и планы', '',
        '`catalog.csv` связывает каждый возвращённый вариант с настоящими schedule.json и schedule.csv. `plans/historical-v1/` содержит все старые цели с исторической версией; `plans/current/` — новые worst/Pareto и контроли; `plans/current-prior/` — ранее проверенные текущие nominal/deadline_f1. Их прежний внешний банк находится в `prior-validation.csv`, отдельно от нового. `inputs/` содержит исходные условия без расписания. Одинаковые физические планы могут соответствовать нескольким целям. `plans.csv` содержит новые внешние вероятности и совместные границы; `costs.csv` — полное время вызова, наблюдённое окно CP-prefix, завершённые/ошибочные/оборванные оценки. Подготовка окружения и весь runner-бюджет сохранены в provenance/budget.json и workflow logs.',
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
