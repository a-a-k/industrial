from pathlib import Path
import unittest
from planning.cpsat import generate as cp_generate
from planning.generator import decode
from planning.rerank import generate
from industrial.common import canonical,digest,read_json,write_json
from industrial.inputs import scenarios
from tests.test_planning import problem


class RerankTests(unittest.TestCase):
    def test_callback_pool_has_feasible_decodable_incumbents_and_final_solution(self):
        data=problem();root=Path('output/comparison-tests/callback')
        result=cp_generate(data,root,15,1701,pool_limit=16)
        pool=read_json(root/'pool.json')
        self.assertGreater(pool['solutions_seen'],0)
        self.assertLessEqual(len(pool['candidates']),16)
        for row in pool['candidates']:
            plan=decode(data,row['genome'])
            self.assertLessEqual(plan['planned_makespan'],row['cp_objective_ticks'])
        self.assertEqual(decode(data,pool['final_genome'])['planned_makespan'],result['planned_makespan'])

    def test_ranking_checks_both_references_on_the_exact_declared_calibration(self):
        root=Path('output/comparison-tests/rerank');data=problem()
        spec=dict(search=dict(total_budget_s=30,max_evaluations=20),pool_cp_budget_s=10,
            pool_limit=16,search_replications_per_law=8,search_split='rerank-interface-check')
        write_json(root/'problem.json',dict(dataset=data,deadline=70,spec=spec))
        result=generate(root/'problem.json',root/'result',1701)
        self.assertEqual(result['status'],'PASS')
        self.assertTrue(result['mandatory_original_and_nominal_evaluated'])
        self.assertEqual(result['calibration_sha256'],digest(canonical(scenarios(data,'F1',spec['search_split'],8))))
        good=[r for r in result['candidates'] if r['status']=='OK']
        self.assertEqual(len({r['plan_sha256'] for r in good}),len(good))
        self.assertEqual(result['selected'][0]['score']['p_f1'],max(r['score']['p_f1'] for r in good))


if __name__=='__main__':unittest.main()
