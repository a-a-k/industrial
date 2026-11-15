"""Exact-byte qualification of cached replay-log serialization on Actions."""
import ast
import base64
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
from .common import actions_only,canonical,digest,execute,read_json,write_json
from .measurement import prepare,run_method
from .releases import fetch


OLD_COMMIT='bcff4acdd0cffb789f1e61d120512eb334d0684a'
OLD_BLOB='a2b0fb25231b1661537990b1292dcd40c2c7eb4e'


def load_reference(path):
    spec=importlib.util.spec_from_file_location('industrial.reference_measurement',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def run(registry):
    root=Path('output/preparation-revision');root.mkdir(parents=True,exist_ok=True)
    api=f'repos/{os.environ["GITHUB_REPOSITORY"]}/contents/industrial/measurement.py?ref={OLD_COMMIT}'
    payload=json.loads(subprocess.check_output(['gh','api',api],text=True))
    if payload['sha']!=OLD_BLOB:raise ValueError('unexpected reference measurement source')
    old=base64.b64decode(payload['content']);reference=root/'reference_measurement.py';reference.write_bytes(old)
    parsed_old=ast.parse(old.decode());parsed_new=ast.parse(Path('industrial/measurement.py').read_text())
    function=lambda tree,name:next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    normalize=lambda node:ast.dump(ast.Module(body=[node],type_ignores=[]),include_attributes=False)
    old_method=normalize(function(parsed_old,'run_method'));new_method=normalize(function(parsed_new,'run_method'))
    if old_method!=new_method:raise ValueError('timed method changed during preparation revision')
    imports=lambda tree:[ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
    if imports(parsed_old)!=imports(parsed_new):raise ValueError('timed module imports changed')
    qualified,_=fetch(registry['qualification'],'output/preparation-core-qualification')
    qualification=read_json(qualified/'qualification.json')
    if qualification['status']!='CORE_PASS':raise ValueError('core qualification unavailable')
    for name,sha in qualification['implementation'].items():
        if digest(Path(name).read_bytes())!=sha:raise ValueError('protected implementation changed: '+name)
    observations={};checks=[]
    for index,tag in enumerate(registry['references']):
        measured,_=fetch(tag,f'output/preparation-reference-{index}');m=read_json(measured/'measurement.json')
        obs_tag=m['observation_release']
        if obs_tag not in observations:
            folder,_=fetch(obs_tag,f'output/preparation-observations-{len(observations)}')
            observations[obs_tag]=folder
        folder=observations[obs_tag];source=read_json(folder/'index.json')
        condition,mode,count_text,_,_=m['case'].split(':');count=int(count_text)
        if condition!=source['condition']:raise ValueError('reference observation condition differs')
        entry=next(e for e in source['cases'] if e['deadline_label']=='110' and e['mode']==mode)
        packet=folder/entry['file']
        if digest(packet.read_bytes())!=m['load']['parent_packet_sha256']:raise ValueError('reference parent differs')
        expected=read_json(measured/'load/log-receipt.json');out=root/f'control-{index}'
        process=execute([sys.executable,'-m','industrial.measurement','prepare',str(packet),str(out),'--count',str(count)])
        row=dict(reference=tag,case=m['case'],process=process,status='UNAVAILABLE')
        if process['status']=='OK':
            actual=digest((out/'log.jsonl.gz').read_bytes());row.update(expected_sha256=expected['sha256'],actual_sha256=actual,
                bytes=(out/'log.jsonl.gz').stat().st_size,status='PASS' if actual==expected['sha256'] else 'FAIL')
            if (out/'contract.json').read_bytes()!=(measured/'load/contract.json').read_bytes():row['status']='FAIL'
            (out/'log.jsonl.gz').unlink()
        checks.append(row);write_json(root/'progress.json',dict(checks=checks))
    marker='__industrial_load_identifier__'
    packet=root/'collision-packet.json'
    write_json(packet,dict(contract=dict(id='collision'),attempts=[dict(id=marker,note=marker+'_'),dict(id=marker+'_',note=marker)],
        records=[dict(attempt=marker,record_id=marker),dict(attempt=marker+'_',record_id=marker+'_')]))
    old_dir=root/'collision-old';new_dir=root/'collision-new'
    legacy=execute([sys.executable,'-m','industrial.preparation_revision','legacy',str(reference),str(packet),str(old_dir),'513'])
    revised=execute([sys.executable,'-m','industrial.measurement','prepare',str(packet),str(new_dir),'--count','513'])
    collision=dict(old_process=legacy,new_process=revised,status='UNAVAILABLE')
    if legacy['status']==revised['status']=='OK':
        a=digest((old_dir/'log.jsonl.gz').read_bytes());b=digest((new_dir/'log.jsonl.gz').read_bytes())
        collision.update(old_sha256=a,new_sha256=b,status='PASS' if a==b else 'FAIL')
    status='PASS' if len(checks)==4 and all(c['status']=='PASS' for c in checks) and collision['status']=='PASS' else 'FAIL'
    write_json(root/'qualification.json',dict(status=status,old_commit=OLD_COMMIT,old_blob=OLD_BLOB,
        prepare_source_sha256=digest(inspect.getsource(prepare).encode()),method_ast_sha256=digest(new_method.encode()),
        method_and_imports_unchanged=True,protected_implementation=qualification['implementation'],
        exact_byte_controls=checks,marker_collision=collision,process_timeout_s=300,
        monetary_budget=0,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))
    if status!='PASS':raise SystemExit('Preparation equivalence qualification failed')


if __name__=='__main__':
    actions_only()
    if sys.argv[1]=='legacy':load_reference(sys.argv[2]).prepare(sys.argv[3],sys.argv[4],int(sys.argv[5]))
    else:run(read_json(sys.argv[1]))
