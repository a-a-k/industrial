"""Post-seal per-attempt comparison with independent finished-product outcomes."""
from pathlib import Path
from .binding import fit,mask
from .common import canonical,digest,read_json,read_rows
from .production import export_observations,outcomes


def check(bank_folder,analysis_folder,analysis_report):
    bank_folder=Path(bank_folder);analysis_folder=Path(analysis_folder)
    data=read_json(bank_folder/'dataset.json');scenarios=read_json(bank_folder/'scenarios.json.gz')
    ledger=read_json(bank_folder/'product-ledger.json.gz')
    trajectories={}
    for path in (bank_folder/'des').glob('des-*.jsonl'):
        for row in read_rows(path):trajectories[row['scenario_id']]=row
    packet=export_observations(data,scenarios,trajectories,5*data['nominal_makespan']//4)
    cases=[]
    for result in analysis_report['results']:
        if result['status']!='PASS':
            cases.append(dict(case=result['case'],status='UNAVAILABLE'));continue
        deadline=result['deadline'];labels=outcomes(ledger,packet['contract']['jobs'],deadline)
        observed=mask(packet,result['mode'],labels)
        if digest(canonical(observed))!=result['input_sha256']:
            raise ValueError('saved observation packet differs from native bank export')
        model,rows,_=fit(observed,deadline)
        if digest(canonical(model))!=result['model_sha256']:
            raise ValueError('saved model differs from its native observations')
        certificates=read_json(analysis_folder/result['case']/'certificates.json.gz')
        cells={tuple(r['values']):r['extrema'] for r in certificates['category_certificates']}
        checked=unknown=0;mismatches=[];available_not_point=[]
        for attempt,row in zip(observed['attempts'],rows):
            y=labels[attempt['id']]
            if y is None:unknown+=1;continue
            extrema=cells[tuple(row[k] for k in model['signal_ids'])]
            for target in ('execution','R'):
                low,high=extrema[target]['minimum'],extrema[target]['maximum']
                if not low<=int(y)<=high:
                    mismatches.append(dict(attempt=attempt['id'],target=target,lower=low,upper=high,Y=y))
                if result['mode']=='available' and low!=high:
                    available_not_point.append(dict(attempt=attempt['id'],target=target))
                checked+=1
        status='PASS' if not mismatches and not available_not_point and not unknown else 'PARTIAL'
        cases.append(dict(case=result['case'],status=status,registered=len(observed['attempts']),
            known_outcome_attempts=len(observed['attempts'])-unknown,unavailable_outcomes=unknown,
            scalar_containment_checks=checked,mismatches=mismatches,available_nonpoint=available_not_point))
    return dict(status='PASS' if len(cases)==15 and all(r['status']=='PASS' for r in cases) else 'PARTIAL',
        condition=analysis_report['condition'],split=analysis_report['observations']['split'],cases=cases,
        statistical_replications=len(scenarios),comparison_repetitions_do_not_increase_n=True,
        identifier_receives_external_labels=False,role='post-seal external validation; not forecast fitting')
