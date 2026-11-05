"""Bounded realtime snapshots; complete and independently mutable trace export."""
import unittest
from commissioning.bench import BenchController
from tests.test_bench_guard_p18 import service


class NoTraversal(list):
    def __iter__(self):raise AssertionError('Realtime path traversed full trace')
    def __deepcopy__(self,memo):raise AssertionError('Realtime path copied full trace')


class BenchTraceCost(unittest.TestCase):
    def setUp(self):
        self.bench=BenchController(service(),admission_check=lambda identity:{})
        self.bench.state.update(plan={'steps':[{'duty_percent':20,'seconds':2}]},
            records=[{'time_s':i/100.,'rpm':1000+i,'source':'REAL','fg_valid':True} for i in range(1000)])

    def test_collector_summary_never_traverses_trace(self):
        self.bench.state['records']=NoTraversal(self.bench.state['records'])
        result=self.bench.snapshot(record_limit=0)
        self.assertEqual(result['records'],[])
        self.assertEqual(result['record_count'],1000)
        self.assertTrue(result['records_truncated'])

    def test_heartbeat_copies_only_latest_rows_but_keeps_complete_evidence(self):
        self.bench.state['records']=NoTraversal(self.bench.state['records'])
        self.bench.active={'id':'trial'}
        result=self.bench.heartbeat('trial')
        self.assertEqual(len(result['records']),8)
        self.assertEqual(result['records'][0]['rpm'],1992)
        self.assertEqual(result['record_count'],1000)
        self.assertEqual(len(self.bench.state['records']),1000)

    def test_public_mutations_cannot_change_trace_or_plan(self):
        result=self.bench.snapshot()
        self.assertEqual(len(result['records']),1000)
        self.assertFalse(result['records_truncated'])
        result['records'][0]['rpm']=1
        result['plan']['steps'][0]['duty_percent']=99
        result['records'].clear()
        self.assertEqual(self.bench.state['records'][0]['rpm'],1000)
        self.assertEqual(self.bench.state['plan']['steps'][0]['duty_percent'],20)
        self.assertEqual(len(self.bench.state['records']),1000)

    def test_bad_limit_never_silently_returns_unbounded_history(self):
        for value in (-1,True,1.5,'8'):
            with self.assertRaises(ValueError):self.bench.snapshot(record_limit=value)


if __name__=='__main__':unittest.main()
