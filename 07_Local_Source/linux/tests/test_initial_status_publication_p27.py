"""Exercise the real collector loop/public_state using synthetic controller I/O."""
import copy,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from cabinet.service import Service
from commissioning.configuration_permission import configuration_policy
from tests.test_local_display import CONFIG,CountingController
from tests.test_initial_configuration_p27 import initial_status

class PublicReadbackTests(unittest.TestCase):
 def test_real_service_publishes_same_sample_readback_without_new_mmio_owner(self):
  with tempfile.TemporaryDirectory() as td:
   cfg=copy.deepcopy(CONFIG);cfg['database']=str(Path(td)/'events.db');cfg['control']['enabled']=False
   ctl=CountingController();ctl.io=SimpleNamespace(read=lambda address:123 if address==0x1050 else 0)
   ctl.status=lambda:copy.deepcopy(initial_status())
   cw=[0]*24;fw=[1,0,0]+[0]*14;observed=[]
   class Observer:
    def submit(self,p):observed.append(p);svc.stop.set()
   svc=Service(cfg,controller=ctl,observer=Observer())
   try:
    with patch('cabinet.service.read_control_words',return_value=cw),patch('cabinet.service.read_feature_configuration',return_value=fw),patch('cabinet.service.read_mailbox',return_value={'queued_frames':0,'dropped_frames':0}):svc.io_loop()
    state=svc.public_state();self.assertTrue(observed);self.assertEqual(state['link'],'ONLINE',state.get('error'))
    self.assertEqual(state['control_words'],cw);self.assertEqual(state['feature_words'],fw)
    result=configuration_policy(state['status'],state['control_words'],state['status_age_ms'])
    self.assertTrue(result['remote_initial_configuration_ready']);self.assertFalse(result['local_permission'])
    cw[0]=99;fw[0]=99
    self.assertEqual(svc.public_state()['control_words'][0],0);self.assertEqual(svc.public_state()['feature_words'][0],1)
   finally:svc.store.close()
 def test_status_config_id_conflict_prevents_a_fresh_eligible_publication(self):
  with tempfile.TemporaryDirectory() as td:
   cfg=copy.deepcopy(CONFIG);cfg['database']=str(Path(td)/'events.db');cfg['control']['enabled']=False
   ctl=CountingController();ctl.io=SimpleNamespace(read=lambda address:123 if address==0x1050 else 0)
   bad=initial_status();bad['raw_words'][0]&=~(1<<20);bad['configuration_id']=99;bad['raw_words'][18]=99;ctl.status=lambda:copy.deepcopy(bad)
   svc=Service(cfg,controller=ctl);original=svc.set
   def update(**values):
    original(**values)
    if values.get('link')=='OFFLINE':svc.stop.set()
   svc.set=update
   try:
    with patch('cabinet.service.read_control_words',return_value=[0]*24),patch('cabinet.service.read_feature_configuration',return_value=[1,0,0]+[0]*14),patch('cabinet.service.read_mailbox',return_value={'queued_frames':0,'dropped_frames':0}):svc.io_loop()
    state=svc.public_state();self.assertEqual(state['link'],'OFFLINE');self.assertIn('identity mismatch',state['error'])
   finally:svc.store.close()
if __name__=='__main__':unittest.main(verbosity=2)
