"""P27 discovery is read-only and cannot arm or confer production qualification."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from commissioning.bench import BenchController
from commissioning.bench_admission import collector_identity
from tests.test_bench_guard_p18 import IO, service, prepared
from tests.test_initial_configuration_p27 import initial_status


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.service=service();self.io=IO();self.io.words[0x1050]=0xa1b2c3d4
        self.status=initial_status();self.status['raw_words'][0]|=(1<<21)|(1<<10)
        self.status['raw_words'][24]=3000000;self.status['raw_words'][25]=25
        self.status['rpm_age_ms']=0
        self.service.public_state=lambda:dict(link='ONLINE',status_age_ms=1,control_words=[0]*24)
        self.bench=BenchController(self.service);self.service.bench=self.bench
        self.controller=SimpleNamespace(io=self.io)

    def discover(self):self.bench.poll(self.controller,self.status,1000.)

    def test_new_boot_discovers_without_receipt_and_never_writes(self):
        with patch('commissioning.bench.require_admission',side_effect=ValueError('NO_FILE')):
            self.discover()
            proof=self.bench.current_admission(collector_identity(self.service))
        self.assertEqual(proof['verification'],'READ_ONLY_P27_ABI2_CURRENT_COLLECTOR')
        self.assertEqual(self.io.reads,[0x1050,0x900,0x904,0x1050])
        self.assertEqual(self.io.writes,[])
        self.assertEqual(self.bench.snapshot()['state'],'IDLE')
        self.assertFalse(self.bench.snapshot()['controls_enabled'])
        self.assertFalse(self.status['configured'])

    def test_old_or_inconsistent_or_active_status_is_not_probed(self):
        for change in ('legacy','contradiction','pwm','configured','stale','missing_zero'):
            self.setUp()
            if change=='legacy':self.status['raw_words'][0]&=~((1<<19)|(1<<20)|(1<<21))
            elif change=='contradiction':self.status['raw_words'][0]&=~(1<<19)
            elif change=='pwm':self.status['applied_pwm_counts']=400
            elif change=='configured':self.status['configured']=True
            elif change=='stale':self.service.public_state=lambda:dict(status_age_ms=900,control_words=[0]*24)
            else:self.status['raw_words'][0]&=~(1<<21)
            self.discover()
            with self.subTest(change=change):
                self.assertEqual(self.io.reads,[]);self.assertEqual(self.io.writes,[])
                self.assertIsNone(self.bench.runtime_probe)

    def test_wrong_abi_or_reset_does_not_authorize(self):
        for address,value in ((0x900,0),(0x904,0x10000),(0x1050,1)):
            self.setUp();self.io.words[address]=value;self.discover()
            with self.subTest(address=address):
                self.assertIsNone(self.bench.runtime_probe);self.assertEqual(self.io.writes,[])
                with patch('commissioning.bench.require_admission',side_effect=ValueError('NO_FILE')):
                    with self.assertRaises(ValueError):self.bench.current_admission(collector_identity(self.service))

    def test_reconnect_requires_fresh_discovery(self):
        self.discover();first=copy.deepcopy(self.bench.runtime_probe)
        self.bench.lost_link(RuntimeError('link gone'));self.service.connection_epoch+=1
        with patch('commissioning.bench.require_admission',side_effect=ValueError('NO_FILE')):
            with self.assertRaises(ValueError):self.bench.current_admission(first['collector_boot'])
        self.discover()
        self.assertNotEqual(first['collector_boot'],self.bench.runtime_probe['collector_boot'])
        self.assertEqual(self.io.writes,[])

    def test_manual_bounded_start_and_heartbeat_loss_keep_protections(self):
        self.discover()
        with patch('commissioning.bench.time.monotonic',return_value=1000.):
            self.bench.request_start(prepared(),self.service.boot)
        self.bench.poll(self.controller,self.status,1000.)
        self.assertTrue(self.bench.snapshot()['controls_enabled'])
        count=len(self.io.writes)
        self.bench.poll(self.controller,self.status,1001.1)
        self.assertEqual(self.io.writes[count:],[(0x930,0)])
        self.assertEqual(self.bench.snapshot()['reason'],'BROWSER_HEARTBEAT_LOST')
        self.assertTrue(self.bench.snapshot()['output_stop_confirmed'])
        self.assertFalse(any(0x300<=a<0x360 or a==0x18 for a,v in self.io.writes))

    def test_runtime_probe_does_not_skip_per_poll_abi_readback(self):
        self.discover();self.io.words[0x904]=0x10000
        with patch('commissioning.bench.time.monotonic',return_value=1000.):
            self.bench.request_start(prepared(),self.service.boot)
        self.bench.poll(self.controller,self.status,1000.)
        self.assertEqual(self.bench.snapshot()['state'],'REJECTED')
        self.assertEqual(self.io.writes,[])


if __name__=='__main__':unittest.main()
