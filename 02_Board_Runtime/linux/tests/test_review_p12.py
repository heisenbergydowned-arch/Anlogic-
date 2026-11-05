"""Review counterexamples. Explicit unit fixtures; no hardware deployment."""
import copy,csv,io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from cabinet.protocol import Frame,FrameGate
from cabinet.input_policy import FAULT_POLICY,model_values
from commissioning.measure import evaluate_trace
from commissioning.fit import build,save
from commissioning.workbench import Workbench
from commissioning.bench import plan,BenchController
from test_commissioning_ready import dataset,SOURCE
from test_capture import packet,contract
CONTRACT=contract()

class ReviewFixes(unittest.TestCase):
    def test_fault_windows_are_opt_in_and_rpm_is_unknown_not_zero(self):
        original=packet(1,100)['frame'];h=list(original.header);h[19]=7;h[14]=0;h[15]=0x0800
        frame=Frame(tuple(h),original.values);c=dict(CONTRACT,input_policy=FAULT_POLICY)
        self.assertEqual(FrameGate(c).check(frame,100000),[])
        self.assertEqual(model_values(frame,c)[38],-32768)
        self.assertEqual(frame.values,original.values)
        self.assertIn('not_stable_run',FrameGate(CONTRACT).check(frame,100000))
        # Missing FG never excuses stale/calibration/bad current/bad pressure.
        for bit in (0x100,0x200,0x400,0x1000,0x10,0x20,0x4000,0x8000):
            hh=list(h);hh[15]|=bit
            self.assertTrue(FrameGate(c).check(Frame(tuple(hh),frame.values),100000))
        self.assertIn('stale_frame',FrameGate(c).check(frame,103000))
        h[15]=0;self.assertIn('process_count',FrameGate(c).check(Frame(tuple(h),frame.values),100000))
    def test_sparse_tail_does_not_pass(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'trace.csv'
            with p.open('w') as f:
                w=csv.writer(f);w.writerow('time_s,target_rpm,rpm,pwm_counts,temperature_C,setpoint_C,mode,valid,session_id,source'.split(','))
                for i in range(41):w.writerow([i*.5,1000,1005,1000,30,30,'RUN',1,'UNIT',SOURCE])
            with self.assertRaisesRegex(ValueError,'Ten continuous'):evaluate_trace(p,source=SOURCE)
    def test_socket_and_policy_are_preserved_in_fitted_package(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'data';dataset(root)
            base=json.loads((root/'base.json').read_text());base['parameter_control']={'enabled':False,'local_socket':'/run/cabinet-operator/custom.sock'};save(root/'base.json',base)
            build(root,root/'base.json',Path(d)/'out',allow_fixture=True)
            cfg=json.loads((Path(d)/'out/edge.armed.json').read_text())
            self.assertEqual(cfg['parameter_control']['local_socket'],'/run/cabinet-operator/custom.sock')
            self.assertEqual(cfg['contract']['input_policy'],FAULT_POLICY)
    def test_workbench_stale_edits_and_offline_actuation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'base.json';save(base,{'device_id':'UNIT'})
            work=Workbench(Path(d)/'work',base);s=work.status()
            self.assertEqual(s['mode'],'LOCAL_FILES_ONLY');self.assertFalse(s['bench']['controls_enabled'])
            doc=json.loads(s['documents']['settings.json']);doc['fan_id']='UNIT'
            result=work.action('inputs',dict(revision=s['revision'],name='settings.json',content=json.dumps(doc)))
            self.assertNotEqual(result['revision'],s['revision'])
            with self.assertRaisesRegex(ValueError,'REVISION'):work.action('inputs',dict(revision=s['revision'],name='settings.json',content=json.dumps(doc)))
            with self.assertRaises(ValueError):work.action('point',dict(revision=work.revision(),channel='current',reference=1,split='fit',seconds=5))
            with self.assertRaises(ValueError):work.action('bench-start',dict(preview_id='x',start_controlled_trial=True))
            self.assertTrue(work.archive().startswith(b'PK'))
    def test_unreviewed_and_unbounded_bench_plans_rejected(self):
        from commissioning.workbench import BENCH
        with self.assertRaises(ValueError):plan(BENCH)
        p=copy.deepcopy(BENCH);p['profile'].update(operator='UNIT',reference_evidence_sha256='a'*64,wiring_verified=True,zero_pwm_not_poweroff_confirmed=True,
            max_duty_percent=30,current_zero_code=3000,current_trip_distance_code=500,temperature_trip_C=40,minimum_fg_period_clocks=100000,duration_limit_s=5)
        p['steps']=[dict(duty_percent=20,seconds=2)]
        self.assertEqual(plan(p)['words'],[1200,3000,500,640,100000,5000])
        p['steps'][0]['seconds']=8
        with self.assertRaises(ValueError):plan(p)

if __name__=='__main__':unittest.main()

class BenchOwnerTests(unittest.TestCase):
    def test_old_firmware_cannot_arm_and_owner_stops_on_lost_browser(self):
        from types import SimpleNamespace
        from commissioning.workbench import BENCH
        class IO:
            def __init__(self):
                self.words={0x900:0,0x904:0x10000,0x908:0,0x538:400,0x554:1000,0x558:12000000};self.writes=[]
            def read(self,a):return self.words.get(a,0)
            def write(self,a,v):
                self.writes.append((a,v));self.words[a]=v
                if a==0x928:self.words[0x908]=5
                if a==0x930:self.words[0x908]=0;self.words[0x934]=0
                if a==0x92c:self.words[0x934]=v
        io=IO();journal=[]
        service=SimpleNamespace(mock=False,diagnostic_test=False,config={'control':{'enabled':False}},boot='UNIT/boot',recorder=None,
            collector_session='11111111-1111-4111-8111-111111111111',connection_epoch=1,
            public_state=lambda:{'link':'ONLINE'},put_journal=lambda row:journal.append(row) or True)
        bench=BenchController(service,admission_check=lambda boot:{'test_fixture_admission':True})
        p=copy.deepcopy(BENCH);p['profile'].update(operator='UNIT',reference_evidence_sha256='a'*64,wiring_verified=True,zero_pwm_not_poweroff_confirmed=True,
            max_duty_percent=30,current_zero_code=3000,current_trip_distance_code=500,temperature_trip_C=40,minimum_fg_period_clocks=100000,duration_limit_s=5)
        p['steps']=[dict(duty_percent=20,seconds=2)]
        raw=[0x8400]+[0]*31;raw[1]=100;raw[8]=1000;raw[22]=3000;raw[24]=1000000
        status=dict(configured=False,configuration_id=0,applied_pwm_counts=0,raw_words=raw,latched=[],uptime_ms=100,
                    rpm_age_ms=0,input_validity={'rpm':True},measured_rpm=1000,temp_raw_1_16_C=400)
        ctrl=SimpleNamespace(io=io);prepared=plan(p)
        bench.request_start(prepared,service.boot);now=time.monotonic();bench.poll(ctrl,status,now)
        self.assertEqual(io.writes,[]);self.assertEqual(bench.snapshot()['state'],'REJECTED')
        io.words[0x900]=0x424e4331;io.words[0x904]=0x20000
        bench.request_start(prepared,service.boot);now=time.monotonic();bench.poll(ctrl,status,now)
        self.assertTrue(bench.snapshot()['controls_enabled']);self.assertEqual(bench.snapshot()['records'][0]['rpm'],1000)
        self.assertIs(bench.snapshot()['records'][0]['rpm_calibrated'],False)
        bench.poll(ctrl,status,now+1.1)
        self.assertEqual(bench.snapshot()['reason'],'BROWSER_HEARTBEAT_LOST');self.assertFalse(bench.snapshot()['controls_enabled'])
        self.assertEqual(io.writes[-1],(0x930,0));self.assertEqual(journal[0][0],'bench_trace')
