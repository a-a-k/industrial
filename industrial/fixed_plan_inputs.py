"""Prepare fixed input schedules using the already qualified nominal planner."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
from .common import actions_only,canonical,digest,read_json,write_json
from .end_to_end import run
from .production import check_physics,compare,simulate
from .releases import fetch
from planning.generator import from_conditions,validate_problem

ROOT=Path('output/fixed-input')


def profile():return read_json('provenance/fixed_plan_inputs.json')


def conditions(data):
    raw={k:v for k,v in data.items() if k not in ('queues','nominal_makespan','planned_makespan')}
    raw['machines']=len(data['queues'])
    raw['operations']=[{k:v for k,v in o.items() if k not in ('machine','work','planned_start','planned_end')} for o in data['operations']]
    return raw


def prepare(instance):
    cfg=profile();ROOT.mkdir(parents=True,exist_ok=True)
    if instance not in cfg['instances']:raise ValueError('unregistered instance')
    source,receipt=fetch(cfg['preflight'],'output/fixed-input-preflight')
    if read_json(source/'preflight.json')['status']!='PASS':raise ValueError('unavailable preflight')
    original=read_json(source/instance/'dataset.json');raw=conditions(original);rebuilt=from_conditions(raw)
    if canonical(rebuilt)!=canonical(original):raise ValueError('raw constraints changed the frozen reference')
    deadline=original['nominal_makespan']*11//10
    write_json(ROOT/'original.json',original)
    problem=dict(conditions=raw,deadline=deadline,spec=dict(search=dict(total_budget_s=cfg['cp_budget_s'])))
    write_json(ROOT/'problem.json',problem)
    if instance in cfg['legacy_instances']:
        plan=read_json(f'results/cpsat/schedules/{instance}.json')
        prior=read_json('results/cpsat/RESULT.json')
        historical=next(r for r in prior['generation'] if r['instance']==instance)
        entry=dict(origin='unchanged frozen earlier CP plan',source=cfg['legacy_source'],historical_generation=historical,
                   new_optimizer_execution=False)
    else:
        process=run([os.environ['CP_PYTHON'],'-m','industrial.plan',str(ROOT/'problem.json'),
            '--folder',str(ROOT/'cp'),'--objective','nominal','--seed',str(cfg['seed'])],timeout=300)
        result=read_json(ROOT/'cp/result.json') if (ROOT/'cp/result.json').exists() else dict(status='UNAVAILABLE')
        entry=dict(origin='existing qualified nominal interface from raw conditions',process=process,result=result,
                   new_optimizer_execution=True)
        write_json(ROOT/'generation-process.json',entry)
        if process['status']!='OK' or process['wall_s']>cfg['cp_budget_s'] or result['status']!='PASS':
            raise ValueError('nominal planning unavailable or exceeded full fresh-process budget')
        plan=read_json(ROOT/'cp/schedule.json')
    validate_problem(plan)
    if canonical(conditions(plan))!=canonical(raw) or plan['nominal_makespan']!=original['nominal_makespan']:
        raise ValueError('plan changed constraints or reference C0')
    if plan['planned_makespan']>original['nominal_makespan']:raise ValueError('nominal plan worse than feasible initial hint')
    write_json(ROOT/'schedule.json',plan)
    with (ROOT/'schedule.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['id','job','machine','work','planned_start','planned_end'],extrasaction='ignore')
        writer.writeheader();writer.writerows(plan['operations'])
    scenario=dict(id='fixed-input-nominal-'+instance,failures=[],work_overrides=[]);outputs=[];processes=[]
    for engine in ('des','dag'):
        rows,ps=simulate(plan,[scenario],ROOT/'nominal'/engine,engine,5*original['nominal_makespan']//4)
        processes.extend(ps)
        if scenario['id'] not in rows or any(p['status']!='OK' for p in ps):raise ValueError('nominal input verification unavailable')
        row=rows[scenario['id']];check_physics(plan,scenario,row)
        if row['cmax']!=plan['planned_makespan']:raise ValueError('nominal makespan does not reproduce')
        outputs.append(row)
    compare(outputs[0],outputs[1])
    write_json(ROOT/'input.json',dict(status='PASS',instance=instance,profile=cfg,preflight_receipt=receipt,
        nominal_generation=entry,nominal_checks=processes,reference_C0=original['nominal_makespan'],deadline=deadline,
        planned_makespan=plan['planned_makespan'],schedule_sha256=digest(canonical(plan)),
        constraint_sha256=digest(canonical(raw)),commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))


def seal(registry):
    cfg=profile();ROOT.mkdir(parents=True,exist_ok=True);records=[];seen=set()
    for index,tag in enumerate(registry['inputs']):
        folder,receipt=fetch(tag,f'output/input-seal-{index}');record=read_json(folder/'input.json')
        if record['status']!='PASS' or record['profile']!=cfg or record['instance'] in seen:
            raise ValueError('incomplete, changed or duplicate input')
        instance=record['instance'];seen.add(instance);plan=read_json(folder/'schedule.json')
        if digest(canonical(plan))!=record['schedule_sha256']:raise ValueError('input plan changed')
        dest=ROOT/instance;dest.mkdir()
        for name in ('schedule.json','schedule.csv','original.json','problem.json','input.json'):
            shutil.copyfile(folder/name,dest/name)
        records.append(dict(release=tag,archive_sha256=receipt['archive_sha256'],**record))
    if seen!=set(cfg['instances']):raise ValueError('all ten input plans must be frozen')
    write_json(ROOT/'seal.json',dict(status='SEALED',profile=cfg,inputs=records,commit=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],role='fixed plans; no local correction training or holdout opened'))
    lines=['# Зафиксированные исходные планы Mk01–Mk10','',
        'Для трёх задач сохранены прежние CP-планы, для остальных вызван существующий номинальный планировщик. Сроки и шкала отказов относятся к исходному C0. Это исследовательские примеры, не планы реального предприятия.',
        '', '| Задача | Исходный C0 | Длительность CP-плана | Прежний срок | Источник |', '|---|---:|---:|---:|---|']
    for r in sorted(records,key=lambda r:r['instance']):
        lines.append(f'| {r["instance"]} | {r["reference_C0"]/100:g} | {r["planned_makespan"]/100:g} | {r["deadline"]/100:g} | {r["nominal_generation"]["origin"]} |')
    lines+=['', 'Времена прежней генерации указаны как исторические. Они не выдаются за новые парные измерения. Проверка нового локального исправления начинается от одинакового зафиксированного плана для всех методов.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    actions_only();parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','seal'))
    parser.add_argument('--instance');parser.add_argument('--registry',default='{}');args=parser.parse_args()
    if args.stage=='prepare':prepare(args.instance)
    else:seal(json.loads(args.registry))
