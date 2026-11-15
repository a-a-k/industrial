"""Bounded fresh-process analysis tasks for the campaign controller."""
import argparse
import gc
from pathlib import Path
import resource
import time
from .binding import fit,direct_rows
from .common import actions_only,read_json,write_json,digest,canonical
from .model import identify
from .oracle import verify_certificates
from .solver import Compiled,ANALYSIS_VERSION
from .targets import query_full_r,project_full,query_reduced,direct,collapsed,AGGREGATE,conjunction


def full_fit(packet,deadline,output):
    started=time.perf_counter();model,rows,audit=fit(packet,deadline);bound=time.perf_counter()
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    write_json(root/'model.json.gz',model);saved=time.perf_counter()
    compiled=Compiled(model);built=time.perf_counter()
    result=compiled.solve(witnesses=True);queried=time.perf_counter()
    verification=verify_certificates(model,result);verified=time.perf_counter()
    write_json(root/'certificates.json.gz',result);estimates=result['estimates'];del result,compiled;gc.collect()
    full=query_full_r(model);projected=project_full(model)
    reduced=direct(direct_rows(packet['contract'],packet['attempts'],packet['records'],deadline),model['completion_signals'])
    if full!=query_reduced(projected) or full!=query_reduced(reduced) or projected!=reduced:
        raise ValueError('full/projection/direct R mismatch')
    controls=[k for k in model['signal_ids'] if k not in model['completion_signals']]
    proto=dict(model,signal_ids=controls+[AGGREGATE],completion_signals=[AGGREGATE],entry_completion_signal=AGGREGATE,
        required_edge_completions=[dict(edge_id=r['edge_id'],signal=AGGREGATE) for r in model['required_edge_completions']])
    combo=identify(proto,(dict({k:r[k] for k in controls},**{AGGREGATE:conjunction(r[k] for k in model['completion_signals'])}) for r in rows))
    combo_result=Compiled(combo).solve()
    if combo_result['estimates']!=estimates:raise ValueError('combination baseline mismatch')
    write_json(root/'combination.json.gz',combo)
    write_json(root/'reduced.json',reduced)
    report=dict(status='PASS',analysis_version=ANALYSIS_VERSION,deadline=deadline,samples=model['sample_count'],coordinates=len(model['signal_ids']),
        categories=len(model['observation_categories']),estimates=estimates,full_R=full,
        input_sha256=digest(canonical(packet)),model_sha256=digest(canonical(model)),
        three_paths_equal=True,combination_equal=True,verification=verification,
        timings=dict(binding_s=bound-started,save_model_s=saved-bound,compile_s=built-saved,
                     query_with_witnesses_s=queried-built,verify_s=verified-queried,total_s=time.perf_counter()-started),
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    write_json(root/'result.json',report)


def main():
    actions_only();p=argparse.ArgumentParser();p.add_argument('task',choices=['fit','feasibility','replay'])
    p.add_argument('input');p.add_argument('output');p.add_argument('--deadline',type=int)
    a=p.parse_args();data=read_json(a.input)
    if a.task=='fit':full_fit(data,a.deadline,a.output)
    elif a.task=='replay':write_json(a.output,Compiled(data).solve())
    else:
        started=time.perf_counter();compiled=Compiled(data);result=compiled.solve(witnesses=True)
        verified=verify_certificates(data,result)
        write_json(a.output,dict(status='PASS',coordinates=len(data['signal_ids']),
            categories=len(data['observation_categories']),verification=verified,
            wall_s=time.perf_counter()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            estimates=result['estimates']))


if __name__=='__main__':main()
