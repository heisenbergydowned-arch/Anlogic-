"""Reader-clock races and unchanged source freshness/identity boundaries."""
import copy
import json
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from normal_npu.core import FEATURES, GROUPS, live_input
from normal_npu.presentation import fields


class NormalNpuFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'npu.json'
        self.contract=dict(device_id='fixture-device',configuration_words=[1,0,2]+[0]*14,
            frame_identity=[1,0,2],controller_mode='STOPPING',controller_diagnostic_mode=True)
        h=[0]*32;h[:5]=[0x46524d31,0x10000,284,7,1000000]
        start=1000000*100000-25575000;end=1000000*100000
        h[5:9]=[start&0xffffffff,start>>32,end&0xffffffff,end>>32]
        h[9:13]=[25575000,25575000,1024,1024];h[15]=0x3000
        h[16:19]=[1,0,2];h[21]=100000000;h[26]=0x202610f7
        self.sample=dict(link='ONLINE',received_at=1000.,boot='fixture-device/session/1',
            feature_words=self.contract['configuration_words'],
            status=dict(mode='STOPPING',test_mode=True,uptime_ms=1000000,active=[],latched=[],
                        configured=False,hard_inhibit=True,applied_pwm_counts=0,requested_rpm=0,
                        input_validity=dict(rpm=True,adc=True,temperature=True,pressure=True)),
            bench=dict(state='IDLE',controls_enabled=False,output_never_applied=True),
            normal_reference_guard=dict(schema='cabinet-normal-reference-output-v1',
                boot='fixture-device/session/1',state='IDLE',safe_since_uptime_ms=999000,
                status_uptime_ms=1000000,bench_state='IDLE',bench_id=None),
            frame=dict(state='RECEIVED_REAL',header=h,values={name:0. for name in FEATURES}),
            icm_diagnostics=dict(state='DIAGNOSTIC_ONLY',test=False,boot_id='fixture-device',snapshot_age_ms=0,
                sensors=[dict(channel=c,who=0x12,raw=[1,2,3],fresh=True,error=False,
                              config_verified=True,config_bad_mask=0,sample_age_ms=0) for c in ('A','B')]))
        self.result=dict(schema='cabinet-normal-npu-live-v1',backend='Alnpu',
            model_source='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC',formal=False,control_authority='NONE',
            fault_classes_trained=[],input_contract=self.contract,os_boot_id='os-boot',updated_at=1000.01,
            valid=True,status='RUNNING',collector_boot=self.sample['boot'],received_at=1000.,
            frame_end_ms=1000000,frame_start_cycles=start,source='REAL_CURRENT_SENSOR_FRAME',quality=0x3000,
            score=.25,execute_ms=.4,group_scores={name:.25 for name in GROUPS},state='BASELINE_MATCH',
            domain_score=.5,input_clipped=0,inference_count=3,training_rows=700)
        self.write_result()

    def write_result(self):
        self.path.write_text(json.dumps(self.result));self.path.chmod(0o600)

    def display(self,clock=None):
        return fields(self.sample,1000.,self.path,'os-boot',clock=clock)

    def test_publication_during_packet_processing_uses_read_end_clock(self):
        # The original explicit packet-processing time predates this real
        # publication. Do not clamp its negative age to zero or change its stamp.
        self.assertEqual(self.display()['panel_nn_valid'],'0')
        read_finished=[];load=json.load
        def read(stream):
            d=load(stream);read_finished.append(True);return d
        def clock():
            self.assertTrue(read_finished);return 1000.02
        with patch('normal_npu.presentation.json.load',side_effect=read):out=self.display(clock)
        self.assertEqual(out['panel_nn_valid'],'1')
        self.assertEqual(out['panel_nn_deadline_ms'],'1001000')
        self.assertEqual(json.loads(self.path.read_text()),self.result)

    def test_actual_future_publication_is_still_rejected(self):
        self.assertEqual(self.display(lambda:1000.005)['panel_nn_valid'],'0')
        self.result['received_at']=1000.03;self.write_result()
        self.assertEqual(self.display(lambda:1000.02)['panel_nn_valid'],'0')

    def test_read_end_clock_does_not_extend_source_or_result_expiry(self):
        self.assertEqual(self.display(lambda:1001.02)['panel_nn_valid'],'0')
        self.result['updated_at']=1001.09;self.write_result()
        self.assertEqual(self.display(lambda:1001.1)['panel_nn_valid'],'0')

    def test_display_lifetime_includes_age_of_the_physical_fpga_frame(self):
        self.result['frame_end_ms']=999400
        self.result['frame_start_cycles']=999144*100000
        self.write_result()
        out=self.display(lambda:1000.2)
        self.assertEqual(out['panel_nn_valid'],'1')
        self.assertEqual(out['panel_nn_deadline_ms'],'1000400')
        self.assertEqual(self.display(lambda:1000.401)['panel_nn_valid'],'0')
        # A newly published status advances both clocks, not the frame expiry.
        self.sample['received_at']=1000.2
        self.sample['status']['uptime_ms']=1000200
        self.sample['normal_reference_guard']['status_uptime_ms']=1000200
        self.assertEqual(self.display(lambda:1000.3)['panel_nn_deadline_ms'],'1000400')

    def test_producer_deadline_is_immutable_and_cannot_extend_the_display(self):
        self.result['input_deadline']=1000.3;self.write_result()
        self.assertEqual(self.display(lambda:1000.2)['panel_nn_deadline_ms'],'1000300')
        self.result['updated_at']=1000.4;self.write_result()
        self.assertEqual(self.display(lambda:1000.401)['panel_nn_valid'],'0')
        self.result['input_deadline']=1001.1;self.write_result()
        self.assertEqual(self.display(lambda:1000.5)['panel_nn_valid'],'0')

    def test_live_input_deadline_subtracts_existing_window_age(self):
        self.sample['status']['uptime_ms']=1000650
        self.sample['normal_reference_guard']['status_uptime_ms']=1000650
        _,identity=live_input(dict(observation=self.sample),1000.02,self.contract)
        self.assertAlmostEqual(identity['input_deadline'],1000.35)

    def test_boot_sensor_and_frame_time_boundaries_are_unchanged(self):
        for change in ('os_boot','collector_boot','pressure','icm','future_frame','old_frame'):
            with self.subTest(change=change):
                result=copy.deepcopy(self.result);sample=copy.deepcopy(self.sample)
                if change=='os_boot':result['os_boot_id']='wrong'
                elif change=='collector_boot':result['collector_boot']='fixture-device/other'
                elif change=='pressure':sample['status']['input_validity']['pressure']=False
                elif change=='icm':sample['icm_diagnostics']['sensors'][1]['fresh']=False
                elif change=='future_frame':result['frame_end_ms']=1000001
                elif change=='old_frame':result['frame_end_ms']=999499
                self.path.write_text(json.dumps(result))
                self.assertEqual(fields(sample,1000.,self.path,'os-boot',clock=lambda:1000.02)['panel_nn_valid'],'0')

    def test_real_future_collector_timestamp_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'COLLECTOR_STALE'):
            live_input(dict(observation=self.sample),999.999,self.contract)
        live_input(dict(observation=self.sample),1000.001,self.contract)

    def test_live_loop_checks_a_publication_against_clock_after_read(self):
        from normal_npu import live
        now=[1000.];reads=[0];handlers={};published=[]
        norm=dict(mean=[0.]*39,scale=[1.]*39,input_scale=1.,input_zero_point=128,
                  output_scale=1.,output_zero_point=128)
        bundle=SimpleNamespace(expected=self.contract,norm=norm,
            thresholds=dict(group_rmse={k:1. for k in GROUPS},abs_z_limit=[5.]*39),
            manifest=dict(model_id='fixture',source='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC',training_rows=700),
            provenance=dict(sessions={k:dict(session_ids=[k],rows=700) for k in ('train','calibration','test')}))
        def read(path):
            sample=copy.deepcopy(self.sample);reads[0]+=1
            if reads[0]>=1:
                sample['received_at']=1000.01;now[0]=1000.02
            return dict(observation=sample)
        def publish(path,value):
            published.append(value)
            if value.get('status') in ('RUNNING','WAITING_INPUT'):handlers[signal.SIGTERM]()
        native=SimpleNamespace(ready={},infer=lambda q:dict(output=bytes([128]*39),execute_ms=.4),close=lambda:True)
        original_read=Path.read_text
        def path_read(path,*args,**kwargs):
            return 'os-boot' if str(path)=='/proc/sys/kernel/random/boot_id' else original_read(path,*args,**kwargs)
        argv=['normal_npu.live','--bundle',str(self.root),'--manifest-sha256','a'*64,
              '--library',str(self.root/'fixture.so'),'--library-sha256','b'*64,'--output',str(self.root/'state.json')]
        with patch('sys.argv',argv),patch.object(live,'check_start_selection'),patch.object(live,'Bundle',return_value=bundle), \
                patch.object(live,'Supervisor',return_value=native),patch.object(live,'read_state',side_effect=read), \
                patch.object(live,'publish',side_effect=publish),patch.object(live.time,'monotonic',side_effect=lambda:now[0]), \
                patch.object(live.time,'sleep'),patch.object(live.signal,'signal',side_effect=lambda kind,fn:handlers.update({kind:fn})), \
                patch.object(Path,'read_text',path_read):live.main()
        running=[d for d in published if d.get('status')=='RUNNING']
        self.assertEqual(len(running),1)
        self.assertEqual(running[0]['received_at'],1000.01)
        self.assertFalse(any(d.get('status')=='WAITING_INPUT' for d in published))


if __name__=='__main__':unittest.main()
