"""Addressed repair campaign with sealed decisions and independent production checks."""
import argparse
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from .common import actions_only,canonical,digest,read_json,write_json
from .end_to_end import run
from .fixed_plan_reinforcement import Scorer,compress_traces
from .inverse_conditions import SOURCES as INVERSE_SOURCES,base_plan,draw,full_check,scalar
from .inverse_math import analysis
from .releases import fetch
from .statistics import lower,upper

ROOT=Path('output/addressed')
SOURCES=tuple(dict.fromkeys((*INVERSE_SOURCES,'industrial/addressed_repair.py','industrial/addressed_search.py',
    'engines/addressed_oracle.cpp','provenance/addressed_repair.json','docs/ADDRESSED_REPAIR_RU.md')))


def spec():return read_json('provenance/addressed_repair.json')
def fingerprint():return {p:digest(Path(p).read_bytes()) for p in SOURCES}
def stamp():return dict(commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
def cases():return {i+'-'+l for i in spec()['instances'] for l in spec()['laws']}


def build():
    ROOT.mkdir(parents=True,exist_ok=True);Path('build').mkdir(exist_ok=True);started=time.perf_counter()
    command=['g++','-std=c++20','-O3','-DNDEBUG','-Wall','-Wextra','-Werror','-Ivendor','-Iengines',
        'engines/addressed_oracle.cpp','engines/dag_ref/dag.cpp','-o','build/addressed-oracle']
    subprocess.run(command,check=True)
    record=dict(oracle_compile_s=time.perf_counter()-started,command=command,oracle_sha256=digest(Path('build/addressed-oracle').read_bytes()))
    if os.environ.get('STAGE') in ('qualify','validate'):
        from .inverse_conditions import build as inverse_build
        inverse_build();record['validation_build']=read_json('output/inverse/build.json')
    write_json(ROOT/'build.json',dict(record,**stamp()))


def pair_bank(data,law,count,split):
    original='F2' if law=='F2SI' else 'F1'
    base=draw(data,original,1,count,split);fast=draw(data,original,spec()['repair_multiplier'],count,split)
    return [dict(base=b,fast=f) for b,f in zip(base,fast)]


def mix(data,pairs,mask):
    used=sum(1<<m for m,q in enumerate(data['queues']) if q);result=[]
    if mask&~used:raise ValueError('unused machine intervention')
    for row in pairs:
        base,fast=row['base'],row['fast']
        failures=[v for v in base['failures'] if not mask>>v[0]&1]+[v for v in fast['failures'] if mask>>v[0]&1]
        result.append(dict(id=base['id'],failures=sorted(failures),work_overrides=[],
            shared_calendar=base['shared_calendar'] and mask in (0,used),shared_innovations=base['shared_calendar']))
    return result


def preparation():
    def window(name):
        a=ROOT/(name+'-start.txt');b=ROOT/(name+'-end.txt')
        return float(b.read_text())-float(a.read_text()) if a.exists() and b.exists() else 0.
    return dict(common_environment_s=window('common'),cp_environment_s=window('cp'),build=read_json(ROOT/'build.json'))


def worker(data,bank,a,folder,method,target,budget):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    executable=os.environ['CP_PYTHON'] if method=='lazy' else sys.executable
    command=[executable,'-m','industrial.addressed_search','--data',str(data),'--bank',str(bank),'--analysis',str(a),
        '--root',str(folder),'--method',method,'--target',str(target),'--budget',str(budget),
        '--cache-limit',str(spec()['cache_limit']),'--seed',str(spec()['seed'])]
    process=run(command,budget);write_json(folder/'process.json',process)
    if process['status']!='OK' or not (folder/'answer.json').exists():raise ValueError('addressed worker unavailable')
    answer=read_json(folder/'answer.json')
    if answer['status']!='PASS' or process['wall_s']>budget:raise ValueError('BUDGET_EXCEEDED: complete addressed worker process')
    return dict(answer,process=process)


def qualify():
    from tests.test_planning import problem
    from .inverse_math import normalize
    from .addressed_search import Oracle
    ROOT.mkdir(parents=True,exist_ok=True);tiny=problem()
    for o in tiny['operations']:o['release']=0
    tiny=normalize(tiny);tiny['nominal_makespan']=100
    chain=deepcopy(tiny);chain.update(dataset_id='addressed-chain-fixture',queues=[[0],[1]],jobs=[dict(id=0,release=0,final_operation=1)])
    chain['operations']=[deepcopy(tiny['operations'][0]),deepcopy(tiny['operations'][2])]
    chain['operations'][1].update(id=1,machine=1,predecessors=[0],alternatives=[dict(machine=1,work=30)])
    chain=normalize(chain);real,_=base_plan('Mk10');checks=[]
    for index,data in enumerate((tiny,chain,real)):
        folder=ROOT/'qualification'/str(index);folder.mkdir(parents=True)
        write_json(folder/'schedule.json',data);a=analysis(data);a['queues']=data['queues'];write_json(folder/'analysis.json',a)
        used=sum(1<<m for m,q in enumerate(data['queues']) if q)
        for law in spec()['laws']:
            bank=pair_bank(data,law,16,'addressed-v1-qualification');path=folder/(law+'-bank.json');write_json(path,bank)
            original='F2' if law=='F2SI' else 'F1';uniform_checks=[]
            for mask,rho in ((0,1),(used,.25)):
                expected=draw(data,original,rho,16,'addressed-v1-qualification')
                relevant=lambda histories:[[v for v in r['failures'] if data['queues'][v[0]]] for r in histories]
                actual_projected=relevant(mix(data,bank,mask));expected_projected=relevant(expected)
                if actual_projected!=expected_projected:
                    raise ValueError('uniform vector changed original renewal process')
                uniform_checks.append(dict(mask=mask,rho=rho,actual_used_sha256=digest(canonical(actual_projected)),
                    expected_used_sha256=digest(canonical(expected_projected)),raw_bank=str(path)))
            if index==1:
                def fixture(name,failures):return dict(id=name,failures=failures,work_overrides=[],shared_calendar=False)
                bank=[dict(base=fixture('serial',[[0,0,30],[1,60,90]]),fast=fixture('serial',[[0,0,10],[1,60,70]])),
                      dict(base=fixture('nonmonotone',[]),fast=fixture('nonmonotone',[[1,0,115]]))]
                write_json(path,bank)
            masks=list(range(used+1)) if index<2 else [0,used,used&0x55555555,used&0xaaaaaaaa]
            oracle_folder=folder/(law+'-oracle');oracle_folder.mkdir()
            oracle=Oracle(str(folder/'schedule.json'),str(path),str(folder/'analysis.json'),oracle_folder,
                spec()['cache_limit'],time.perf_counter()+120,len(bank))
            truth={}
            try:
                for mask in masks:
                    if mask&~used:continue
                    histories=mix(data,bank,mask);native,_=scalar(data,histories,folder/law/str(mask)/'des')
                    expected=[t is not None for t in native['finished_at']]
                    actual=oracle.query(mask)['labels']
                    if actual!=expected:raise ValueError('cached analytic DAG oracle differs from independent DES')
                    truth[mask]=sum(expected)
                    if index==2 or mask in (0,used):
                        labels=full_check(data,histories,folder/law/str(mask)/'full')
                        if list(labels.values())!=expected:raise ValueError('S1/full physical mismatch')
            finally:oracle.close()
            if index<2:
                target=max(truth.values());minimum=min(m.bit_count() for m,k in truth.items() if k>=target)
                for method in ('lazy','scan'):
                    r=worker(folder/'schedule.json',path,folder/'analysis.json',folder/(law+'-'+method),method,target,25)
                    if not r['search']['minimum_proved'] or r['selected']['count']!=minimum:
                        raise ValueError('inverse allocation disagrees with exhaustive independent DES')
            checks.append(dict(plan=data['dataset_id'],law=law,status='PASS',masks=len(truth),
                uniform_used_calendars_exact=True,uniform_checks=uniform_checks))
    write_json(ROOT/'qualification.json',dict(status='PASS',checks=checks,implementation=fingerprint(),spec=spec(),**stamp()))


def train(instance,law,registry):
    started=time.perf_counter();ROOT.mkdir(parents=True,exist_ok=True)
    source,qreceipt=fetch(registry['qualification'],'output/addressed-qualification');q=read_json(source/'qualification.json')
    if q['status']!='PASS' or q['implementation']!=fingerprint() or q['spec']!=spec():raise ValueError('unqualified addressed implementation')
    data,receipt=base_plan(instance);acquisition=time.perf_counter()-started;cfg=spec()
    t=time.perf_counter();write_json(ROOT/'schedule.json',data);a=analysis(data);a['queues']=data['queues'];write_json(ROOT/'analysis.json',a)
    input_prepare=time.perf_counter()-t
    t=time.perf_counter();bank=pair_bank(data,law,cfg['training_samples'],cfg['training_split']);write_json(ROOT/'bank.json',bank)
    generation=time.perf_counter()-t;results=[]
    for repeat in range(cfg['repetitions']):
        pair={}
        order=list(('lazy','scan') if repeat%2==0 else ('scan','lazy'));order.insert(repeat%3,'cheap')
        for method in order:
            pair[method]=worker(ROOT/'schedule.json',ROOT/'bank.json',ROOT/'analysis.json',ROOT/'workers'/str(repeat)/method,
                method,cfg['training_required_successes'],cfg['worker_budget_s'])
        results.append(pair);write_json(ROOT/'progress.json',dict(completed_pairs=len(results),required=cfg['repetitions']))
    write_json(ROOT/'bank.json.gz',bank);(ROOT/'bank.json').unlink()
    write_json(ROOT/'training.json',dict(status='PASS',instance=instance,law=law,results=results,
        plan_sha256=digest(canonical(data)),bank_sha256=digest(canonical(bank)),input_provenance=receipt,
        qualification_receipt=qreceipt,preparation=preparation(),acquisition_s=acquisition,input_prepare_s=input_prepare,generation_s=generation,
        wall_s=time.perf_counter()-started,implementation=fingerprint(),spec=cfg,**stamp()))


def seal(registry):
    ROOT.mkdir(parents=True,exist_ok=True);records=[];seen=set()
    for i,tag in enumerate(registry['trainings']):
        source,receipt=fetch(tag,f'output/addressed-train-{i}');r=read_json(source/'training.json');key=r['instance']+'-'+r['law']
        if key not in cases() or key in seen or r['status']!='PASS' or r['implementation']!=fingerprint() or r['spec']!=spec():
            raise ValueError('incomplete, changed or duplicate addressed training')
        seen.add(key);folder=ROOT/key;folder.mkdir();data=read_json(source/'schedule.json')
        if digest(canonical(data))!=r['plan_sha256']:raise ValueError('addressed plan changed')
        write_json(folder/'schedule.json',data);write_json(folder/'analysis.json',read_json(source/'analysis.json'))
        used=sum(1<<m for m,q in enumerate(data['queues']) if q);variants={}
        def add(mask,origin):
            if mask&~used:raise ValueError('unknown targeted machine')
            variants.setdefault(mask,dict(mask=mask,machines=[m for m in range(len(data['queues'])) if mask>>m&1],origins=[]))['origins'].append(origin)
        add(0,dict(method='none'));add(used,dict(method='uniform'))
        for repeat,pair in enumerate(r['results']):
            for method,answer in pair.items():
                add(answer['selected']['mask'],dict(method=method,repeat=repeat))
                if answer['cheap_best'] is not None:add(answer['cheap_best']['mask'],dict(method='cheap',repeat=repeat,parent=method))
                for control,value in answer['controls'].items():add(value['mask'],dict(method=control,repeat=repeat,parent=method))
        records.append(dict(training_release=tag,training_receipt=receipt,training=r,case=key,used_machines=used.bit_count(),variants=list(variants.values())))
    if seen!=cases():raise ValueError('all20 training cells required before opening validation')
    n=sum(len(r['variants']) for r in records)
    write_json(ROOT/'seal.json',dict(status='SEALED',records=records,configurations=n,one_sided_alpha=spec()['family_error']/(2*n),
        validation_bank_opened=False,implementation=fingerprint(),spec=spec(),**stamp()))


def validate(instance,law,registry):
    started=time.perf_counter();ROOT.mkdir(parents=True,exist_ok=True);cfg=spec()
    source,receipt=fetch(registry['seal'],'output/addressed-seal');sealed=read_json(source/'seal.json');key=instance+'-'+law
    if sealed['status']!='SEALED' or sealed['implementation']!=fingerprint() or sealed['spec']!=cfg:raise ValueError('addressed seal mismatch')
    if {r['case'] for r in sealed['records']}!=cases():raise ValueError('partial addressed seal')
    cell=next(r for r in sealed['records'] if r['case']==key);data=read_json(source/key/'schedule.json');write_json(ROOT/'schedule.json',data)
    deadline=11*data['nominal_makespan']//10;t=time.perf_counter();bank=pair_bank(data,law,cfg['validation_samples'],cfg['validation_split'])
    write_json(ROOT/'bank.json.gz',bank);generation=time.perf_counter()-t;records=[];alpha=sealed['one_sided_alpha']
    for variant in cell['variants']:
        t=time.perf_counter();mask=variant['mask'];histories=mix(data,bank,mask);folder=ROOT/'variants'/str(mask);folder.mkdir(parents=True)
        external,process=scalar(data,histories,folder/'des');expected=[t is not None for t in external['finished_at']]
        dag=Scorer(folder/'risk-dag',data,deadline,'dag');dag.root.mkdir()
        if dag.evaluate(data,histories,'addressed-validation')!=expected:raise ValueError('external DES/riskDAG disagreement')
        s1=Scorer(folder/'s1',data,deadline,'tsfg');s1.root.mkdir()
        if s1.evaluate(data,histories[:cfg['s1_scalar_samples']],'addressed-S1-subset')!=expected[:cfg['s1_scalar_samples']]:
            raise ValueError('addressed original S1 disagreement')
        labels=full_check(data,histories[:cfg['full_trace_samples']],folder/'full')
        if list(labels.values())!=expected[:cfg['full_trace_samples']]:raise ValueError('addressed full trace mismatch')
        for root in (dag.root,s1.root):
            for name in ('current-plan.json','current-scenarios.json'):(root/name).unlink(missing_ok=True)
        n=len(expected);k=sum(expected);lo,hi=lower(k,n,alpha),upper(k,n,alpha)
        record=dict(variant,successes=k,samples=n,probability=k/n,lower=lo,upper=hi,
            status='FEASIBLE' if lo>=cfg['target_probability'] else 'INFEASIBLE' if hi<cfg['target_probability'] else 'UNRESOLVED',
            validation_wall_s=time.perf_counter()-t,des_process=process,dag_calls=dag.calls,s1_calls=s1.calls,
            analytic_mismatches=0,scenario_sha256=digest(canonical(histories)))
        records.append(record);write_json(folder/'condition.json',record);compress_traces(folder)
    write_json(ROOT/'validation.json',dict(status='PASS',case=key,instance=instance,law=law,conditions=records,
        seal_release=registry['seal'],seal_receipt=receipt,training_cell=cell,preparation=preparation(),generation_s=generation,
        wall_s=time.perf_counter()-started,one_sided_alpha=alpha,implementation=fingerprint(),spec=cfg,**stamp()))


def main():
    actions_only();p=argparse.ArgumentParser();p.add_argument('stage');p.add_argument('--instance');p.add_argument('--law');p.add_argument('--registry',default='{}')
    args=p.parse_args();registry=json.loads(args.registry)
    if args.stage=='build':build()
    elif args.stage=='qualify':qualify()
    elif args.stage=='train':train(args.instance,args.law,registry)
    elif args.stage=='seal':seal(registry)
    elif args.stage=='validate':validate(args.instance,args.law,registry)
    elif args.stage=='report':
        from .addressed_report import report
        report(registry)
    else:raise ValueError(args.stage)


if __name__=='__main__':main()
