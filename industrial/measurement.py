"""Paired fresh-process measurements with equal inputs and censored failures."""
import argparse
from collections import defaultdict
import gc
import gzip
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time
from .common import actions_only,canonical,digest,execute,read_json,read_rows,rng,write_json,write_rows


def prepare(packet_path,folder,count):
    from .binding import schema
    packet=read_json(packet_path);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    records=defaultdict(list)
    for r in packet['records']:records[r['attempt']].append(r)
    attempts=packet['attempts'];n=len(attempts);started=time.perf_counter()
    def rows():
        for index in range(count):
            source=attempts[index%n];aid=f'load:{index:06d}'
            yield dict(attempt=dict(source,id=aid,source_attempt=source['id']),
                       records=[dict(r,attempt=aid) for r in records[source['id']]])
    write_json(folder/'contract.json',packet['contract']);write_rows(folder/'log.jsonl.gz',rows())
    write_json(folder/'load.json',dict(attempts=count,unique_production_attempts=min(count,n),
        preparation_s=time.perf_counter()-started,log_bytes=(folder/'log.jsonl.gz').stat().st_size,
        parent_packet_sha256=digest(Path(packet_path).read_bytes()),statistical_sample_size_increased=False))


def run_method(folder,method,query,deadline,result_path,saved=None):
    from .targets import direct,query_reduced,query_full_r,project_full,conjunction,AGGREGATE
    started=time.perf_counter();phases={};result_path=Path(result_path);result_path.parent.mkdir(parents=True,exist_ok=True)
    def progress(stage):write_json(str(result_path)+'.progress.json',dict(stage=stage,elapsed_s=time.perf_counter()-started))
    progress('input')
    if query=='saved_R':
        source=read_json(Path(saved)/('model.json.gz' if method=='full' else 'reduced.json'))
        phases['read_s']=time.perf_counter()-started;answer=None;samples=[]
        for index in range(10):
            begin=time.perf_counter();value=query_full_r(source) if method=='full' else query_reduced(source)
            samples.append(time.perf_counter()-begin)
            if answer is not None and answer!=value:raise ValueError('saved query is not stable')
            answer=value
        estimates={'R':answer};representation=Path(saved)/('model.json.gz' if method=='full' else 'reduced.json')
        phases['queries_s']=samples
    else:
        from .binding import bind,direct_rows,schema,ckey
        from .model import identify
        folder=Path(folder);contract=read_json(folder/'contract.json')
        if method=='direct':
            cs=['C_dispatch']+[ckey(j) for j in contract['jobs']]
            def observations():
                for item in read_rows(folder/'log.jsonl.gz'):
                    yield from direct_rows(contract,[item['attempt']],item['records'],deadline)
            model=direct(observations(),cs)
        else:
            proto=schema(contract);cs=proto['completion_signals']
            original_proto=proto
            if method=='combination':
                controls=[k for k in proto['signal_ids'] if k not in cs]
                proto=dict(proto,signal_ids=controls+[AGGREGATE],completion_signals=[AGGREGATE],
                    entry_completion_signal=AGGREGATE,required_edge_completions=[dict(edge_id=r['edge_id'],signal=AGGREGATE)
                        for r in proto['required_edge_completions']])
            def observations():
                for item in read_rows(folder/'log.jsonl.gz'):
                    _,rows,_=bind(contract,[item['attempt']],item['records'],deadline,state_schema=original_proto)
                    row=rows[0]
                    if method=='combination':yield dict({k:row[k] for k in controls},**{AGGREGATE:conjunction(row[k] for k in cs)})
                    else:yield row
            model=identify(proto,observations())
            if method=='projection':model=project_full(model)
        constructed=time.perf_counter();phases['parse_bind_build_s']=constructed-started;progress('serialization')
        representation=Path(str(result_path)+'.model.json.gz');write_json(representation,model)
        stored=time.perf_counter();phases['serialize_s']=stored-constructed;progress('query')
        if query=='R':
            value=query_full_r(model) if method=='full' else query_reduced(model)
            estimates={'R':value}
        elif query=='panel':
            from .solver import Compiled
            compiled=Compiled(model);phases['compile_s']=compiled.build_seconds
            estimates=compiled.solve()['estimates']
        else:raise ValueError('unknown cost query')
        phases['analysis_s']=time.perf_counter()-stored
    report=dict(status='OK',method=method,query=query,estimates=estimates,
        signature=digest(canonical(estimates)),phases=phases,wall_internal_s=time.perf_counter()-started,
        cpu_s=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        representation_bytes=representation.stat().st_size)
    write_json(result_path,report)


def paired(case,observation_tag,fit_tag):
    from .releases import fetch
    condition,mode,load_text,query,pair=case.split(':');count=int(load_text);methods=pair.split('-')
    spec=read_json('provenance/measurements.json')
    if condition not in spec['conditions'] or mode not in spec['observation_modes']:
        raise ValueError('undeclared measurement condition')
    if query=='saved_R':
        if count!=512 or methods not in spec['saved_R_pairs']:raise ValueError('undeclared saved-model case')
    elif query not in spec['pairs'] or count not in spec['loads'] or methods not in spec['pairs'][query]:
        raise ValueError('undeclared measurement pair or load')
    if len(methods)!=2:raise ValueError('cost case must be paired')
    root=Path('output/measurement');root.mkdir(parents=True,exist_ok=True);setup=time.perf_counter()
    observations,_=fetch(observation_tag,'output/input-cost-observations');index=read_json(observations/'index.json')
    if index['condition']!=condition or index['split']!='calibration':raise ValueError('cost input condition')
    entries=[x for x in index['cases'] if x['deadline_label']=='110' and x['mode']==mode]
    if len(entries)!=1:raise ValueError('cost packet not found')
    entry=entries[0];saved=None;prep=None
    if query=='saved_R':
        fitroot,_=fetch(fit_tag,'output/input-cost-fit');saved=fitroot/f'110-{mode}'
        prep=dict(status='SAVED_MODEL',source_fit=fit_tag)
    else:
        prep=execute([sys.executable,'-m','industrial.measurement','prepare',str(observations/entry['file']),
            str(root/'load'),'--count',str(count)])
    setup_s=time.perf_counter()-setup;attempts=[];deadline=entry['deadline'];start=time.monotonic()
    if prep['status'] in ('OK','SAVED_MODEL'):
        for repeat in range(6):
            order=list(methods);rng('cost-order',case,repeat).shuffle(order)
            for method in order:
                if time.monotonic()-start>80*60:
                    attempts.append(dict(method=method,repeat=repeat,warmup=repeat==0,status='JOB_BUDGET_UNRUN'));continue
                out=root/f'{repeat}-{method}.json'
                command=[sys.executable,'-m','industrial.measurement','method',str(root/'load'),str(out),
                    '--method',method,'--query',query,'--deadline',str(deadline)]
                if saved is not None:command+=['--saved',str(saved)]
                process=execute(command)
                row=dict(method=method,repeat=repeat,warmup=repeat==0,process=process,status=process['status'])
                if process['status']=='OK':row['measurement']=read_json(out)
                attempts.append(row)
                write_json(root/'progress.json',dict(case=case,attempts=attempts,preparation=prep))
    matched=[];mismatches=[]
    for repeat in range(1,6):
        rows=[r for r in attempts if r['repeat']==repeat]
        if len(rows)==2 and all(r['status']=='OK' for r in rows):
            a,b=[next(r for r in rows if r['method']==m) for m in methods]
            if a['measurement']['signature']!=b['measurement']['signature']:
                mismatches.append(repeat)
            else:matched.append(dict(repeat=repeat,ratio_first_to_second=a['process']['wall_s']/b['process']['wall_s']))
    complete=prep['status'] in ('OK','SAVED_MODEL') and len(attempts)==12 and all(r['status']=='OK' for r in attempts) and not mismatches
    summary={}
    for method in methods:
        rows=[r for r in attempts if r['method']==method and not r['warmup']]
        good=[r for r in rows if r['status']=='OK']
        summary[method]=dict(required=5,completed=len(good),timeouts=sum(r['status']=='TIMEOUT' for r in rows),
            median_wall_s=statistics.median(r['process']['wall_s'] for r in good) if len(good)==5 else None,
            median_completed_only_diagnostic_s=statistics.median(r['process']['wall_s'] for r in good) if good else None)
    write_json(root/'measurement.json',dict(case=case,status='COMPLETE' if complete else 'PARTIAL',condition=condition,
        observation_release=observation_tag,fit_release=fit_tag,preparation=prep,shared_setup_s=setup_s,
        load=read_json(root/'load/load.json') if (root/'load/load.json').exists() else None,
        attempts=attempts,summary=summary,paired_complete=matched,mismatched_repeats=mismatches,
        median_paired_ratio=statistics.median(r['ratio_first_to_second'] for r in matched) if len(matched)==5 else None,
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        costs_include='fresh-process startup, parse, binding, construction, save and query; warmups separate and retained'))
    # The replay log is reconstructible from the retained original packet and exact load rule.
    # Preserve its hash and preparation cost instead of uploading duplicated production data.
    log=root/'load/log.jsonl.gz'
    if log.exists():
        write_json(root/'load/log-receipt.json',dict(bytes=log.stat().st_size,sha256=digest(log.read_bytes()),
            reconstruction='prepare parent packet, cycle journal order, unique load:index IDs'))
        log.unlink()


def main():
    actions_only();p=argparse.ArgumentParser();sub=p.add_subparsers(dest='task',required=True)
    s=sub.add_parser('prepare');s.add_argument('packet');s.add_argument('folder');s.add_argument('--count',type=int,required=True)
    s=sub.add_parser('method');s.add_argument('folder');s.add_argument('output');s.add_argument('--method',required=True)
    s.add_argument('--query',required=True);s.add_argument('--deadline',type=int,required=True);s.add_argument('--saved')
    s=sub.add_parser('paired');s.add_argument('--case',required=True);s.add_argument('--observations',required=True);s.add_argument('--fit',default='')
    a=p.parse_args()
    if a.task=='prepare':prepare(a.packet,a.folder,a.count)
    elif a.task=='method':run_method(a.folder,a.method,a.query,a.deadline,a.output,a.saved)
    else:paired(a.case,a.observations,a.fit)


if __name__=='__main__':main()
