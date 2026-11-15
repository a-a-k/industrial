from itertools import permutations,product
from pathlib import Path
import unittest
from planning.generator import BudgetStop,decode,initial_genome,search,validate_problem
from industrial.plan_campaign import plan_identity,paired_difference
from industrial.production import simulate,check_physics,compare


def problem():
    return dict(dataset_id='planner-fixture',delta=5,nominal_makespan=60,
        queues=[[0,2],[1]],jobs=[dict(id=0,release=0,final_operation=2),dict(id=1,release=0,final_operation=1)],
        operations=[dict(id=0,job=0,release=0,predecessors=[],alternatives=[dict(machine=0,work=30),dict(machine=1,work=10)],machine=0,work=30,planned_start=0,planned_end=30),
            dict(id=1,job=1,release=5,predecessors=[],alternatives=[dict(machine=0,work=10),dict(machine=1,work=20)],machine=1,work=20,planned_start=5,planned_end=25),
            dict(id=2,job=0,release=0,predecessors=[0],alternatives=[dict(machine=0,work=30)],machine=0,work=30,planned_start=30,planned_end=60)])


class PlanningTests(unittest.TestCase):
    def test_every_tiny_assignment_and_priority_is_feasible_and_independent_engines_agree(self):
        data=problem();validate_problem(data);count=0
        for assignments in product(range(2),range(2),range(1)):
            for priority in permutations(range(3)):
                plan=decode(data,(assignments,priority));count+=1
                for op in plan['operations']:
                    self.assertGreaterEqual(op['planned_start'],op['release'])
                    self.assertEqual(op['planned_end']-op['planned_start'],op['work'])
                    for parent in op['predecessors']:
                        self.assertGreaterEqual(op['planned_start'],plan['operations'][parent]['planned_end'])
                for queue in plan['queues']:
                    for a,b in zip(queue,queue[1:]):
                        self.assertGreaterEqual(plan['operations'][b]['planned_start'],plan['operations'][a]['planned_end'])
                scenario=dict(id=f'decoder-{count}',failures=[[0,10,25]],work_overrides=[]);outputs=[]
                for engine in ('des','dag'):
                    trajectories,ps=simulate(plan,[scenario],Path('output/planning-tests')/str(count)/engine,engine,100)
                    self.assertTrue(all(p['status']=='OK' for p in ps));trajectory=trajectories[scenario['id']]
                    check_physics(plan,scenario,trajectory);outputs.append(trajectory)
                compare(*outputs)
        self.assertEqual(count,24)

    def test_search_generates_new_assignments_and_preserves_best_incumbent(self):
        data=problem();initial=decode(data,initial_genome(data))
        def evaluate(plan,objective,remaining_s):
            return dict(nominal_makespan=plan['planned_makespan'],p_f1=1-plan['planned_makespan']/100,p_f2=.5)
        for objective in ('nominal','deadline_f1','worst_regime','pareto'):
            result=search(data,objective,evaluate,plan_identity,10,1701,max_evaluations=100)
            self.assertTrue(result['selected']);self.assertFalse(result['globally_optimal'])
            self.assertLess(min(r['score']['nominal_makespan'] for r in result['selected']),initial['planned_makespan'])

    def test_budget_censored_evaluation_returns_the_previous_incumbent(self):
        calls=[]
        def evaluate(plan,objective,remaining_s):
            calls.append(plan_identity(plan))
            if len(calls)>1:raise BudgetStop('test remaining-budget exhaustion')
            return dict(nominal_makespan=plan['planned_makespan'])
        result=search(problem(),'nominal',evaluate,plan_identity,10,1701,max_evaluations=100)
        self.assertEqual(result['stopping_reason'],'evaluation_budget_censored')
        self.assertEqual(result['stats']['budget_censored_evaluations'],1)
        self.assertEqual(result['selected'][0]['plan_sha256'],calls[0])

    def test_invalid_compatibility_and_cycles_are_rejected(self):
        data=problem();data['operations'][0]['alternatives'][0]['machine']=99
        with self.assertRaises(ValueError):validate_problem(data)
        data=problem();data['operations'][0]['predecessors']=[2]
        with self.assertRaises(ValueError):decode(data,initial_genome(data))

    def test_paired_gain_and_loss_use_shared_attempt_ids(self):
        a={str(i):True for i in range(1024)};b={str(i):False for i in range(1024)}
        result=paired_difference(a,b)
        self.assertEqual(result['gain'],1024);self.assertEqual(result['difference'],1)
        self.assertGreater(result['outer95'][0],0)
        b['0']=None;self.assertEqual(paired_difference(a,b)['status'],'UNAVAILABLE')


if __name__=='__main__':unittest.main()
