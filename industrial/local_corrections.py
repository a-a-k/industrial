"""A predefined finite catalogue preserving every unedited physical queue order."""
from copy import deepcopy
import heapq
from .common import canonical,digest
from .fixed_plan_inputs import conditions
from planning.generator import validate_problem


def structure(data):
    return dict(queues=data['queues'],assignments=[(o['machine'],o['work']) for o in data['operations']])


def earliest(data,queues,assignment=None):
    n=len(data['operations']);work=[o['work'] for o in data['operations']]
    machines=[o['machine'] for o in data['operations']]
    if assignment is not None:
        i,m,w=assignment;machines[i]=m;work[i]=w
    if sorted(i for q in queues for i in q)!=list(range(n)):raise ValueError('queue census')
    parents=[set(o['predecessors']) for o in data['operations']];children=[[] for _ in range(n)]
    for m,q in enumerate(queues):
        if any(machines[i]!=m for i in q):raise ValueError('queue assignment')
        for a,b in zip(q,q[1:]):parents[b].add(a)
    degree=[len(p) for p in parents]
    for i,ps in enumerate(parents):
        for p in ps:children[p].append(i)
    ready=[i for i,d in enumerate(degree) if not d];heapq.heapify(ready)
    starts=[0]*n;ends=[0]*n;order=[]
    while ready:
        i=heapq.heappop(ready);order.append(i)
        starts[i]=max([data['operations'][i].get('release',0),*(ends[p] for p in parents[i])]);ends[i]=starts[i]+work[i]
        for j in children[i]:
            degree[j]-=1
            if not degree[j]:heapq.heappush(ready,j)
    if len(order)!=n:return None
    cmax=max(ends);latest=[cmax-w for w in work]
    for i in reversed(order):
        if children[i]:latest[i]=min(latest[j]-work[i] for j in children[i])
    return dict(starts=starts,ends=ends,cmax=cmax,slack=[latest[i]-starts[i] for i in range(n)])


def materialize(base,edit):
    data=deepcopy(base);qs=data['queues'];kind=edit['kind']
    if kind=='swap':
        m,k=edit['machine'],edit['slot'];qs[m][k],qs[m][k+1]=qs[m][k+1],qs[m][k]
    elif kind=='move':
        i,m,k=edit['operation'],edit['target'],edit['slot'];o=data['operations'][i]
        qs[o['machine']].remove(i);qs[m].insert(k,i);o.update(machine=m,work=edit['work'])
    elif kind!='none':raise ValueError('unknown edit')
    timing=earliest(data,qs)
    if timing is None:raise ValueError('cyclic correction')
    for o in data['operations']:
        i=o['id'];o.update(planned_start=timing['starts'][i],planned_end=timing['ends'][i])
    data['planned_makespan']=timing['cmax']
    if data['planned_makespan']>base['planned_makespan']:raise ValueError('nominal guard')
    validate_problem(data)
    if canonical(conditions(data))!=canonical(conditions(base)):raise ValueError('changed production conditions')
    return data


def diff(base,plan):
    return dict(operations=[dict(operation=a['id'],before={k:a[k] for k in ('machine','work','planned_start','planned_end')},
        after={k:b[k] for k in ('machine','work','planned_start','planned_end')})
        for a,b in zip(base['operations'],plan['operations'])
        if any(a[k]!=b[k] for k in ('machine','work','planned_start','planned_end'))],
        queues=[dict(machine=m,before=a,after=b) for m,(a,b) in enumerate(zip(base['queues'],plan['queues'])) if a!=b])


def catalogue(base):
    validate_problem(base);timing=earliest(base,base['queues'])
    if timing is None or timing['starts']!=[o['planned_start'] for o in base['operations']]:
        raise ValueError('input must already use earliest feasible nominal times')
    if timing['cmax']!=base['planned_makespan']:raise ValueError('input nominal duration changed')
    records=[];seen=set();stats=dict(positions_checked=0,cyclic=0,nominal_rejected=0,exact_duplicates=0)
    def admit(edit,qs,assignment=None,known=None):
        t=known if known is not None else earliest(base,qs,assignment)
        if known is None:stats['positions_checked']+=1
        if t is None:stats['cyclic']+=1;return None
        if t['cmax']>timing['cmax']:stats['nominal_rejected']+=1;return None
        assignments=[(o['machine'],o['work']) for o in base['operations']]
        if assignment is not None:
            i,m,w=assignment;assignments[i]=(m,w)
        key=digest(canonical(dict(queues=qs,assignments=assignments)))
        if key in seen:stats['exact_duplicates']+=1;return None
        seen.add(key);record=dict(edit,structure_sha256=key,cmax=t['cmax'],edit_count=int(edit['kind']!='none'))
        records.append(record);return record
    admit(dict(id='none',kind='none',machines=[],operations=[]),base['queues'],known=timing)
    for m,q in enumerate(base['queues']):
        for slot in range(len(q)-1):
            qs=[list(v) for v in base['queues']];qs[m][slot],qs[m][slot+1]=qs[m][slot+1],qs[m][slot]
            admit(dict(id=f'swap-{m:03d}-{slot:04d}',kind='swap',machine=m,slot=slot,
                       machines=[m],operations=sorted(q[slot:slot+2])),qs)
    for o in base['operations']:
        i=o['id'];origin=o['machine']
        for a in sorted(o['alternatives'],key=lambda r:r['machine']):
            m,w=a['machine'],a['work']
            if m==origin:continue
            qs=[list(v) for v in base['queues']];qs[origin].remove(i);best=None
            for slot in range(len(qs[m])+1):
                qs[m].insert(slot,i);t=earliest(base,qs,(i,m,w));stats['positions_checked']+=1
                if t is None:stats['cyclic']+=1
                elif t['cmax']>timing['cmax']:stats['nominal_rejected']+=1
                else:
                    displacement=sum(abs(x-y) for x,y in zip(t['starts'],timing['starts']))+sum(abs(x-y) for x,y in zip(t['ends'],timing['ends']))
                    key=(t['cmax'],displacement,slot)
                    if best is None or key<best[0]:best=(key,slot,t)
                qs[m].pop(slot)
            if best is not None:
                _,slot,t=best;qs[m].insert(slot,i)
                admit(dict(id=f'move-{i:04d}-{m:03d}-{slot:04d}',kind='move',operation=i,target=m,slot=slot,work=w,
                           machines=sorted([origin,m]),operations=[i]),qs,(i,m,w),t)
    return records,dict(stats,retained=len(records),base_slack=timing['slack'])
