from copy import deepcopy
import unittest
from industrial.binding import bind,direct_rows
from industrial.model import Unsupported


def packet():
    return dict(contract=dict(id='edge-audit',jobs=[0],operations=[dict(id=0,job=0,predecessors=[],compatible_machines=[0])]),
        attempts=[dict(id='a',started_at=0,observed_until=100,finished_at=10)],records=[
            dict(attempt='a',kind='dispatch',time=0,value=True),
            dict(attempt='a',kind='assignment',op=0,machine=0,time=0,closed=True),
            dict(attempt='a',kind='receipt',op=0,machine=0,time=0,parents=[]),
            dict(attempt='a',kind='postcondition',job=0,time=10,value=True)])


class BindingEdgeTests(unittest.TestCase):
    def test_out_of_window_records_are_ignored_before_structural_validation(self):
        base=packet()
        for extra in (dict(kind='reassign',op=0,machine=0),dict(kind='receipt',op=999,machine=0),
                dict(kind='receipt',op=0,machine=99),dict(kind='receipt',op=0,machine=0,parents=[999])):
            with self.subTest(extra=extra):
                data=deepcopy(base);data['records'].append(dict(extra,attempt='a',time=101))
                _,full,_=bind(data['contract'],data['attempts'],data['records'],50)
                reduced=list(direct_rows(data['contract'],data['attempts'],data['records'],50))
                self.assertEqual(reduced,[{k:full[0][k] for k in reduced[0]}])

    def test_invalid_attempt_boundaries_and_completion_are_rejected_consistently(self):
        for field,value in (('finished_at',-1),('finished_at',True),('started_at',-5),('observed_until',20)):
            with self.subTest(field=field,value=value):
                data=packet();data['attempts'][0][field]=value
                with self.assertRaises(ValueError):bind(data['contract'],data['attempts'],data['records'],50)
                with self.assertRaises(ValueError):list(direct_rows(data['contract'],data['attempts'],data['records'],50))

    def test_in_window_unknown_executor_is_rejected_by_both_paths(self):
        data=packet();data['records'].append(dict(attempt='a',kind='receipt',op=0,machine=99,time=5))
        with self.assertRaises(Unsupported):bind(data['contract'],data['attempts'],data['records'],50)
        with self.assertRaises(Unsupported):list(direct_rows(data['contract'],data['attempts'],data['records'],50))
