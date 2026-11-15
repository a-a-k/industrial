"""The original E6 small-model timing control, with identical scalar outputs."""
import argparse
from itertools import product
import os
from pathlib import Path
import resource
import statistics
import sys
import time
from .common import actions_only,canonical,digest,execute,read_json,rng,write_json

CASE='E3-seven-all-fibers:available:2187:panel:full-oracle'


def prepare(folder):
    from tests.test_frozen_core import make,row
    from .model import VERSION
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    ids=make([row()])['signal_ids']
    model=make([dict(zip(ids,values)) for values in product((None,False,True),repeat=7)])
    model['version']=VERSION
    write_json(folder/'model.json.gz',model)
    write_json(folder/'input-receipt.json',dict(model_sha256=digest(canonical(model)),
        coordinates=7,categories=2187,category_count=1,source='unchanged E3 seven-coordinate fixture',
        target='all thirteen scalar bounds; neither method computes joint images or witnesses'))


def method(folder,which,out):
    started=time.perf_counter();folder=Path(folder)
    model=read_json(folder/'model.json.gz');receipt=read_json(folder/'input-receipt.json')
    if digest(canonical(model))!=receipt['model_sha256']:raise ValueError('small-model input differs')
    read_s=time.perf_counter()-started
    if which=='full':
        from .solver import Compiled
        estimates=Compiled(model).solve()['estimates']
    elif which=='oracle':
        from .oracle import compatible,evaluate
        from .targets import estimate
        totals={}
        for category in model['observation_categories']:
            extrema={}
            for state in compatible(model,category['values']):
                for name,value in evaluate(model,state).items():
                    value=int(value)
                    pair=extrema.setdefault(name,[value,value])
                    pair[0]=min(pair[0],value);pair[1]=max(pair[1],value)
            for name,pair in extrema.items():
                weighted=totals.setdefault(name,[0,0])
                for side in (0,1):weighted[side]+=category['count']*pair[side]
        estimates={name:estimate(*pair,model['sample_count']) for name,pair in totals.items()}
    else:raise ValueError('undeclared small-model method')
    if len(estimates)!=13:raise ValueError('incomplete scalar panel')
    write_json(out,dict(status='OK',method=which,query='panel',estimates=estimates,
        signature=digest(canonical(estimates)),phases=dict(read_s=read_s,analysis_s=time.perf_counter()-started-read_s),
        wall_internal_s=time.perf_counter()-started,
        cpu_s=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        representation_bytes=(folder/'model.json.gz').stat().st_size))


def paired():
    root=Path('output/measurement');root.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter()
    prep=execute([sys.executable,'-m','industrial.small_cost','prepare',str(root/'load')])
    setup_s=time.perf_counter()-started;attempts=[]
    if prep['status']=='OK':
        for repeat in range(6):
            order=['full','oracle'];rng('cost-order',CASE,repeat).shuffle(order)
            for which in order:
                out=root/f'{repeat}-{which}.json'
                process=execute([sys.executable,'-m','industrial.small_cost','method',str(root/'load'),
                    '--method',which,'--output',str(out)])
                record=dict(method=which,repeat=repeat,warmup=repeat==0,process=process,status=process['status'])
                if process['status']=='OK':record['measurement']=read_json(out)
                attempts.append(record)
                write_json(root/'progress.json',dict(case=CASE,attempts=attempts,preparation=prep))
    matched=[];mismatches=[];summary={}
    for repeat in range(1,6):
        rows=[r for r in attempts if r['repeat']==repeat]
        if len(rows)==2 and all(r['status']=='OK' for r in rows):
            a,b=[next(r for r in rows if r['method']==m) for m in ('full','oracle')]
            if a['measurement']['signature']!=b['measurement']['signature']:mismatches.append(repeat)
            else:matched.append(dict(repeat=repeat,ratio_first_to_second=a['process']['wall_s']/b['process']['wall_s']))
    for which in ('full','oracle'):
        good=[r for r in attempts if r['method']==which and not r['warmup'] and r['status']=='OK']
        def median(key):return statistics.median(r['measurement'][key] for r in good) if len(good)==5 else None
        walls=[r['process']['wall_s'] for r in good]
        summary[which]=dict(required=5,completed=len(good),completion_fraction=len(good)/5,
            timeouts=sum(r['status']=='TIMEOUT' for r in attempts if r['method']==which and not r['warmup']),
            median_wall_s=statistics.median(walls) if len(walls)==5 else None,
            median_completed_only_diagnostic_s=statistics.median(walls) if walls else None,
            median_cpu_s=median('cpu_s'),median_peak_rss_bytes=median('peak_rss_bytes'),
            median_representation_bytes=median('representation_bytes'))
    complete=len(attempts)==12 and all(r['status']=='OK' for r in attempts) and len(matched)==5
    write_json(root/'measurement.json',dict(case=CASE,condition='E3-seven-all-fibers',
        status='COMPLETE' if complete else 'PARTIAL',analysis_source_sha256=digest(Path('industrial/solver.py').read_bytes()),
        preparation=prep,shared_setup_s=setup_s,attempts=attempts,summary=summary,
        input_receipt=read_json(root/'load/input-receipt.json') if prep['status']=='OK' else None,
        paired_complete=matched,mismatched_repeats=mismatches,
        median_paired_ratio=statistics.median(r['ratio_first_to_second'] for r in matched) if len(matched)==5 else None,
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        costs_include='fresh-process startup, read and all thirteen scalar bounds; identical saved input; no images or witnesses'))


if __name__=='__main__':
    actions_only();p=argparse.ArgumentParser();p.add_argument('task',choices=['prepare','method'])
    p.add_argument('folder');p.add_argument('--method');p.add_argument('--output');a=p.parse_args()
    if a.task=='prepare':prepare(a.folder)
    else:method(a.folder,a.method,a.output)
