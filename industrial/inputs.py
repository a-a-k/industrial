"""Frozen Brandimarte schedules and fully specified synthetic failure laws."""
import math
from pathlib import Path
import urllib.request
from planning.list_v1 import schedule
from .common import SOURCE, DELTA, rng, digest


def parse_instance(text):
    lines = [list(map(int,line.split())) for line in text.splitlines() if line.strip()]
    n_jobs,machines = lines[0][:2]
    if len(lines) != n_jobs+1: raise ValueError('instance row census')
    jobs=[]
    for line in lines[1:]:
        pos=1; operations=[]
        for _ in range(line[0]):
            n=line[pos];pos+=1; options=[]
            for _ in range(n):
                machine,work=line[pos:pos+2];pos+=2
                options.append(dict(machine=machine,work=work*100))
            operations.append(options)
        if pos != len(line): raise ValueError('trailing instance fields')
        jobs.append(operations)
    values=[a['machine'] for job in jobs for op in job for a in op]
    # The pinned SchedulingLab files use zero-based machine identities.
    if min(values) < 0 or max(values) >= machines: raise ValueError('unexpected machine indexing')
    return jobs,machines


def dataset(instance, root):
    path=Path(root)/f'{instance.lower()}.txt';path.parent.mkdir(parents=True,exist_ok=True)
    url=f'https://raw.githubusercontent.com/SchedulingLab/fjsp-instances/{SOURCE}/brandimarte/{instance.lower()}.txt'
    if not path.exists():
        with urllib.request.urlopen(url,timeout=60) as response:path.write_bytes(response.read())
    jobs,machines=parse_instance(path.read_text());ops=[];final=[]
    for j,job in enumerate(jobs):
        previous=None
        for alternatives in job:
            i=len(ops)
            ops.append(dict(id=i,job=j,release=0,predecessors=[] if previous is None else [previous],
                            alternatives=alternatives))
            previous=i
        final.append(previous)
    queues=schedule(ops,machines);c0=max(o['planned_end'] for o in ops)
    data=dict(schema_version='industrial-schedule-v1',dataset_id=instance,
        operations=ops,queues=queues,jobs=[dict(id=j,release=0,final_operation=i) for j,i in enumerate(final)],
        nominal_makespan=c0,source=dict(url=url,sha256=digest(path.read_bytes()),commit=SOURCE),delta=DELTA)
    return data


def contract(data):
    return dict(id=data['dataset_id'],assignment_policy='fixed_no_reassignment',
        jobs=[j['id'] for j in data['jobs'] if not j.get('optional',False)],
        operations=[dict(id=o['id'],job=o['job'],predecessors=o['predecessors'],
            compatible_machines=[a['machine'] for a in o['alternatives']],optional=o.get('optional',False))
            for o in data['operations']])


def calendar(source,c0,horizon):
    clock=0;down=[];up_sum=repair_sum=0.;cycles=0
    while clock < horizon:
        up=source.expovariate(1/(2*c0));repair=source.expovariate(1/(.1*c0))
        up_sum+=up;repair_sum+=repair;cycles+=1
        clock+=max(DELTA,math.ceil(up/DELTA)*DELTA)
        if clock >= horizon: break
        finish=clock+max(DELTA,math.ceil(repair/DELTA)*DELTA)
        down.append((clock,min(finish,horizon)));clock=finish
    return down,dict(raw_up_sum=up_sum,raw_repair_sum=repair_sum,drawn_cycles=cycles)


def scenarios(data,law,split,count):
    c0=data['nominal_makespan'];h=5*c0//4;result=[]
    for index in range(count):
        identity=f'{data["dataset_id"]}-{law}-{split}-{index:04d}'
        shared=law=='F2' and rng(identity,'mixture').random()<.5
        histories=[];stats=[]
        if shared:
            common,stat=calendar(rng(identity,'shared'),c0,h)
            histories=[common for _ in data['queues']];stats=[stat]
        else:
            for m in range(len(data['queues'])):
                hist,stat=calendar(rng(identity,'machine',m),c0,h);histories.append(hist);stats.append(stat)
        result.append(dict(id=identity,failures=[[m,a,b] for m,hist in enumerate(histories) for a,b in hist],
                           work_overrides=[],shared_calendar=shared,raw_duration_statistics=stats))
    return result
