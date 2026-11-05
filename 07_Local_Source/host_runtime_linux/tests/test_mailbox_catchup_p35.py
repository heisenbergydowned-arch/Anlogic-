"""Exercise the hardware worker with a synthetic queued-frame controller."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cabinet.service import Service
from tests.test_local_display import CONFIG,CountingController
from tests.test_initial_configuration_p27 import initial_status


class StopAfterPolls:
    def __init__(self,count):self.count=count;self.waits=[];self.done=False
    def is_set(self):return self.done
    def set(self):self.done=True
    def wait(self,timeout):
        self.waits.append(timeout)
        self.done=len(self.waits)>=self.count
        return self.done


class MailboxCatchupTests(unittest.TestCase):
    def run_worker(self,depths,empty=False):
        with tempfile.TemporaryDirectory() as td:
            cfg=copy.deepcopy(CONFIG);cfg['database']=str(Path(td)/'events.db')
            cfg['control']['enabled']=False;cfg['poll_ms']=64
            ctl=CountingController();ctl.io=SimpleNamespace(read=lambda address:123 if address==0x1050 else 0)
            ctl.status=lambda:copy.deepcopy(initial_status())
            if empty:ctl.frame=lambda:None
            observed=[]
            observer=SimpleNamespace(submit=lambda packet:observed.append(packet))
            svc=Service(cfg,controller=ctl,observer=observer);svc.stop=StopAfterPolls(len(depths))
            try:
                with patch('cabinet.service.read_control_words',return_value=[0]*24), \
                     patch('cabinet.service.read_feature_configuration',return_value=[1,0,0]+[0]*14), \
                     patch('cabinet.service.read_mailbox',side_effect=[dict(queued_frames=d,dropped_frames=0) for d in depths]):
                    svc.io_loop()
                self.assertEqual(svc.public_state()['link'],'ONLINE',svc.public_state().get('error'))
                return svc.stop.waits,observed
            finally:svc.store.close()

    def test_backlog_is_delivered_in_order_before_normal_idle_pause(self):
        waits,packets=self.run_worker([2,2,1])
        self.assertEqual(waits,[0,0,.064])
        self.assertEqual([p['sequence'] for p in packets],[1,2,3])
        self.assertEqual([p['frame'].header[3] for p in packets],[1,2,3])
        self.assertTrue(all(p['received_at']>0 for p in packets))

    def test_empty_or_single_frame_keeps_the_configured_interval(self):
        self.assertEqual(self.run_worker([1,0])[0],[.064,.064])

    def test_empty_read_cannot_create_a_busy_loop_even_if_count_was_two(self):
        waits,packets=self.run_worker([2],empty=True)
        self.assertEqual(waits,[.064])
        self.assertIsNone(packets[0]['frame'])


if __name__=='__main__':unittest.main()
