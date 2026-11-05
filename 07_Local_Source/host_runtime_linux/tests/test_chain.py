import copy
import json
import math
from pathlib import Path
import struct
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from cabinet.protocol import Frame,FrameGate,elapsed32
from cabinet.mock import MockController
from cabinet.model import Model
from cabinet.policy import Fusion,TemperatureLoop
from cabinet.service import Service
from cabinet.store import Store,EventTracker
from cabinet.uplink import Uplink
from cabinet.web import server

CONFIG=json.loads((Path(__file__).resolve().parents[1]/'config.example.json').read_text('utf-8'))

def real_frame():
    mock=MockController();mock.status();f=mock.frame();h=list(f.header);h[15]=0;h[17]=1;h[27]=0
    return Frame(tuple(h),f.values)

class GateTests(unittest.TestCase):
    def gate(self):return FrameGate(dict(CONFIG['contract'],calibration_id=1))
    def test_versions_quality_age_and_sequence(self):
        f=real_frame();g=self.gate();self.assertEqual(g.check(f,f.header[4]),[])
        self.assertIn('duplicate_or_reordered',g.check(f,f.header[4]))
        self.assertIn('stale_frame',self.gate().check(f,f.header[4]+1001))
        for index,value,reason in [(16,2,'feature_config'),(17,0,'calibration'),(19,4,'not_stable_run'),(11,1023,'sample_count'),(15,4,'quality'),(9,100,'rate_a')]:
            h=list(f.header);h[index]=value;self.assertIn(reason,self.gate().check(Frame(tuple(h),f.values),h[4]))
    def test_nan_and_length(self):
        f=real_frame();words=list(struct.unpack('<39I',struct.pack('<39f',*f.values)));words[9]=0x7fc00000
        with self.assertRaises(ValueError):Frame.from_words(list(f.header),words)
        with self.assertRaises(ValueError):Frame.from_words(list(f.header),words[:-1])
    def test_wrap_and_test_source(self):
        self.assertEqual(elapsed32(2,0xfffffffd),5)
        m=MockController();m.status();f=m.frame()
        self.assertIn('test_frame',self.gate().check(f,f.header[4]))
        self.assertEqual(self.gate().check(f,f.header[4],diagnostic_test=True),[])

class PolicyTests(unittest.TestCase):
    def test_physical_priority_and_confirm_time(self):
        m=MockController();status=m.status();status['alarm_level']=3;status['latched']=['OC_HARD'];status['fan_action']='INHIBIT'
        fusion=Fusion({'confirm_ms':500,'confidence_min':0.8})
        normal=dict(label='normal',confidence=.99)
        decision=fusion.evaluate(normal,status,100,formal=True)
        self.assertEqual(decision['level'],3);self.assertEqual(decision['fan_action'],'INHIBIT');self.assertFalse(decision['buzzer_requested'])
        abnormal=dict(label='imbalance',confidence=.99)
        self.assertEqual(fusion.evaluate(abnormal,status,200,formal=True)['model_state'],'CANDIDATE')
        self.assertEqual(fusion.evaluate(abnormal,status,500,formal=True)['model_state'],'CANDIDATE')
        self.assertEqual(fusion.evaluate(abnormal,status,800,formal=True)['model_state'],'CONFIRMED_MAINTENANCE')
        self.assertEqual(fusion.evaluate(None,status,900)['level'],3)
    def test_outer_loop_requires_calibration(self):
        with self.assertRaises(ValueError):TemperatureLoop({'enabled':True})
        self.assertIsNone(TemperatureLoop({'enabled':False}).update({},0))
        config=dict(enabled=True,qualified=True,evidence='unit-test vector only',setpoint_C=30,kp_rpm_per_C=100,
                    ki_rpm_per_C_s=10,rpm_min=1000,rpm_max=6000,slew_rpm_per_s=500,temp_age_ms=2000)
        loop=TemperatureLoop(config);m=MockController();status=m.status();status['temp_raw_1_16_C']=60*16
        a=loop.update(status,0);b=loop.update(status,.1);self.assertLessEqual(abs(b-a),50)
        status['active']=['FG_LOSS'];self.assertIsNone(loop.update(status,.2))
    def test_wrong_model_result_and_timeout(self):
        f=real_frame();base=dict(backend='command',model_id='m1',timeout_ms=50)
        wrong="import json,sys;x=json.load(sys.stdin);x['frame_id']+=1;x['probabilities']=[1,0,0,0,0];print(json.dumps(x))"
        with self.assertRaises(ValueError):Model(dict(base,timeout_ms=2000,command=[sys.executable,'-c',wrong])).infer(f)
        slow="import time;time.sleep(.5)"
        with self.assertRaises(subprocess.TimeoutExpired):Model(dict(base,command=[sys.executable,'-c',slow])).infer(f)
        valid="import json,sys;x=json.load(sys.stdin);x['probabilities']=[1,0,0,0,0];print(json.dumps(x))"
        result=Model(dict(base,timeout_ms=500,command=[sys.executable,'-c',valid])).infer(f)
        self.assertEqual(result['frame_id'],f.id);self.assertEqual(result['label'],'normal')

class PersistenceTests(unittest.TestCase):
    def test_candidate_confirmation_and_recovery_publish(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'c.sqlite');status=MockController().status();tracker=EventTracker(s,'d1','b1')
            tracker.update('imbalance',0,True,status,source='MODEL',notify=False)
            self.assertEqual(s.events()[0]['state'],'OBSERVING');self.assertEqual(s.pending(),[])
            tracker.update('imbalance',1,True,status,source='MODEL',notify=True)
            self.assertEqual(s.events()[0]['state'],'ACTIVE');self.assertEqual(len(s.pending()),1)
            event=s.events()[0];s.acknowledge(event['event_id'])
            tracker.update('imbalance',0,False,status,source='MODEL',notify=False)
            e=s.events()[0];self.assertTrue(e['acknowledged']);self.assertTrue(e['notify']);self.assertEqual(e['severity_peak'],1)
            self.assertEqual(e['state'],'RECOVERED');self.assertEqual(e['event_revision'],4);s.close()
    def test_uplink_priority_and_no_repeated_candidate_updates(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'p.sqlite');tracker=EventTracker(s,'d','b');status=MockController().status()
            tracker.update('maintenance',1,True,status);tracker.update('OC_HARD',3,True,status)
            self.assertEqual(s.pending()[0]['payload']['code'],'OC_HARD')
            tracker.update('imbalance',1,True,status,source='MODEL',notify=True)
            tracker.update('imbalance',0,True,status,source='MODEL',notify=False)
            count=len(s.pending());tracker.update('imbalance',0,True,status,source='MODEL',notify=False)
            self.assertEqual(len(s.pending()),count);s.close()
    def test_event_recovery_peak_and_platform_reordering(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'events.sqlite');m=MockController();status=m.status();tracker=EventTracker(s,'d1','b1')
            tracker.update('TEMP_HARD',3,True,status);tracker.update('TEMP_HARD',3,True,status)
            self.assertEqual(len(s.events()),1);first=s.events()[0]
            tracker.update('TEMP_HARD',0,False,status);recovered=s.events()[0]
            self.assertEqual(recovered['event_revision'],2);self.assertEqual(recovered['severity_peak'],3)
            s.receive(recovered);s.receive(first);s.receive(recovered)
            self.assertEqual(s.received()[0]['state'],'RECOVERED');self.assertEqual(len(s.received()),1)
            self.assertEqual(len(s.pending()),2);s.close()
            s=Store(Path(d)/'events.sqlite');s.reset_retry_clock();self.assertEqual(len(s.pending()),2);s.close()
    def test_journal_failure_retains_pl_fifo(self):
        with tempfile.TemporaryDirectory() as d:
            c=copy.deepcopy(CONFIG);c['database']=str(Path(d)/'service.sqlite');c['poll_ms']=20;c['model']['backend']='mock'
            mock=MockController();mock.fifo=[[1,2,3,4,5,6,7,8]];service=Service(c,mock=True,controller=mock)
            original=service.store.fifo;service.store.fifo=lambda *_:(_ for _ in ()).throw(OSError('disk full'))
            service.start();time.sleep(.15)
            self.assertEqual(len(mock.fifo),1);self.assertFalse(any(op==8 for op,_ in mock.commands))
            service.store.fifo=original
            for _ in range(50):
                if not mock.fifo:break
                time.sleep(.02)
            self.assertEqual(mock.fifo,[]);service.close()

class WholeServiceTests(unittest.TestCase):
    def test_persistent_npu_contract_and_latched_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'npu.sock');root=Path(__file__).resolve().parents[1]
            for delay in [0,150]:
                with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                p=subprocess.Popen([sys.executable,str(root/'npu_server.py'),'--mock','--socket',path,
                                    '--model-id','m1','--feature-config-id','1','--calibration-id','1',
                                    '--tcp-port',str(port),'--timeout-ms','50','--mock-delay-ms',str(delay)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
                try:
                    ready=False
                    # A spawned Python worker can start slowly on WSL /mnt/d.
                    # This is initialization, separate from the 50 ms job deadline.
                    deadline=time.monotonic()+10
                    while time.monotonic()<deadline:
                        if p.poll() is not None:self.fail(p.communicate()[1])
                        try:
                            with socket.create_connection(('127.0.0.1',port),timeout=.05):ready=True;break
                        except OSError:pass
                        time.sleep(.02)
                    if not ready:
                        p.terminate();out,err=p.communicate(timeout=3)
                        self.fail('NPU listener did not start: '+out+err)
                    c=dict(backend='tcp',port=port,model_id='m1',timeout_ms=500)
                    if delay:
                        with self.assertRaisesRegex(RuntimeError,'timeout latched'):Model(c).infer(real_frame())
                        with self.assertRaisesRegex(RuntimeError,'timeout latched'):Model(c).infer(real_frame())
                    else:
                        result=Model(c).infer(real_frame());self.assertTrue(result['test']);self.assertEqual(result['label'],'normal')
                        with self.assertRaisesRegex(RuntimeError,'contract mismatch'):Model(dict(c,model_id='wrong')).infer(real_frame())
                finally:
                    p.terminate();p.communicate(timeout=3)
                    try:Path(path).unlink()
                    except FileNotFoundError:pass
    def test_frame_model_events_hmi_and_offline_retry(self):
        with tempfile.TemporaryDirectory() as d:
            c=copy.deepcopy(CONFIG);c['database']=str(Path(d)/'chain.sqlite');c['poll_ms']=20;c['model']['backend']='mock';c['model']['model_id']='mock-v1'
            service=Service(c,mock=True);http=server('127.0.0.1',0,service,collector=True)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();port=http.server_address[1]
            service.start()
            try:
                for _ in range(100):
                    if service.public_state().get('model') and service.store.pending():break
                    time.sleep(.02)
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=2) as response:state=json.load(response)
                self.assertEqual(state['link'],'ONLINE');self.assertTrue(state['test']);self.assertIsNotNone(state['frame']);self.assertIsNotNone(state['model'])
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=2) as response:self.assertIn('机柜风冷'.encode(),response.read())
                events=service.store.events();self.assertTrue(events)
                # Network outage keeps the journal/outbox, without stopping I/O.
                upload=Uplink({'url':'http://127.0.0.1:1/v1/devices/events','loopback_test':True,'timeout_s':.1},service.store)
                pending=len(service.store.pending());self.assertEqual(upload.once(),0);self.assertIsNotNone(upload.last_error)
                self.assertGreaterEqual(len(service.store.pending()),pending-1)
                service.store.reset_retry_clock()
                upload=Uplink({'url':f'http://127.0.0.1:{port}/v1/devices/events','loopback_test':True},service.store)
                self.assertGreater(upload.once(),0);self.assertTrue(service.store.received())
                event=service.store.events()[0]
                request=urllib.request.Request(f'http://127.0.0.1:{port}/api/ack',data=json.dumps({'event_id':event['event_id']}).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=2) as response:ack=json.load(response)
                self.assertTrue(ack['acknowledged']);self.assertFalse(any(op in (1,2) for op,_ in service.controller.commands))
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as response:self.assertTrue(json.load(response)['alive'])
            finally:
                http.shutdown();http.server_close();thread.join(timeout=2);service.close()
    def test_inference_timeout_does_not_block_status(self):
        with tempfile.TemporaryDirectory() as d:
            c=copy.deepcopy(CONFIG);c['database']=str(Path(d)/'timeout.sqlite');c['poll_ms']=20
            c['model'].update(backend='command',command=[sys.executable,'-c','import time;time.sleep(1)'],timeout_ms=40)
            service=Service(c,mock=True);service.start();time.sleep(.35)
            state=service.public_state();self.assertEqual(state['link'],'ONLINE');self.assertGreater(state['status']['uptime_ms'],500)
            self.assertEqual(state['decision']['model_state'],'UNAVAILABLE');service.close()
    def test_network_and_live_control_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'s.sqlite')
            with self.assertRaises(ValueError):Uplink({'url':'http://example.com/events'},s)
            s.close()
            c=copy.deepcopy(CONFIG);c['database']=str(Path(d)/'s2.sqlite');c['control']['enabled']=True
            with self.assertRaises(ValueError):Service(c,mock=True)

if __name__=='__main__':unittest.main()
