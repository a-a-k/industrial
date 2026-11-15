"""Standard flexible-job-shop CP-SAT generation, followed by earliest decoding."""
import argparse
from copy import deepcopy
from functools import reduce
from math import gcd
from pathlib import Path
import resource
import sys
import time
from planning.generator import decode,from_conditions,initial_genome,validate_problem
from industrial.common import actions_only,digest,read_json,write_json


def generate(data,folder,budget_s=240,seed=1701,started=None):
    started=time.perf_counter() if started is None else started
    from ortools.sat.python import cp_model
    import ortools
    data=deepcopy(data);validate_problem(data)
    # Earliest schedules have times on the gcd grid of the given durations/releases.
    step=reduce(gcd,[a['work'] for op in data['operations'] for a in op['alternatives']]
        +[op['release'] for op in data['operations']])
    initial=decode(data,initial_genome(data));horizon=initial['planned_makespan']//step
    model=cp_model.CpModel();starts={};ends={};choices={};intervals=[[] for _ in data['queues']]
    for op in data['operations']:
        i=op['id'];starts[i]=model.new_int_var(0,horizon,f'start_{i}')
        ends[i]=model.new_int_var(0,horizon,f'end_{i}')
        model.add(starts[i]>=op['release']//step);present=[]
        for index,alt in enumerate(op['alternatives']):
            presence=model.new_bool_var(f'choose_{i}_{index}');choices[i,index]=presence;present.append(presence)
            interval=model.new_optional_interval_var(starts[i],alt['work']//step,ends[i],presence,f'op_{i}_{index}')
            intervals[alt['machine']].append(interval)
        model.add_exactly_one(present)
    for op in data['operations']:
        for parent in op['predecessors']:model.add(starts[op['id']]>=ends[parent])
    for group in intervals:model.add_no_overlap(group)
    makespan=model.new_int_var(0,horizon,'makespan');model.add_max_equality(makespan,list(ends.values()));model.minimize(makespan)
    # The same inexpensive initial schedule is available to the heuristic and CP-SAT.
    for op in initial['operations']:
        model.add_hint(starts[op['id']],op['planned_start']//step)
        model.add_hint(ends[op['id']],op['planned_end']//step)
        for index,alt in enumerate(op['alternatives']):
            model.add_hint(choices[op['id'],index],int(alt['machine']==op['machine']))
    model.add_hint(makespan,horizon)
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1;solver.parameters.random_seed=seed
    remaining=budget_s-(time.perf_counter()-started)-5
    if remaining<=0:raise TimeoutError('CP model construction exhausted its complete budget')
    solver.parameters.max_time_in_seconds=remaining
    status=solver.solve(model);status_name=solver.status_name(status)
    if status in (cp_model.INFEASIBLE,cp_model.MODEL_INVALID):raise ValueError('constructively feasible model rejected: '+status_name)
    plan=initial;incumbent_source='initial';objective=None
    if status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        assignments=[next(k for k in range(len(op['alternatives'])) if solver.boolean_value(choices[op['id'],k])) for op in data['operations']]
        priorities=sorted(range(len(assignments)),key=lambda i:(solver.value(starts[i]),i))
        plan=decode(data,(assignments,priorities));incumbent_source='CP-SAT';objective=solver.value(makespan)*step
        if plan['planned_makespan']>objective:raise ValueError('earliest decoding worsened the CP solution')
        if status==cp_model.OPTIMAL and plan['planned_makespan']!=objective:raise ValueError('claimed optimum contradicts feasible decoding')
    root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    write_json(root/'schedule.json',plan)
    response=dict(status='PASS',solver_status=status_name,incumbent_source=incumbent_source,
        nominal_optimality_proved=status==cp_model.OPTIMAL,stochastic_optimality_claimed=False,
        planned_makespan=plan['planned_makespan'],initial_makespan=initial['planned_makespan'],
        cp_objective_ticks=objective,lower_bound_ticks=solver.best_objective_bound*step,
        seed=seed,budget_s=budget_s,ortools_version=ortools.__version__,workers=1,
        solver_tick=step,execution_tick=data['delta'],
        model_build_and_search_s=time.perf_counter()-started,
        cpu_s=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        initial_hint='original inexpensive list schedule; no prior expensive heuristic hint',
        earliest_decoding='same assignments and machine order; remove unnecessary nominal idle time')
    write_json(root/'result.json',response)
    return response


if __name__=='__main__':
    actions_only();started=time.perf_counter();p=argparse.ArgumentParser()
    p.add_argument('input');p.add_argument('output');p.add_argument('--budget',type=float,default=240);p.add_argument('--seed',type=int,default=1701)
    args=p.parse_args();problem=read_json(args.input)
    data=problem.get('dataset')
    if data is None:data=from_conditions(problem['conditions'])
    generate(data,args.output,args.budget,args.seed,started)
