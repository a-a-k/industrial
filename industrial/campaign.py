"""Finite E5 acquisition and isolated calibration tasks with complete censuses."""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import re
import sys
import time
from .binding import schema,fit,mask
from .common import actions_only,canonical,digest,execute,read_json,write_json,write_rows
from .inputs import dataset,contract,scenarios
from .model import identify
from .production import simulate,export_observations,product_ledger,outcomes,check_physics,compare
from .releases import fetch

MODES=('available','mcar10','mcar30','informative','trace_loss')
DEADLINES=('100','110','125')


def deadlines(data):
    c0=data['nominal_makespan']
    return {'100':c0,'110':11*c0//10,'125':5*c0//4}


def check_qualification(root):
    q=read_json(Path(root)/'qualification.json')
    if q['status']!='CORE_PASS':raise ValueError('core qualification not passed')
    for name,expected in q['implementation'].items():
        if digest(Path(name).read_bytes())!=expected:raise ValueError('qualified implementation changed: '+name)
    return q


def preflight(qualification_tag):
    qroot,receipt=fetch(qualification_tag,'output/input-qualification');q=check_qualification(qroot)
    root=Path('output/preflight');root.mkdir(parents=True,exist_ok=True);entries=[]
    import shutil
    (root/'provenance').mkdir(exist_ok=True)
    shutil.copyfile('build/tsfg-provenance.json',root/'provenance/tsfg-provenance.json')
    for index in range(1,11):
        instance=f'Mk{index:02d}';data=dataset(instance,root/'sources');folder=root/instance;folder.mkdir()
        write_json(folder/'dataset.json',data);con=contract(data);proto=schema(con)
        write_json(folder/'contract.json',con);write_json(folder/'state-schema.json',proto)
        nominal=[dict(id=f'{instance}-nominal',failures=[],work_overrides=[])]
        engine_rows=[];processes=[]
        for engine in ('des','dag','tsfg'):
            rows,proc=simulate(data,nominal,folder/engine,engine,deadlines(data)['125'])
            processes+=proc
            if nominal[0]['id'] not in rows:raise ValueError('nominal trajectory unavailable')
            trajectory=rows[nominal[0]['id']];check_physics(data,nominal[0],trajectory)
            if trajectory['cmax']!=data['nominal_makespan']:raise ValueError('nominal schedule/makespan mismatch')
            engine_rows.append(trajectory)
        compare(engine_rows[0],engine_rows[1]);compare(engine_rows[0],engine_rows[2])
        unknown=identify(proto,[dict.fromkeys(proto['signal_ids'])]);write_json(folder/'maximum-fiber.json',unknown)
        process=execute([sys.executable,'-m','industrial.worker','feasibility',str(folder/'maximum-fiber.json'),str(folder/'feasibility.json')])
        if process['status']!='OK':
            write_json(folder/'feasibility-process.json',process);raise ValueError('industrial-schema qualification unavailable')
        entries.append(dict(instance=instance,jobs=len(data['jobs']),operations=len(data['operations']),
            machines=len(data['queues']),coordinates=len(proto['signal_ids']),nominal_makespan=data['nominal_makespan'],
            schema_sha256=digest(canonical(proto)),dataset_sha256=digest(canonical(data)),
            feasibility=read_json(folder/'feasibility.json'),nominal_processes=processes))
    write_json(root/'preflight.json',dict(status='PASS',core_qualification=qualification_tag,
        qualification_commit=q['commit'],freeze_commit=os.environ['GITHUB_SHA'],instances=entries,
        holdout='Mk08-Mk10 first opened after algorithm qualification',
        E4_production_acceptance='pending first required Mk01-F1 calibration bank'))


def acquire(preflight_tag,condition,split,seal_tag=None,binding_gate=None):
    if not re.fullmatch(r'Mk(0[1-9]|10)-F[12]',condition):raise ValueError('invalid condition')
    instance,law=condition.split('-');pref,_=fetch(preflight_tag,'output/input-preflight')
    metadata=read_json(pref/'preflight.json')
    if metadata['status']!='PASS':raise ValueError('preflight not passed')
    qroot,_=fetch(metadata['core_qualification'],'output/input-qualification');qualified=check_qualification(qroot)
    if split=='calibration' and condition!='Mk01-F1':
        if not binding_gate:raise ValueError('remaining calibration requires first-bank E4 acceptance')
        gate,_=fetch(binding_gate,'output/input-binding-gate');accepted=read_json(gate/'fit.json')
        if (accepted['condition']!='Mk01-F1' or accepted['status']!='PASS' or len(accepted['refinement_deadlines'])!=3
                or accepted['observations']['bank_status']!='COMPLETE'):
            raise ValueError('first required calibration bank did not pass E4 and isolated identification')
    if split=='validation':
        if not seal_tag:raise ValueError('validation requires immutable prediction seal')
        seal,_=fetch(seal_tag,'output/input-seal')
        sealed=read_json(seal/'seal.json')
        if sealed['status']!='SEALED' or condition not in sealed['conditions']:
            raise ValueError('condition not sealed before validation acquisition')
    elif split!='calibration':raise ValueError('invalid split')
    data=read_json(pref/instance/'dataset.json');h=deadlines(data)['125']
    count=512 if split=='calibration' else 1024
    bank=Path('output/bank');obs=Path('output/observations');bank.mkdir(parents=True,exist_ok=True);obs.mkdir()
    started=time.perf_counter();sc=scenarios(data,law,split,count)
    write_json(bank/'dataset.json',data);write_json(bank/'scenarios.json.gz',sc)
    des,dp=simulate(data,sc,bank/'des','des',h);dag,gp=simulate(data,sc,bank/'dag','dag',h)
    mismatches=[]
    for scenario in sc:
        aid=scenario['id']
        try:
            if aid in des:check_physics(data,scenario,des[aid])
            if aid in dag:check_physics(data,scenario,dag[aid])
            if aid in des and aid in dag:compare(des[aid],dag[aid])
        except Exception as error:mismatches.append(dict(attempt=aid,error=str(error),comparison='DES-DAG'))
    processes=dp+gp;tsfg={};selected=[]
    if split=='validation':
        selected=sorted(sc,key=lambda s:digest(('TSFG-v1|'+s['id']).encode()))[:128]
        tsfg,tp=simulate(data,selected,bank/'tsfg','tsfg',h,chunk=16);processes+=tp
        for scenario in selected:
            aid=scenario['id']
            if aid not in des or aid not in tsfg:continue
            try:
                check_physics(data,scenario,tsfg[aid]);compare(des[aid],tsfg[aid])
            except Exception as error:mismatches.append(dict(attempt=aid,error=str(error),comparison='DES-TSFG'))
    packet=export_observations(data,sc,des,h);ledger=product_ledger(data,sc,des)
    write_json(bank/'product-ledger.json.gz',ledger)
    index=[]
    for label,d in deadlines(data).items():
        labels=outcomes(ledger,packet['contract']['jobs'],d)
        for mode in MODES:
            candidate=mask(packet,mode,labels)
            name=f'{label}-{mode}.json.gz';write_json(obs/name,candidate)
            index.append(dict(deadline_label=label,deadline=d,mode=mode,file=name,
                sha256=digest((obs/name).read_bytes()),attempts=count))
        if selected:
            ids={s['id'] for s in selected if s['id'] in des and s['id'] in tsfg}
            paired=[s for s in selected if s['id'] in ids]
            if paired:
                left=export_observations(data,paired,des,h);right=export_observations(data,paired,tsfg,h)
                if fit(left,d)[0]!=fit(right,d)[0]:
                    mismatches.append(dict(comparison='DES-TSFG-identification',deadline=d))
    status='COMPLETE' if len(des)==count and len(dag)==count and not mismatches and (split!='validation' or len(tsfg)==128) else 'PARTIAL'
    report=dict(status=status,condition=condition,split=split,registered=count,des_completed=len(des),dag_completed=len(dag),
        tsfg_required=128 if split=='validation' else 0,tsfg_completed=len(tsfg),tsfg_selected=[s['id'] for s in selected],
        mismatches=mismatches,processes=processes,preflight=preflight_tag,prediction_seal=seal_tag,
        generation_and_execution_wall_s=time.perf_counter()-started,
        failure_law=dict(up='exponential',repair='exponential',mean_up_before_rounding=2*data['nominal_makespan'],
            mean_repair_before_rounding=.1*data['nominal_makespan'],initially_up=True,delta=5,rounding='ceil each positive duration',
            F2_mixture='independent fair replication coin; shared-all or independent identical component calendars'),
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(bank/'bank.json',report)
    write_json(obs/'index.json',dict(condition=condition,split=split,preflight=preflight_tag,
        schema_sha256=digest(canonical(schema(packet['contract']))),cases=index,registered=count,
        permitted_inputs_only=True,implementation=qualified['implementation'],bank_status=status,
        bank_admission='INVALID' if mismatches else 'VALID'))
    if mismatches:raise SystemExit('Engine mismatches retained; bank cannot be accepted')


def fit_observations(observation_tag,validation_reanalysis=False):
    source,receipt=fetch(observation_tag,'output/input-observations');index=read_json(source/'index.json')
    expected='validation' if validation_reanalysis else 'calibration'
    if index['split']!=expected:raise ValueError('wrong sample split for analysis role')
    if index['bank_admission']!='VALID':raise ValueError('invalid production bank cannot identify a model')
    for name,expected in index['implementation'].items():
        if digest(Path(name).read_bytes())!=expected:raise ValueError('fixed identification implementation changed')
    root=Path('output/fit');root.mkdir(parents=True,exist_ok=True);reports=[];processes=[]
    allowed={r['file'] for r in index['cases']}|{'index.json','SHA256SUMS.json'}
    if {p.name for p in source.iterdir() if p.is_file()}!=allowed:raise ValueError('unexpected identification files')
    for case in index['cases']:
        inp=source/case['file']
        if digest(inp.read_bytes())!=case['sha256']:raise ValueError('observation checksum mismatch')
        label=case['deadline_label']+'-'+case['mode'];out=root/label
        process=execute([sys.executable,'-m','industrial.worker','fit',str(inp),str(out),'--deadline',str(case['deadline'])])
        process.update(case=label);processes.append(process)
        report=dict(case=label,mode=case['mode'],deadline_label=case['deadline_label'],status=process['status'])
        if process['status']=='OK':
            saved=read_json(out/'result.json');report.update(saved)
            replay=execute([sys.executable,'-m','industrial.worker','replay',str(out/'model.json.gz'),str(out/'replay.json')])
            if replay['status']!='OK' or read_json(out/'replay.json')['estimates']!=saved['estimates']:
                report['status']='REPLAY_FAILED'
            else:report['fresh_replay_equal']=True
        reports.append(report)
    refinement=[]
    for deadline in DEADLINES:
        cases={r['mode']:r for r in reports if r['deadline_label']==deadline}
        if all(cases[m]['status']=='PASS' for m in MODES):
            for name in cases['available']['estimates']:
                a,b,c=[cases[m]['estimates'][name] for m in ('available','mcar10','mcar30')]
                if not c['lower']<=b['lower']<=a['lower']<=a['upper']<=b['upper']<=c['upper']:
                    raise ValueError('nested information refinement failed')
                for mode in ('informative','trace_loss'):
                    other=cases[mode]['estimates'][name]
                    if not other['lower']<=a['lower']<=a['upper']<=other['upper']:
                        raise ValueError('available observations do not refine masked family')
            refinement.append(deadline)
    status='PASS' if all(r['status']=='PASS' for r in reports) and len(refinement)==3 else 'PARTIAL'
    write_json(root/'fit.json',dict(status=status,condition=index['condition'],observation_release=observation_tag,
        observations=index,results=reports,processes=processes,refinement_deadlines=refinement,
        role='validation_descriptive_reanalysis' if validation_reanalysis else 'calibration_forecast',
        external_outcomes_accessed=False,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))


def main():
    actions_only();p=argparse.ArgumentParser();sub=p.add_subparsers(dest='task',required=True)
    a=sub.add_parser('preflight');a.add_argument('--qualification',required=True)
    a=sub.add_parser('acquire');a.add_argument('--preflight',required=True);a.add_argument('--condition',required=True)
    a.add_argument('--split',choices=['calibration','validation'],required=True);a.add_argument('--seal')
    a.add_argument('--binding-gate')
    a=sub.add_parser('fit');a.add_argument('--observations',required=True)
    a.add_argument('--validation-reanalysis',action='store_true')
    a=p.parse_args()
    if a.task=='preflight':preflight(a.qualification)
    elif a.task=='acquire':acquire(a.preflight,a.condition,a.split,a.seal,a.binding_gate)
    else:fit_observations(a.observations,a.validation_reanalysis)


if __name__=='__main__':main()
