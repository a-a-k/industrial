"""Uniform old/new analysis verification before validation outcomes are opened."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import urllib.request
from .common import actions_only,canonical,digest,execute,read_json,write_json
from .releases import fetch


def run(registry):
    manifest=read_json('provenance/analysis_compatibility.json')
    root=Path('output/analysis-revision');root.mkdir(parents=True,exist_ok=True)
    request=urllib.request.Request(
        f'https://api.github.com/repos/{os.environ["GITHUB_REPOSITORY"]}/contents/industrial/solver.py?ref={manifest["old_commit"]}',
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=60) as response:source=base64.b64decode(json.load(response)['content'])
    if digest(source)!=manifest['old_sha256']:raise ValueError('old analysis source checksum mismatch')
    old_file=root/'reference_solver_v1.py';old_file.write_bytes(source)
    spec=importlib.util.spec_from_file_location('industrial.reference_solver_v1',old_file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    old_cases={};retained=[];unavailable=[]
    for index,tag in enumerate(registry['old_fits']):
        try:folder,receipt=fetch(tag,f'output/revision-old-{index}')
        except Exception as error:
            unavailable.append(dict(release=tag,error=str(error)));continue
        parts=receipt['name'].split('-');condition=parts[1]+'-'+parts[2]
        paths=list(folder.rglob('result.json'));complete=0;incomplete=[]
        for path in paths:
            try:value=read_json(path)
            except Exception as error:
                incomplete.append(dict(path=str(path.relative_to(folder)),error=str(error)));continue
            if value.get('status')=='PASS':old_cases[(condition,path.parent.name)]=value;complete+=1
        retained.append(dict(release=tag,completed_case_records=complete,incomplete_case_records=incomplete,
                             aggregate_report_present=(folder/'fit.json').exists()))
    comparisons=[];retained_comparisons=[];new_reports={}
    for index,tag in enumerate(registry['new_fits']):
        folder,receipt=fetch(tag,f'output/revision-new-{index}');report=read_json(folder/'fit.json')
        if report['status']!='PASS' or report['role']!='calibration_forecast':
            raise ValueError('uniform new calibration analysis incomplete')
        condition=report['condition'];new_reports[condition]=report
        compiled=None
        for result in report['results']:
            case=result['case'];model=read_json(folder/case/'model.json.gz')
            if compiled is None:compiled=module.Compiled(model)
            else:
                previous=compiled.model
                for name in ('graph','replicas','operation','demand_controls','required_edge_completions','signal_ids',
                             'completion_signals','entry_completion_signal','timely_signal'):
                    if previous[name]!=model[name]:raise ValueError('semantic schema changed across cases')
                compiled.model=model
            reference=compiled.solve(witnesses=False)['estimates']
            if reference!=result['estimates']:raise ValueError('old/new exact extrema mismatch')
            comparisons.append(dict(condition=condition,case=case,status='EQUAL',samples=model['sample_count']))
            key=(condition,case)
            if key in old_cases:
                old=old_cases[key]
                if (old['estimates']!=result['estimates'] or old['full_R']!=result['full_R']
                        or old['model_sha256']!=result['model_sha256'] or old['input_sha256']!=result['input_sha256']):
                    raise ValueError('retained old case differs in model, input or prediction')
                retained_comparisons.append(dict(condition=condition,case=case,status='EQUAL'))
        del compiled
    if len(new_reports)!=20 or len(comparisons)!=300 or len(retained_comparisons)!=len(old_cases):
        raise ValueError('incomplete uniform scalar equivalence census')
    preflight,_=fetch(registry['preflight'],'output/revision-preflight');maxima=[]
    for item in read_json(preflight/'preflight.json')['instances']:
        instance=item['instance'];result_path=root/f'{instance}-maximum.json'
        process=execute([sys.executable,'-m','industrial.worker','feasibility',
            str(preflight/instance/'maximum-fiber.json'),str(result_path)])
        if process['status']!='OK':raise ValueError('new industrial-schema feasibility unavailable')
        result=read_json(result_path)
        if result['estimates']!=item['feasibility']['estimates']:
            raise ValueError('old/new maximum-schema extrema mismatch')
        maxima.append(dict(instance=instance,status='PASS',coordinates=result['coordinates'],process=process,
                          verification=result['verification']))
    write_json(root/'revision.json',dict(status='PASS',old_sha256=manifest['old_sha256'],
        new_sha256=manifest['new_sha256'],qualification=manifest['qualification'],
        old_source_commit=manifest['old_commit'],new_fits=registry['new_fits'],old_fits=registry['old_fits'],
        exact_scalar_comparisons=comparisons,retained_old_comparisons=retained_comparisons,
        retained_old_releases=retained,old_release_unavailable=unavailable,maximum_schemas=maxima,
        family_unchanged=True,bindings_unchanged=True,retained_model_and_input_hashes_unchanged=True,
        validation_opened=False,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))


if __name__=='__main__':
    actions_only();p=argparse.ArgumentParser();p.add_argument('registry');a=p.parse_args();run(read_json(a.registry))
