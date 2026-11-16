"""Physical change metrics and deadline-specific necessary service inequalities."""
from copy import deepcopy
from fractions import Fraction
from .common import canonical,digest
from .fixed_plan_inputs import conditions
from .local_corrections import earliest,structure
from planning.generator import validate_problem


def identity(data):return digest(canonical(structure(data)))


def normalize(data):
    data=deepcopy(data);validate_problem(data)
    if any(o['release']!=0 or o.get('optional',False) for o in data['operations']):
        raise ValueError('inverse certificate profile requires zero-release mandatory operations')
    if any(j.get('optional',False) for j in data['jobs']) or any(v is not True for v in data.get('quality_results',{}).values()):
        raise ValueError('inverse certificate profile requires accepted mandatory products')
    if data.get('extended_profile') or data.get('semantics'):raise ValueError('unsupported extended execution semantics')
    timing=earliest(data,data['queues'])
    if timing is None:raise ValueError('cyclic physical schedule')
    for o in data['operations']:
        i=o['id'];o.update(planned_start=timing['starts'][i],planned_end=timing['ends'][i])
    data['planned_makespan']=timing['cmax'];return data


def distance(base,plan):
    if canonical(conditions(base))!=canonical(conditions(plan)):raise ValueError('production constraints changed')
    assignments=sum(a['machine']!=b['machine'] for a,b in zip(base['operations'],plan['operations']))
    ranks={i:k for q in plan['queues'] for k,i in enumerate(q)};inversions=0
    for m,q in enumerate(base['queues']):
        kept=[i for i in q if plan['operations'][i]['machine']==m]
        inversions+=sum(ranks[a]>ranks[b] for k,a in enumerate(kept) for b in kept[k+1:])
    return dict(assignments=assignments,queue_inversions=inversions,total=assignments+inversions)


def analysis(plan,window_limit=32):
    canonical_plan=normalize(plan)
    if canonical(canonical_plan)!=canonical(plan):raise ValueError('plan must already be earliest')
    deadline=11*plan['nominal_makespan']//10;ops=plan['operations'];n=len(ops)
    if plan['planned_makespan']>deadline:raise ValueError('healthy schedule misses original deadline')
    children=[set() for _ in ops]
    for o in ops:
        for p in o['predecessors']:children[p].add(o['id'])
    for q in plan['queues']:
        for a,b in zip(q,q[1:]):children[a].add(b)
    order=sorted(range(n),key=lambda i:(ops[i]['planned_start'],i))
    latest_start=[deadline-o['work'] for o in ops]
    for i in reversed(order):
        if children[i]:latest_start[i]=min(latest_start[j]-ops[i]['work'] for j in children[i])
    latest_finish=[latest_start[i]+ops[i]['work'] for i in range(n)]
    windows=[];work=[]
    for m,q in enumerate(plan['queues']):
        work.append(sum(ops[i]['work'] for i in q));candidates=[]
        starts=sorted({0,*[ops[i]['planned_start'] for i in q]})
        ends=sorted({deadline,*[latest_finish[i] for i in q]})
        for a in starts:
            for b in ends:
                if a>=b:continue
                required=sum(max(0,ops[i]['work']-max(0,a-ops[i]['planned_start'])-max(0,latest_finish[i]-b)) for i in q)
                if required<=0:continue
                if required>b-a:raise ValueError('necessary inequality contradicts healthy feasible schedule')
                candidates.append(dict(machine=m,begin=a,end=b,required=required))
        candidates.sort(key=lambda r:(-Fraction(r['required'],r['end']-r['begin']),
            r['end']-r['begin']-r['required'],r['begin'],r['end']))
        windows.extend(candidates[:window_limit])
    return dict(deadline=deadline,nominal=plan['planned_makespan'],machine_work=work,
        earliest_start=[o['planned_start'] for o in ops],latest_finish=latest_finish,
        deadline_slack=[latest_start[i]-ops[i]['planned_start'] for i in range(n)],windows=windows,
        shared_calendar_downtime_budget=deadline-plan['planned_makespan'],
        plan_sha256=digest(canonical(plan)),certificate_profile='zero_release_earliest_unit_rate_preempt_resume_unlimited_buffers')
