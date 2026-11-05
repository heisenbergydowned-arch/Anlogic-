import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from link_cli import pack_feature,commit_feature
from cabinet.mock import MockController
from cabinet.policy import Fusion
from cabinet.service import Service
from cabinet.store import EventTracker

ROOT=Path(__file__).resolve().parents[1]

class CommissionTests(unittest.TestCase):
    def test_atomic_feature_commit_and_invalid_contracts(self):
        c=json.loads((ROOT/'feature_config.example.json').read_text('utf-8'))
        words=pack_feature(c);self.assertEqual(len(words),17);self.assertEqual(words[8],1);self.assertEqual(words[-1],513)
        for key,value in [('qualified',1),('ppr',0),('current_gain_q30',0),('edges',[1]*9),('feature_config_id',True)]:
            bad=dict(c);bad[key]=value
            with self.assertRaises(ValueError):pack_feature(bad)
        bad=dict(c,qualified=True,calibration_id=0,evidence='test only')
        with self.assertRaises(ValueError):pack_feature(bad)
        class Registers:
            def __init__(self):self.r={0x1020:1,0x1024:0};self.staged={};self.busy=2;self.commits=0
            def read(self,a):
                if a==0x1008:
                    self.busy-=1;return 0x10 if self.busy>=0 else 0
                return self.r.get(a,0)
            def write(self,a,v):
                if a==0x1040:
                    self.commits+=1;self.r[0x1020]=self.staged[0x1300];self.r[0x1024]=self.staged[0x1304]
                else:self.staged[a]=v
        ctrl=type('Controller',(),{'io':Registers()})()
        commit_feature(ctrl,words);self.assertEqual(ctrl.io.commits,1)
        self.assertEqual([ctrl.io.staged[0x1300+4*i] for i in range(17)],words)
        with self.assertRaises(ValueError):commit_feature(ctrl,words)
    def test_unqualified_model_stays_observation(self):
        status=MockController().status();fusion=Fusion({'confirm_ms':10,'confidence_min':.8})
        result=dict(label='imbalance',confidence=.99,test=True)
        for t in (0,100):
            decision=fusion.evaluate(result,status,t,formal=False)
            self.assertEqual(decision['level'],status['alarm_level']);self.assertEqual(decision['model_state'],'TEST_OBSERVATION')
            self.assertFalse(decision['buzzer_requested'])
        result['test']=False
        self.assertEqual(fusion.evaluate(result,status,200,formal=True)['model_state'],'CANDIDATE')
        self.assertEqual(fusion.evaluate(result,status,1000,formal=True)['model_state'],'CANDIDATE')
    def test_stale_state_and_durable_short_fault(self):
        with tempfile.TemporaryDirectory() as d:
            c=json.loads((ROOT/'config.example.json').read_text('utf-8'));c['database']=str(Path(d)/'c.db')
            service=Service(c,mock=True);status=MockController().status()
            service.set(link='ONLINE',status=status,model={'frame_end_ms':0})
            service.updated=time.monotonic()-3
            state=service.public_state();self.assertEqual(state['link'],'OFFLINE');self.assertIsNone(state['model'])
            words=[7,123,8,0,3|(2<<9)|(1<<6),8,1,0]
            event=service.fifo_event('b1',words)
            service.store.fifo('b1/7',words,event);service.store.fifo('b1/7',words,event)
            self.assertEqual(len(service.store.pending()),1)
            saved=service.store.events()[0];self.assertEqual(saved['severity_peak'],3)
            self.assertIn('TEMP_HARD',saved['active_causes']);self.assertEqual(saved['state'],'RECORDED')
            tracker=service.link_tracker;tracker.update('PL_LINK_LOSS',1,True,status,source='SYSTEM')
            tracker.update('PL_LINK_LOSS',0,False,status,source='SYSTEM')
            self.assertEqual(service.store.events()[0]['state'],'RECOVERED');service.close()

if __name__=='__main__':unittest.main()
