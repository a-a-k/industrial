from itertools import permutations,product
from pathlib import Path
import unittest
from planning.cpsat import generate
from planning.generator import decode
from industrial.common import read_json,write_json
from industrial.plan import generate as generate_under_objective
from tests.test_planning import problem


class CpPlanningTests(unittest.TestCase):
    def test_public_interface_generates_nominal_optimum_from_unscheduled_conditions(self):
        raw=problem();raw['machines']=2
        for key in ('queues','nominal_makespan','dataset_id','delta'):raw.pop(key)
        for op in raw['operations']:
            for key in ('machine','work','planned_start','planned_end'):op.pop(key)
        root=Path('output/cpsat-tests/raw-interface')
        write_json(root/'problem.json',dict(conditions=raw,deadline=70,
            spec=dict(search=dict(total_budget_s=15))))
        result=generate_under_objective(root/'problem.json',root/'generated','nominal',1701)
        self.assertEqual(result['backend'],'CP-SAT')
        self.assertEqual(result['planned_makespan'],40)
        self.assertEqual(result['deadline'],70)
        self.assertTrue(result['nominal_optimality_proved'])
        plan=read_json(root/'generated/schedule.json')
        self.assertEqual(len(plan['queues']),2)
        self.assertEqual(plan['planned_makespan'],40)

    def test_nominal_optimum_matches_independent_tiny_exhaustion(self):
        data=problem()
        optimum=min(decode(data,(choices,order))['planned_makespan']
            for choices in product(range(2),range(2),range(1)) for order in permutations(range(3)))
        result=generate(data,Path('output/cpsat-tests/tiny'),budget_s=15)
        self.assertEqual(result['solver_status'],'OPTIMAL')
        self.assertEqual(result['planned_makespan'],optimum)
        self.assertEqual(result['lower_bound_ticks'],optimum)

    def test_gcd_units_preserve_releases_and_objective(self):
        data=problem()
        for op in data['operations']:
            for key in ('release','work','planned_start','planned_end'):op[key]*=20
            for alt in op['alternatives']:alt['work']*=20
        data['nominal_makespan']*=20
        result=generate(data,Path('output/cpsat-tests/scaled'),budget_s=15)
        self.assertEqual(result['solver_tick'],100)
        self.assertEqual(result['planned_makespan'],800)
        self.assertTrue(result['nominal_optimality_proved'])


if __name__=='__main__':unittest.main()
