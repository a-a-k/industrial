"""Generate a schedule from conditions under an explicitly selected objective."""
import argparse
from pathlib import Path
import time
from planning.generator import OBJECTIVES,from_conditions,initial_genome
from .common import actions_only,read_json,write_json


def generate(problem_path,folder,objective='nominal',seed=1701):
    if objective not in OBJECTIVES:raise ValueError('unknown objective')
    started=time.perf_counter()
    if objective=='nominal':
        from planning.cpsat import generate as nominal
        problem=read_json(problem_path)
        data=problem.get('dataset')
        if data is None:data=from_conditions(problem['conditions'])
        budget=problem.get('spec',{}).get('search',{}).get('total_budget_s',240)
        result=nominal(data,folder,budget,seed,started)
        result.update(objective=objective,backend='CP-SAT',reference_C0=data['nominal_makespan'],
            deadline=problem.get('deadline'),total_s=time.perf_counter()-started)
        if result['total_s']>budget:result['status']='BUDGET_EXCEEDED'
        write_json(Path(folder)/'result.json',result)
        return result
    from .plan_campaign import search_one
    from planning.cpsat import generate as nominal
    problem=read_json(problem_path);data=problem.get('dataset')
    if data is None:data=from_conditions(problem['conditions'])
    budget=problem['spec']['search']['total_budget_s']
    if budget<20:raise ValueError('at least twenty seconds required for the CP and simulation portfolio')
    cp_budget=min(60,budget/4)
    cp=nominal(data,Path(folder)/'cp-seed',cp_budget,seed,started)
    seed_plan=read_json(Path(folder)/'cp-seed/schedule.json')
    search_one(problem_path,folder,objective,seed,
        additional_initial=[initial_genome(seed_plan)],started=started)
    result=read_json(Path(folder)/'result.json')
    result.update(backend='CP-SAT-seeded-direct-simulation',cp_seed=cp,
        cp_seed_budget_s=cp_budget,initial_candidates=['original','CP-SAT'],
        total_interface_s=time.perf_counter()-started)
    if result['total_interface_s']>budget:result['status']='BUDGET_EXCEEDED'
    write_json(Path(folder)/'result.json',result)
    return result


if __name__=='__main__':
    actions_only();parser=argparse.ArgumentParser()
    parser.add_argument('input');parser.add_argument('--folder',required=True)
    parser.add_argument('--objective',choices=OBJECTIVES,default='nominal')
    parser.add_argument('--seed',type=int,default=1701);args=parser.parse_args()
    generate(args.input,args.folder,args.objective,args.seed)
