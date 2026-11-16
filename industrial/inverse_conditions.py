"""Inverse plan/repair requirements; all numerical execution is Actions-only."""
import argparse
from copy import deepcopy
import csv
from itertools import permutations,product
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from .common import actions_only,canonical,digest,read_json,rng,write_json
from .end_to_end import run
from .fixed_plan_reinforcement import Scorer,compress_traces
from .inverse_math import analysis,distance,identity,normalize
from .local_corrections import diff
from .production import check_physics,compare,outcomes,product_ledger,simulate
from .releases import fetch
from .statistics import lower,upper

ROOT=Path('output/inverse')
SOURCES=('industrial/inverse_conditions.py','industrial/inverse_math.py','planning/inverse_candidates.py',
    'industrial/common.py','industrial/inputs.py','industrial/production.py','industrial/fixed_plan_inputs.py',
    'industrial/fixed_plan_reinforcement.py','industrial/end_to_end.py','industrial/targets.py','industrial/statistics.py',
    'industrial/local_corrections.py','planning/generator.py','engines/inverse_scalar.cpp','engines/risk_main.cpp',
    'engines/model.hpp','engines/des_ref/des.cpp','engines/dag_ref/dag.cpp','engines/tsfg_op/operation_adapter.go',
    'provenance/inverse_conditions.json','docs/INVERSE_CONDITIONS_RU.md')


def spec():return read_json('provenance/inverse_conditions.json')
def fingerprint():return {p:digest(Path(p).read_bytes()) for p in SOURCES}
def stamp():return dict(commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
def rho_label(rho):return str(rho).replace('.','p')


def save_plan(folder,data):
    root=Path(folder);root.mkdir(parents=True,exist_ok=True);write_json(root/'schedule.json',data)
    with (root/'schedule.csv').open('w',newline='') as stream:
        rows=[{k:o[k] for k in ('id','job','machine','work','planned_start','planned_end')} for o in data['operations']]
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def base_plan(instance):
    source,receipt=fetch(spec()['input_seal'],'output/inverse-inputs');seal=read_json(source/'seal.json')
    if seal['status']!='SEALED' or {r['instance'] for r in seal['inputs']}!=set(spec()['instances']):raise ValueError('fixed input seal unavailable')
    record=next(r for r in seal['inputs'] if r['instance']==instance);data=read_json(source/instance/'schedule.json')
    if digest(canonical(data))!=record['schedule_sha256'] or canonical(normalize(data))!=canonical(data):raise ValueError('base changed or is not earliest')
    return data,dict(release=spec()['input_seal'],receipt=receipt,record=record)


def build():
    ROOT.mkdir(parents=True,exist_ok=True);Path('build').mkdir(exist_ok=True);records=[]
    flags=['-std=c++20','-O3','-DNDEBUG','-Wall','-Wextra','-Werror','-Ivendor','-Iengines']
    for target,files in [('risk-dag',['engines/risk_main.cpp']),
        ('inverse-scalar',['engines/inverse_scalar.cpp','engines/des_ref/des.cpp','engines/dag_ref/dag.cpp'])]:
        started=time.perf_counter();command=['g++',*flags,*files,'-o','build/'+target]
        subprocess.run(command,check=True);records.append(dict(target=target,command=command,wall_s=time.perf_counter()-started,
            sha256=digest(Path('build',target).read_bytes())))
    write_json(ROOT/'build.json',dict(records=records,**stamp()))


def draw(data,law,rho,count,split=None):
    cfg=spec();split=cfg['certification_split'] if split is None else split
    c0=data['nominal_makespan'];horizon=5*c0//4;result=[]
    if rho not in cfg['repair_multipliers'] or law not in cfg['laws']:raise ValueError('unregistered condition')
    def calendar(source):
        clock=0;down=[];up_sum=repair_sum=0.;cycles=0
        while clock<horizon:
            up=source.expovariate(1/(2*c0));repair=source.expovariate(1/(.1*c0*rho))
            up_sum+=up;repair_sum+=repair;cycles+=1
            clock+=max(5,math.ceil(up/5)*5)
            if clock>horizon:break
            end=clock+max(5,math.ceil(repair/5)*5);down.append((clock,end));clock=end
        return down,dict(raw_up_sum=up_sum,raw_repair_sum=repair_sum,drawn_cycles=cycles)
    for index in range(count):
        aid=f'{data["dataset_id"]}-{law}-{split}-{index:04d}';shared=law=='F2' and rng(aid,'mixture').random()<.5
        if shared:
            common,stat=calendar(rng(aid,'shared'));histories=[common for _ in data['queues']];stats=[stat]
        else:
            pairs=[calendar(rng(aid,'machine',m)) for m in range(len(data['queues']))]
            histories=[v[0] for v in pairs];stats=[v[1] for v in pairs]
        result.append(dict(id=aid,failures=[[m,a,b] for m,hist in enumerate(histories) for a,b in hist],
            work_overrides=[],shared_calendar=shared,raw_duration_statistics=stats))
    return result


def scalar(plan,histories,folder,engine='des'):
    root=Path(folder);root.mkdir(parents=True,exist_ok=True);a=analysis(plan,spec()['window_limit_per_machine'])
    write_json(root/'dataset.json',plan);write_json(root/'scenarios.json',histories);write_json(root/'analysis.json',a)
    command=[str(Path('build/inverse-scalar').resolve()),engine,str(root/'dataset.json'),str(root/'scenarios.json'),
             str(root/'production.json'),str(a['deadline']),str(root/'analysis.json')]
    process=run(command,spec()['process_watchdog_s']);write_json(root/'process.json',process)
    if process['status']!='OK':raise ValueError('independent scalar production unavailable')
    answer=read_json(root/'production.json')
    if answer['sample_count']!=len(histories) or answer['analytic_mismatches']!=0:raise ValueError('scalar analytic census mismatch')
    (root/'scenarios.json').unlink();return answer,process


def full_check(plan,histories,folder):
    root=Path(folder);deadline=11*plan['nominal_makespan']//10;traces={};processes=[]
    for engine in ('des','dag','tsfg'):
        rows,ps=simulate(plan,histories,root/engine,engine,5*plan['nominal_makespan']//4)
        processes.extend(ps)
        if len(rows)!=len(histories) or any(p['status']!='OK' for p in ps):raise ValueError('full trace check unavailable')
        traces[engine]=rows
    for s in histories:
        for engine in traces:check_physics(plan,s,traces[engine][s['id']])
        compare(traces['des'][s['id']],traces['dag'][s['id']]);compare(traces['des'][s['id']],traces['tsfg'][s['id']])
    labels=outcomes(product_ledger(plan,histories,traces['des']),[j['id'] for j in plan['jobs']],deadline)
    write_json(root/'checks.json',dict(status='PASS',samples=len(histories),processes=processes,mismatches=0))
    compress_traces(root);return labels


def qualify():
    from tests.test_planning import problem
    from planning.generator import decode
    from .inputs import scenarios as original_draw
    ROOT.mkdir(parents=True,exist_ok=True);tiny=problem();tiny['operations'][1]['release']=0
    tiny=normalize(tiny);tiny['nominal_makespan']=100;write_json(ROOT/'tiny.json',tiny);checks=[]
    possibilities={}
    for assignment in product(*[range(len(o['alternatives'])) for o in tiny['operations']]):
        for priority in permutations(range(len(tiny['operations']))):
            plan=decode(tiny,(assignment,priority));possibilities[identity(plan)]=plan
    def key(plan,objective):
        dist=distance(tiny,plan)['total'];load=max(sum(plan['operations'][i]['work'] for i in q) for q in plan['queues'])
        pair=(plan['planned_makespan'],load) if objective=='nominal' else (load,plan['planned_makespan'])
        return (*pair,dist)
    plans={identity(tiny):tiny}
    for cap in (1,4):
        for objective in ('nominal','load'):
            folder=ROOT/'cp-check'/f'{cap}-{objective}'
            process=run([os.environ['CP_PYTHON'],'-m','planning.inverse_candidates',str(ROOT/'tiny.json'),str(folder),
                '--cap',str(cap),'--objective',objective,'--budget','8'],30)
            if process['status']!='OK':raise ValueError('inverse CP qualification process')
            result=read_json(folder/'result.json');plan=read_json(folder/'schedule.json')
            feasible=[p for p in possibilities.values() if distance(tiny,p)['total']<=cap and p['planned_makespan']<=110]
            if result['solver_status']!='OPTIMAL' or key(plan,objective)!=min(key(p,objective) for p in feasible):
                raise ValueError('inverse CP disagrees with independent exhaustive tiny reference')
            plans[identity(plan)]=plan;checks.append(dict(kind='CP-vs-exhaustive',cap=cap,objective=objective,status='PASS'))
    for law in spec()['laws']:
        split='inverse-conditions-v1-qualification'
        if canonical(draw(tiny,law,1,16,split))!=canonical(original_draw(tiny,law,split,16)):
            raise ValueError('rho=1 changed the frozen renewal law')
    real,_=base_plan('Mk10');plans[identity(real)]=real
    for index,plan in enumerate(plans.values()):
        for law in spec()['laws']:
            for rho in (1,.25):
                histories=draw(plan,law,rho,16,'inverse-conditions-v1-qualification')
                if plan['dataset_id']=='planner-fixture':
                    histories.extend([dict(id=f'boundary-{index}-{law}-{rho}-{k}',failures=failures,work_overrides=[],shared_calendar=False)
                        for k,failures in enumerate(([],[[0,0,220]],[[0,65,110],[1,0,40]]))])
                folder=ROOT/'checks'/f'{index}-{law}-{rho_label(rho)}'
                native,_=scalar(plan,histories,folder/'scalar')
                labels=full_check(plan,histories,folder/'full')
                expected=[labels[s['id']] for s in histories]
                if [t is not None for t in native['finished_at']]!=expected:raise ValueError('scalar vs product ledger mismatch')
                for engine in ('dag','tsfg'):
                    scorer=Scorer(folder/engine,plan,11*plan['nominal_makespan']//10,engine);scorer.root.mkdir(parents=True,exist_ok=True)
                    if scorer.evaluate(plan,histories,'inverse-qualification')!=expected:raise ValueError('S1/risk-DAG scalar mismatch')
                checks.append(dict(kind='physical-and-analytic',plan=identity(plan),law=law,rho=rho,samples=len(histories),status='PASS'))
    write_json(ROOT/'qualification.json',dict(status='PASS',checks=checks,implementation=fingerprint(),spec=spec(),**stamp()))


def catalogue(instance,registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);base,provenance=base_plan(instance)
    qsource,qreceipt=fetch(registry['qualification'],'output/inverse-qualification');q=read_json(qsource/'qualification.json')
    if q['status']!='PASS' or q['implementation']!=fingerprint() or q['spec']!=cfg:raise ValueError('unqualified inverse implementation')
    save_plan(ROOT/'base',base);started=time.perf_counter();records=[];plans={}
    def add(plan,origin):
        plan=normalize(plan);d=distance(base,plan);k=identity(plan)
        if plan['planned_makespan']>11*base['nominal_makespan']//10:raise ValueError('healthy candidate misses original deadline')
        if k not in plans:
            folder=ROOT/'plans'/k;save_plan(folder,plan);write_json(folder/'diff.json',diff(base,plan))
            write_json(folder/'analysis.json',analysis(plan,cfg['window_limit_per_machine']))
            plans[k]=dict(key=k,distance=d,nominal=plan['planned_makespan'],origins=[],schedule_sha256=digest(canonical(plan)))
        plans[k]['origins'].append(origin)
    add(base,'frozen approved benchmark input')
    for cap in cfg['distance_caps']:
        for objective in cfg['candidate_objectives']:
            if time.perf_counter()-started+cfg['candidate_process_budget_s']>cfg['candidate_family_budget_s']:
                raise TimeoutError('not all six required bounded CP attempts fit family budget')
            label=f'{cap}-{objective}';folder=ROOT/'searches'/label
            process=run([os.environ['CP_PYTHON'],'-m','planning.inverse_candidates',str(ROOT/'base/schedule.json'),str(folder),
                '--cap',str(cap),'--objective',objective,'--budget',str(cfg['candidate_process_budget_s']),'--seed',str(cfg['seed'])],60)
            records.append(dict(cap=cap,objective=objective,process=process));write_json(ROOT/'progress.json',records)
            if process['status']!='OK' or process['wall_s']>cfg['candidate_process_budget_s']:raise ValueError('bounded CP process unavailable or over budget')
            result=read_json(folder/'result.json');records[-1]['result']=result
            if result['status']!='PASS':raise ValueError('bounded candidate failed')
            plan=read_json(folder/'schedule.json')
            if distance(base,plan)['total']>cap:raise ValueError('physical edit cap exceeded after normalization')
            add(plan,label)
    write_json(ROOT/'catalogue.json',dict(status='PASS',instance=instance,base_provenance=provenance,qualification_receipt=qreceipt,
        plans=list(plans.values()),attempts=records,catalogue_wall_s=time.perf_counter()-started,
        implementation=fingerprint(),spec=cfg,**stamp()))


def seal(registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);records=[];seen=set()
    for index,tag in enumerate(registry['catalogues']):
        source,receipt=fetch(tag,f'output/inverse-catalogue-{index}');r=read_json(source/'catalogue.json');instance=r['instance']
        if r['status']!='PASS' or r['implementation']!=fingerprint() or r['spec']!=cfg or instance in seen:
            raise ValueError('incomplete, duplicate or changed inverse catalogue')
        seen.add(instance);dest=ROOT/instance;dest.mkdir();shutil.copytree(source/'plans',dest/'plans')
        shutil.copytree(source/'base',dest/'base')
        for p in r['plans']:
            if digest(canonical(read_json(dest/'plans'/p['key']/'schedule.json')))!=p['schedule_sha256']:raise ValueError('catalogue plan changed')
        records.append(dict(release=tag,receipt=receipt,**r))
    if seen!=set(cfg['instances']):raise ValueError('all ten catalogues required before any certification bank')
    total=sum(len(r['plans']) for r in records)*len(cfg['laws'])*len(cfg['repair_multipliers'])
    write_json(ROOT/'seal.json',dict(status='SEALED',catalogues=records,configurations=total,
        one_sided_alpha=cfg['confidence_family_error']/(2*total),certification_bank_opened=False,
        implementation=fingerprint(),spec=cfg,**stamp()))


def certify(instance,law,registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    source,receipt=fetch(registry['seal'],'output/inverse-global-menu');sealed=read_json(source/'seal.json')
    if sealed['status']!='SEALED' or sealed['implementation']!=fingerprint() or sealed['spec']!=cfg:
        raise ValueError('unavailable immutable inverse menu')
    if {r['instance'] for r in sealed['catalogues']}!=set(cfg['instances']):raise ValueError('partial menu cannot open bank')
    catalog=next(r for r in sealed['catalogues'] if r['instance']==instance);base=read_json(source/instance/'base/schedule.json')
    alpha=sealed['one_sided_alpha'];records=[];deadline=11*base['nominal_makespan']//10
    for rho in cfg['repair_multipliers']:
        histories=draw(base,law,rho,cfg['certification_samples']);write_json(ROOT/'scenarios'/(rho_label(rho)+'.json.gz'),histories)
        scenario_sha=digest(canonical(histories))
        for p in catalog['plans']:
            plan=read_json(source/instance/'plans'/p['key']/'schedule.json')
            if digest(canonical(plan))!=p['schedule_sha256']:raise ValueError('sealed physical plan changed')
            folder=ROOT/'configurations'/(p['key']+'-'+rho_label(rho));folder.mkdir(parents=True)
            external,process=scalar(plan,histories,folder/'des')
            expected=[t is not None for t in external['finished_at']]
            scorer=Scorer(folder/'risk-dag',plan,deadline,'dag');scorer.root.mkdir()
            if scorer.evaluate(plan,histories,'inverse-new-certification')!=expected:raise ValueError('risk DAG vs external products mismatch')
            scorer_s1=Scorer(folder/'s1',plan,deadline,'tsfg');scorer_s1.root.mkdir()
            if scorer_s1.evaluate(plan,histories[:cfg['s1_scalar_samples']],'inverse-S1-fixed-subset')!=expected[:cfg['s1_scalar_samples']]:
                raise ValueError('original S1 scalar disagrees with external products')
            labels=full_check(plan,histories[:cfg['full_trace_samples']],folder/'full')
            if list(labels.values())!=expected[:cfg['full_trace_samples']]:raise ValueError('full trace external census mismatch')
            for root in (scorer.root,scorer_s1.root):
                for name in ('current-plan.json','current-scenarios.json'):
                    if (root/name).exists():(root/name).unlink()
            n=len(expected);k=sum(expected);lo,hi=lower(k,n,alpha),upper(k,n,alpha)
            status='FEASIBLE' if lo>=cfg['target_probability'] else 'INFEASIBLE' if hi<cfg['target_probability'] else 'UNRESOLVED'
            a=read_json(folder/'des/analysis.json')
            record=dict(instance=instance,law=law,plan=p['key'],distance=p['distance'],rho=rho,
                raw_mean_repair_ticks=.1*base['nominal_makespan']*rho,nominal=plan['planned_makespan'],deadline=deadline,
                successes=k,samples=n,probability=k/n,lower=lo,upper=hi,status=status,one_sided_alpha=alpha,
                analytic_guaranteed_successes=external['sufficient_success_count'],analytic_necessary_failures=external['necessary_failure_count'],
                analytic_bounds=[external['sufficient_success_count']/n,1-external['necessary_failure_count']/n],
                analytic_mismatches=0,shared_exact_checks=external['shared_exact_checks'],
                windows=[dict(w,violations=c) for w,c in zip(a['windows'],external['window_failure_counts'])],
                production_process=process,dag_calls=scorer.calls,s1_calls=scorer_s1.calls,
                s1_scalar_samples=cfg['s1_scalar_samples'],full_trace_samples=cfg['full_trace_samples'],
                scenario_sha256=scenario_sha,schedule_sha256=p['schedule_sha256'])
            records.append(record);write_json(folder/'condition.json',record)
            compress_traces(folder);write_json(ROOT/'progress.json',dict(completed=len(records),required=len(catalog['plans'])*len(cfg['repair_multipliers'])))
    expected_count=len(catalog['plans'])*len(cfg['repair_multipliers'])
    if len(records)!=expected_count:raise ValueError('certification menu incomplete')
    write_json(ROOT/'certification.json',dict(status='PASS',instance=instance,law=law,conditions=records,
        catalogue=catalog,seal_release=registry['seal'],seal_receipt=receipt,configurations_in_global_family=sealed['configurations'],
        one_sided_alpha=alpha,wall_s=time.perf_counter()-started,implementation=fingerprint(),spec=cfg,**stamp()))


def main():
    actions_only();p=argparse.ArgumentParser();p.add_argument('stage');p.add_argument('--instance');p.add_argument('--law')
    p.add_argument('--registry',default='{}');args=p.parse_args();registry=json.loads(args.registry)
    if args.stage=='build':build()
    elif args.stage=='qualify':qualify()
    elif args.stage=='catalogue':catalogue(args.instance,registry)
    elif args.stage=='seal':seal(registry)
    elif args.stage=='certify':certify(args.instance,args.law,registry)
    elif args.stage=='report':
        from .inverse_report import report
        report(registry)
    else:raise ValueError('unregistered inverse stage')


if __name__=='__main__':
    try:main()
    except Exception as error:
        ROOT.mkdir(parents=True,exist_ok=True);write_json(ROOT/'failure.json',dict(status='FAILED',error=type(error).__name__+': '+str(error),**stamp()))
        raise
