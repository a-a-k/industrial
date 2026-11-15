"""Sealed forecast evaluation using independent finished-product accounting."""
import argparse
import csv
import datetime as dt
import os
from pathlib import Path
from .common import actions_only,canonical,digest,read_json,write_json
from .production import outcomes
from .releases import fetch
from .statistics import forecast_metrics


CONDITIONS=[f'Mk{i:02d}-F{law}' for i in range(1,11) for law in (1,2)]


def seal(tags,revision_tag=None):
    root=Path('output/seal');root.mkdir(parents=True,exist_ok=True);entries={}
    if Path('provenance/analysis_compatibility.json').exists():
        if not revision_tag:raise ValueError('analysis replacement requires complete equivalence audit before sealing')
        revised,_=fetch(revision_tag,'output/seal-analysis-revision');revision=read_json(revised/'revision.json')
        if revision['status']!='PASS' or set(revision['new_fits'])!=set(tags):
            raise ValueError('analysis replacement verification does not cover these forecasts')
    for index,tag in enumerate(tags):
        source,receipt=fetch(tag,f'output/seal-input-{index}')
        report=read_json(source/'fit.json');condition=report['condition']
        if report['role']!='calibration_forecast' or report['observations']['split']!='calibration':
            raise ValueError('only calibration forecasts can be sealed')
        if condition in entries:raise ValueError('duplicate sealed condition')
        entries[condition]=dict(release=tag,status=report['status'],
            report_sha256=digest(canonical(report)),
            cases=[dict(case=r['case'],status=r['status'],estimates=r.get('estimates')) for r in report['results']])
    if set(entries)!=set(CONDITIONS):raise ValueError('all twenty conditions must be represented before validation')
    write_json(root/'seal.json',dict(status='SEALED',conditions=entries,
        analysis_revision=revision_tag,
        complete_predictions=all(v['status']=='PASS' for v in entries.values()),
        sealed_at=dt.datetime.now(dt.timezone.utc).isoformat(),commit=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],selection_after_validation=False))


def evaluate(registry):
    root=Path('output/evaluation');root.mkdir(parents=True,exist_ok=True)
    sealed,_=fetch(registry['seal'],'output/evaluation-seal');seal_record=read_json(sealed/'seal.json')
    fits={};banks={};reanalyses={};all_banks=[]
    for index,tag in enumerate(registry['fits']):
        folder,_=fetch(tag,f'output/evaluation-fit-{index}');report=read_json(folder/'fit.json')
        if report['role']!='calibration_forecast':raise ValueError('descriptive model used as forecast')
        condition=report['condition']
        if digest(canonical(report))!=seal_record['conditions'][condition]['report_sha256']:
            raise ValueError('forecast changed after sealing')
        fits[condition]=report
    for index,tag in enumerate(registry['banks']):
        folder,_=fetch(tag,f'output/evaluation-bank-{index}');report=read_json(folder/'bank.json')
        ledger=read_json(folder/'product-ledger.json.gz');data=read_json(folder/'dataset.json')
        banks[(report['condition'],report['split'])]=(report,ledger,data);all_banks.append(dict(release=tag,**report))
    for index,tag in enumerate(registry.get('reanalyses',[])):
        folder,_=fetch(tag,f'output/evaluation-reanalysis-{index}');report=read_json(folder/'fit.json')
        if report['role']!='validation_descriptive_reanalysis':raise ValueError('wrong descriptive analysis role')
        reanalyses[report['condition']]=report
    rows=[];calibration_checks=[];unavailable=[]
    for condition in CONDITIONS:
        if condition not in fits or (condition,'calibration') not in banks or (condition,'validation') not in banks:
            unavailable.append(dict(condition=condition,reason='missing required acquisition or forecast'));continue
        own=fits[condition]
        for split in ('calibration','validation'):
            report,ledger,data=banks[(condition,split)]
            if split=='validation' and report['prediction_seal']!=registry['seal']:
                raise ValueError('validation did not use this forecast seal')
        cal_report,cal_ledger,data=banks[(condition,'calibration')]
        val_report,val_ledger,_=banks[(condition,'validation')]
        jobs=[j['id'] for j in data['jobs'] if not j.get('optional',False)]
        for label,mult in (('100',(1,1)),('110',(11,10)),('125',(5,4))):
            d=data['nominal_makespan']*mult[0]//mult[1]
            cal_y=outcomes(cal_ledger,jobs,d);test_y=outcomes(val_ledger,jobs,d)
            known_cal=all(v is not None for v in cal_y.values()) and len(cal_y)==512
            known_test=all(v is not None for v in test_y.values()) and len(test_y)==1024
            actual=sum(v is True for v in cal_y.values())/512 if known_cal else None
            available=next(r for r in own['results'] if r['case']==label+'-available')
            if known_cal and available['status']=='PASS':
                e=available['estimates']['execution'];r=available['estimates']['R']
                ok=e['lower']==e['upper']==r['lower']==r['upper']==actual
                calibration_checks.append(dict(condition=condition,deadline=label,status='PASS' if ok else 'FAIL',
                    model_e=[e['lower'],e['upper']],model_r=[r['lower'],r['upper']],external_frequency=actual))
            candidates=[('same_regime',condition)]
            if condition.endswith('F2'):candidates.append(('frozen_F1_to_F2',condition[:-2]+'F1'))
            for regime,source_condition in candidates:
                source=fits.get(source_condition)
                if source is None:continue
                source_bank=banks.get((source_condition,'calibration'))
                source_frequency=None
                if source_bank is not None:
                    source_labels=outcomes(source_bank[1],jobs,d)
                    if len(source_labels)==512 and all(v is not None for v in source_labels.values()):
                        source_frequency=sum(source_labels.values())/512
                for result in source['results']:
                    if result['deadline_label']!=label:continue
                    for target in ('execution','R'):
                        base=dict(condition=condition,source_condition=source_condition,regime=regime,
                            mode=result['mode'],deadline_label=label,target=target,source_fit=seal_record['conditions'][source_condition]['release'])
                        if result['status']!='PASS' or not known_test:
                            rows.append(dict(base,status='UNAVAILABLE',reason='missing fitted result or independent outcomes'));continue
                        metrics=forecast_metrics(result['estimates'][target],sum(test_y.values()),1024)
                        baseline=None
                        if source_frequency is not None:
                            k=sum(source_labels.values())
                            baseline=forecast_metrics(dict(guaranteed=k,possible=k,samples=512,
                                lower=k/512,upper=k/512),sum(test_y.values()),1024)
                        rows.append(dict(base,status='OK',**metrics,calibration_success_frequency=source_frequency,
                            calibration_frequency_metrics=baseline,
                            calibration_frequency_role='external comparator; not an identifier input'))
    required_banks=len(all_banks)==40 and all(r['status']=='COMPLETE' for r in all_banks)
    required_fits=len(fits)==20 and all(r['status']=='PASS' for r in fits.values())
    required_reanalysis=len(reanalyses)==20 and all(r['status']=='PASS' for r in reanalyses.values())
    valid_checks=len(calibration_checks)==60 and all(r['status']=='PASS' for r in calibration_checks)
    complete_rows=len(rows)==900 and all(r['status']=='OK' for r in rows)
    status='PASS' if required_banks and required_fits and required_reanalysis and valid_checks and complete_rows and not unavailable else 'PARTIAL'
    report=dict(status=status,seal=registry['seal'],forecasts=rows,calibration_checks=calibration_checks,
        banks=all_banks,fit_statuses={k:v['status'] for k,v in fits.items()},
        validation_reanalysis_statuses={k:v['status'] for k,v in reanalyses.items()},unavailable=unavailable,
        completed_forecast_rows=sum(r['status']=='OK' for r in rows),
        required_forecast_rows=10*3*5*2*3,
        confidence_scope='per condition only; batch replication is the unit',
        population_improvement_claimed=False,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'evaluation.json',report)
    fields=['condition','source_condition','regime','mode','deadline_label','target','status','validation_frequency',
            'signed_error','absolute_error','prediction_width','distance_to_frequency']
    with (root/'forecasts.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)


def main():
    actions_only();p=argparse.ArgumentParser();p.add_argument('task',choices=['seal','evaluate']);p.add_argument('registry')
    a=p.parse_args();registry=read_json(a.registry)
    if a.task=='seal':seal(registry['fits'],registry.get('analysis_revision'))
    else:evaluate(registry)


if __name__=='__main__':main()
