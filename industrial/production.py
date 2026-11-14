"""Execution, permitted observation export and separate product accounting."""
from pathlib import Path
import os
from .common import read_rows,write_json,execute
from .inputs import contract


SIGNATURE=('start','finish','remaining','state','job_finish','cmax','completion_known',
           'completion_lower_bound','mission_success','stopped')


def simulate(data, scenarios, root, engine, horizon, chunk=128):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    dataset_path=root/'dataset.json';write_json(dataset_path,data)
    results={};processes=[]
    for begin in range(0,len(scenarios),chunk):
        batch=scenarios[begin:begin+chunk];inp=root/f'{engine}-{begin:05d}-input.json'
        output=root/f'{engine}-{begin:05d}.jsonl';write_json(inp,batch)
        executable=Path('.private/runtime/tsfg') if engine=='tsfg' else Path('build/simulator')
        command=[str(executable.resolve()),engine,str(dataset_path),str(inp),
                 str(output),'MISSION',str(horizon),str(data['delta'])]
        env={**os.environ,'TSFG_OP_DRIVER':'true','GOMAXPROCS':'1'}
        process=execute(command,env=env)
        process.update(engine=engine,first=begin,attempts=[s['id'] for s in batch])
        if output.exists():
            try:
                for row in read_rows(output):
                    if row['scenario_id'] in results: raise ValueError('duplicate trajectory')
                    results[row['scenario_id']]=row
            except (ValueError,EOFError) as error:
                process['output_error']=str(error)
                if process['status']=='OK':process['status']='INVALID_OUTPUT'
        process['completed']=sum(s['id'] in results for s in batch)
        processes.append(process)
    return results,processes


def export_observations(data, scenarios, trajectories, horizon):
    attempts=[];records=[]
    for scenario in scenarios:
        aid=scenario['id'];trajectory=trajectories.get(aid)
        if trajectory is None:
            attempts.append(dict(id=aid,started_at=0,observed_until=horizon,finished_at=None,
                                 compute_status='UNAVAILABLE'))
            continue
        mandatory=[o for o in data['operations'] if not o.get('optional',False)]
        ends=[trajectory['finish'][o['id']] for o in mandatory]
        finished=max(ends) if ends and all(t is not None for t in ends) else None
        attempts.append(dict(id=aid,started_at=0,observed_until=horizon,finished_at=finished,compute_status='OK'))
        records.append(dict(attempt=aid,record_id='dispatch',kind='dispatch',time=0,value=True))
        for op in data['operations']:
            i=op['id']
            records.append(dict(attempt=aid,record_id=f'assignment:{i}',kind='assignment',op=i,
                                machine=op['machine'],closed=True,time=0))
            start=trajectory['start'][i]
            if start is not None:
                records.append(dict(attempt=aid,record_id=f'receipt:{i}',kind='receipt',op=i,
                    machine=op['machine'],time=start,parents=op['predecessors']))
        for job in data['jobs']:
            local=[trajectory['finish'][o['id']] for o in mandatory if o['job']==job['id']]
            if local and all(t is not None for t in local):
                records.append(dict(attempt=aid,record_id=f'postcondition:{job["id"]}',kind='postcondition',
                                    job=job['id'],time=max(local),value=data.get('quality_results',{}).get(str(job['id']),True)))
    return dict(contract=contract(data),attempts=attempts,records=records)


def product_ledger(data, scenarios, trajectories):
    """Independent product census: no model/binding calls or derived model bits."""
    result=[]
    for scenario in scenarios:
        aid=scenario['id'];trajectory=trajectories.get(aid)
        if trajectory is None:
            result.append(dict(attempt=aid,status='COMPUTATION_UNAVAILABLE',products=[]));continue
        products=[]
        for job in data['jobs']:
            if job.get('optional',False): continue
            terminal=job['final_operation'];issued=trajectory['finish'][terminal]
            if issued is not None:
                products.append(dict(job=job['id'],serial=f'{aid}/{job["id"]}',issued_at=issued,
                    accepted=data.get('quality_results',{}).get(str(job['id']),True)))
        result.append(dict(attempt=aid,status='OBSERVED',products=products))
    return result


def outcomes(ledger,jobs,deadline):
    result={}
    for row in ledger:
        if row['status'] != 'OBSERVED':
            result[row['attempt']]=None;continue
        good={p['job'] for p in row['products'] if p['accepted'] and p['issued_at']<=deadline}
        result[row['attempt']]=set(jobs)<=good
    return result


def check_physics(data, scenario, trajectory):
    if len(trajectory['finish']) != len(data['operations']): raise ValueError('trajectory dimensions')
    horizon=trajectory['horizon'];down=[[] for _ in data['queues']]
    for m,a,b in scenario['failures']:down[m].append((a,b))
    for op in data['operations']:
        i=op['id'];s=trajectory['start'][i];f=trajectory['finish'][i];rem=trajectory['remaining'][i]
        if s is None:
            if f is not None or rem!=op['work']:raise ValueError('unstarted work conservation')
            continue
        if s<max(op['release'],op['planned_start']) or s>horizon:raise ValueError('invalid start')
        for p in op['predecessors']:
            if trajectory['finish'][p] is None or trajectory['finish'][p]>s:raise ValueError('causal start')
        if any(a<=s<b for a,b in down[op['machine']]):raise ValueError('start in downtime')
        end=horizon if f is None else f
        service=end-s-sum(max(0,min(end,b)-max(s,a)) for a,b in down[op['machine']])
        if service+rem!=op['work'] or rem<0 or (f is not None and (rem or f>horizon)):
            raise ValueError('work conservation')
    for queue in data['queues']:
        for left,right in zip(queue,queue[1:]):
            if trajectory['start'][right] is not None:
                if trajectory['finish'][left] is None or trajectory['finish'][left]>trajectory['start'][right]:
                    raise ValueError('machine queue/overlap')


def compare(left,right):
    differences=[key for key in SIGNATURE if left[key]!=right[key]]
    if differences:raise ValueError('engine disagreement: '+','.join(differences))
