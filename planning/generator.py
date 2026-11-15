"""Feasible assignment/order generation with selectable empirical objectives."""
from copy import deepcopy
import heapq
import random
import time


OBJECTIVES=('nominal','deadline_f1','worst_regime','pareto')


class BudgetStop(Exception):
    """An incomplete evaluation is censored, never admitted as a candidate score."""


def validate_problem(data):
    ops=data['operations'];machines=len(data['queues'])
    if not machines or [o['id'] for o in ops]!=list(range(len(ops))):
        raise ValueError('operations must have consecutive integer identities and machines')
    jobs={j['id'] for j in data['jobs']}
    for op in ops:
        if op['job'] not in jobs or type(op.get('release',0)) is not int or op.get('release',0)<0:
            raise ValueError('invalid job or release')
        if not op['alternatives']:raise ValueError('operation has no compatible machine')
        seen=set()
        for alternative in op['alternatives']:
            machine,work=alternative['machine'],alternative['work']
            if (type(machine) is not int or not 0<=machine<machines or machine in seen
                    or type(work) is not int or work<=0):raise ValueError('invalid machine alternative')
            seen.add(machine)
        if any(type(p) is not int or not 0<=p<len(ops) or p==op['id'] for p in op['predecessors']):
            raise ValueError('invalid predecessor')


def initial_genome(data):
    assignments=[]
    for op in data['operations']:
        assignments.append(next(i for i,a in enumerate(op['alternatives'])
            if a['machine']==op['machine'] and a['work']==op['work']))
    priority=sorted(range(len(assignments)),key=lambda i:(data['operations'][i]['planned_start'],i))
    return assignments,priority


def decode(data,genome):
    assignments,priority=genome;ops=deepcopy(data['operations']);n=len(ops)
    if len(assignments)!=n or sorted(priority)!=list(range(n)):raise ValueError('invalid search encoding')
    rank={op:index for index,op in enumerate(priority)}
    pending=[len(op['predecessors']) for op in ops];children=[[] for _ in ops]
    for op in ops:
        for parent in op['predecessors']:children[parent].append(op['id'])
    ready=[(rank[i],i) for i,k in enumerate(pending) if not k];heapq.heapify(ready)
    queues=[[] for _ in data['queues']];tail=[0]*len(queues);count=0
    while ready:
        _,i=heapq.heappop(ready);op=ops[i];choice=assignments[i]
        if type(choice) is not int or not 0<=choice<len(op['alternatives']):raise ValueError('invalid assignment')
        alternative=op['alternatives'][choice];machine=alternative['machine'];work=alternative['work']
        start=max([op.get('release',0),tail[machine],*(ops[p]['planned_end'] for p in op['predecessors'])])
        op.update(machine=machine,work=work,planned_start=start,planned_end=start+work)
        tail[machine]=start+work;queues[machine].append(i);count+=1
        for child in children[i]:
            pending[child]-=1
            if not pending[child]:heapq.heappush(ready,(rank[child],child))
    if count!=n:raise ValueError('cyclic precedence graph')
    return dict(data,operations=ops,queues=queues,planned_makespan=max(tail))


def mutate(data,genome,source,restart=False):
    assignments,priority=[list(x) for x in genome]
    movable=[op['id'] for op in data['operations'] if len(op['alternatives'])>1]
    if restart:
        assignments=[source.randrange(len(op['alternatives'])) for op in data['operations']]
        source.shuffle(priority)
    elif movable and source.random()<.5:
        i=source.choice(movable);choices=list(range(len(data['operations'][i]['alternatives'])))
        choices.remove(assignments[i]);assignments[i]=source.choice(choices)
    elif len(priority)>1:
        i,j=source.sample(range(len(priority)),2);priority[i],priority[j]=priority[j],priority[i]
    return assignments,priority


def objective_key(score,objective):
    if objective=='nominal':return (score['nominal_makespan'],)
    if objective=='deadline_f1':return (-score['p_f1'],score['nominal_makespan'])
    if objective=='worst_regime':
        return (-min(score['p_f1'],score['p_f2']),-(score['p_f1']+score['p_f2']),score['nominal_makespan'])
    raise ValueError('scalar objective required')


def coordinates(score):return (score['nominal_makespan'],-score['p_f1'],-score['p_f2'])


def dominates(a,b):return all(x<=y for x,y in zip(a,b)) and any(x<y for x,y in zip(a,b))


def pareto_representatives(archive,limit):
    """Keep extremes, then deterministic farthest points in observed coordinates."""
    ordered=sorted(archive,key=lambda r:r['plan_sha256'])
    if len(ordered)<=limit:return ordered
    points={r['plan_sha256']:coordinates(r['score']) for r in ordered}
    scales=[max(p[i] for p in points.values())-min(p[i] for p in points.values()) or 1 for i in range(3)]
    selected=[]
    for i in range(3):
        r=min(ordered,key=lambda r:(points[r['plan_sha256']][i],r['plan_sha256']))
        if r not in selected:selected.append(r)
    while len(selected)<limit:
        candidates=[r for r in ordered if r not in selected]
        def distance(r):
            return min(sum(((points[r['plan_sha256']][i]-points[s['plan_sha256']][i])/scales[i])**2
                for i in range(3)) for s in selected)
        selected.append(max(candidates,key=lambda r:(distance(r),r['plan_sha256'])))
    return selected


def search(data,objective,evaluate,identity,budget_s,seed,max_evaluations=1000,trace=None):
    if objective not in OBJECTIVES:raise ValueError('unknown objective')
    validate_problem(data);started=time.perf_counter();source=random.Random(seed)
    genome=initial_genome(data);cache={};archive=[];incumbent=None;best=None;stale=0
    evaluated_records={}
    stats=dict(evaluated=0,cache_hits=0,restarts=0,failures=0,budget_censored_evaluations=0)
    stopping='evaluation_limit'
    for iteration in range(max_evaluations):
        elapsed=time.perf_counter()-started
        if elapsed>=budget_s:stopping='wall_budget';break
        if iteration:
            restart=stale>=32
            if objective=='pareto' and archive:genome=source.choice(archive)['genome']
            elif incumbent is not None:genome=incumbent['genome']
            genome=mutate(data,genome,source,restart)
            if restart:stats['restarts']+=1;stale=0;incumbent=None
        plan=decode(data,genome);key=identity(plan)
        if key in cache:
            stats['cache_hits']+=1;score=cache[key]
        else:
            # Reserve the observed cost of another complete evaluation.
            typical=(time.perf_counter()-started)/max(stats['evaluated'],1)
            if budget_s-(time.perf_counter()-started)<max(1.,2*typical):
                stopping='evaluation_reservation';break
            try:score=evaluate(plan,objective,budget_s-(time.perf_counter()-started))
            except BudgetStop as error:
                stats['budget_censored_evaluations']+=1;stopping='evaluation_budget_censored'
                if trace:trace(dict(iteration=iteration,plan_sha256=key,genome=genome,status='BUDGET_CENSORED',error=str(error)))
                break
            except Exception as error:
                stats['failures']+=1
                if trace:trace(dict(iteration=iteration,plan_sha256=key,genome=genome,status='FAILED',error=str(error)))
                stale+=1;continue
            cache[key]=score;stats['evaluated']+=1
        record=dict(plan_sha256=key,genome=genome,score=score)
        evaluated_records[key]=record
        if trace:trace(dict(record,iteration=iteration,status='OK',elapsed_s=time.perf_counter()-started))
        if objective=='pareto':
            point=coordinates(score)
            if not any(coordinates(r['score'])==point or dominates(coordinates(r['score']),point) for r in archive):
                archive=[r for r in archive if not dominates(point,coordinates(r['score']))]+[record]
                archive=pareto_representatives(archive,128);stale=0
            else:stale+=1
            incumbent=record
        elif incumbent is None or objective_key(score,objective)<objective_key(incumbent['score'],objective):
            incumbent=record;stale=0
        else:stale+=1
        if objective!='pareto' and (best is None or objective_key(score,objective)<objective_key(best['score'],objective)):
            best=record
    if objective=='pareto':
        # The search archive may be capped; final output is checked against ALL evaluated plans.
        archive=[]
        for record in sorted(evaluated_records.values(),key=lambda r:r['plan_sha256']):
            point=coordinates(record['score'])
            if not any(coordinates(r['score'])==point or dominates(coordinates(r['score']),point) for r in archive):
                archive=[r for r in archive if not dominates(point,coordinates(r['score']))]+[record]
        selected=pareto_representatives(archive,9)
    else:selected=[best] if best else []
    return dict(selected=selected,stats=stats,stopping_reason=stopping,wall_s=time.perf_counter()-started,
        objective=objective,seed=seed,budget_s=budget_s,max_evaluations=max_evaluations,
        globally_optimal=False,claim='best found under the declared search budget')
