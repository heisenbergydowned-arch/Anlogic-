"""Isolated filesystem and CSR transaction tests. Never opens board hardware."""
import contextlib,copy,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_commissioning_ready import dataset,SOURCE
from commissioning.fit import build,sha,save
from commissioning import deploy

class Transactions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.fs=self.root/'fs';inp=self.root/'input'
        dataset(inp)
        for n in ('settings.json','base.json'):
            d=json.loads((inp/n).read_text());d['device_id']='machine:TEST-BOARD';save(inp/n,d)
        r=build(inp,inp/'base.json',self.root/'out',allow_fixture=True);self.out=Path(r['output']);self.pin=r['manifest_sha256']
        self.armed=json.loads((self.out/'edge.armed.json').read_text());self.binding=self.armed['commissioning']
        for d in ('etc/cabinet','var/lib/cabinet/npu-lease'): (self.fs/d).mkdir(parents=True)
        (self.fs/'etc/machine-id').write_text('TEST-BOARD')
        shutil.copy2(inp/'base.json',self.fs/'etc/cabinet/edge.json')
        for n in ('capture-contract.json','learning.json'):(self.fs/'etc/cabinet'/n).write_text('{}')
        (self.fs/'var/lib/cabinet/npu-lease/lease.json').write_text('{"state":"CLEAN"}')
        raw=[0]*32;raw[0]=0x8000;raw[22]=3000
        self.status=dict(raw_words=raw,applied_pwm_counts=0,temp_raw_1_16_C=400,input_validity=dict(adc=True,temperature=True),
            active=['CONFIG_UNQUALIFIED'],latched=[],configured=False,configuration_id=0)
        self.obs=dict(status=self.status,control={'control_words':self.binding['control_words']},feature_words=self.binding['feature_words'])
        self.calls=[];self.writes=[];self.cw=[0]*24;self.fw=[1,0,0]+[0]*14;self.fail_commit=False
        owner=self
        class IO:
            def read(self,a):
                if a==0x24:return owner.cw[1]
                if 0x500<=a<0x560:return owner.cw[(a-0x500)//4]
                raise AssertionError('Unexpected read '+hex(a))
            def write(self,a,v):
                owner.writes.append((a,v))
                if a==0x18:
                    if owner.fail_commit:raise IOError('Fixture commit failure')
                    owner.cw=[dict(owner.writes)[0x300+4*i] for i in range(24)]
                elif not 0x300<=a<0x360:raise AssertionError('An actuator command was attempted')
        class Controller:
            io=IO()
            def status(self):return owner.status
            def close(self):pass
        self.ctrl=Controller()
        self.stack=contextlib.ExitStack()
        original_copy2=shutil.copy2;original_tree=shutil.copytree
        def map_path(p):
            p=Path(p)
            return self.fs/str(p).lstrip('/') if str(p).startswith(('/etc/','/var/lib/cabinet/','/run/cabinet')) else p
        def run(args,check=True):
            self.calls.append(args)
            return type('Completed',(),dict(returncode=0,stdout=''))()
        for name,value in [
            ('commissioning.deploy.Path',map_path),('commissioning.deploy.sha',lambda p:sha(map_path(p))),
            ('commissioning.deploy.run',run),('commissioning.deploy.os.geteuid',lambda:0),
            ('commissioning.deploy.observation',lambda p:({'display':{}},self.obs,self.status)),
            ('commissioning.deploy.open_controller',lambda cfg:self.ctrl),
            ('commissioning.deploy.read_feature_configuration',lambda io:self.fw),
            ('commissioning.deploy.commit_feature',lambda ctrl,words:setattr(self,'fw',list(words))),
            ('hmi_daily.read_real.normalize_status',lambda status,keep_raw=False:copy.deepcopy(status)),
            ('commissioning.deploy.SOURCE',SOURCE),('commissioning.runtime.SOURCE',SOURCE),
            ('commissioning.deploy.shutil.copy2',lambda a,b:original_copy2(map_path(a),map_path(b))),
            ('commissioning.deploy.shutil.copytree',lambda a,b:original_tree(map_path(a),map_path(b)))]:
            self.stack.enter_context(patch(name,value))
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def edge(self):return json.loads((self.fs/'etc/cabinet/edge.json').read_text())
    def test_apply_reads_back_registers_keeps_control_disabled_and_never_sends_target(self):
        r=deploy.apply(self.out,self.pin)
        self.assertEqual(r['status'],'PARAMETERS_APPLIED_CONTROL_DISARMED');self.assertFalse(self.edge()['control']['enabled'])
        self.assertEqual(self.cw,self.binding['control_words']);self.assertEqual(self.fw,self.binding['feature_words'])
        self.assertTrue(all(0x300<=a<0x360 or a==0x18 for a,v in self.writes))
    def test_partial_hardware_failure_retains_disabled_owner_and_transaction(self):
        self.fail_commit=True
        with self.assertRaises(IOError):deploy.apply(self.out,self.pin)
        self.assertFalse(self.edge()['control']['enabled'])
        receipt=list((self.fs/'var/lib/cabinet/commissioning').glob('*/transaction.json'))[0]
        self.assertEqual(json.loads(receipt.read_text())['status'],'COMMISSIONING_INCOMPLETE_CONTROL_DISARMED')
        self.assertIn(['systemctl','start','cabinet-edge','cabinet-local-display'],self.calls)
    def test_no_local_key_no_writes(self):
        self.status['raw_words'][0]=0
        with self.assertRaisesRegex(ValueError,'KEY2'):deploy.apply(self.out,self.pin)
        self.assertEqual(self.writes,[]);self.assertEqual(self.calls,[])
    def test_no_arm_without_explicit_trial_or_matching_board(self):
        with self.assertRaises(ValueError):deploy.arm(self.out,self.pin)
        (self.fs/'etc/machine-id').write_text('OTHER')
        with self.assertRaisesRegex(ValueError,'Wrong physical board'):deploy.arm(self.out,self.pin,True)
    def test_arm_requires_fresh_exact_installed_registers(self):
        deploy.apply(self.out,self.pin);self.obs['control']['control_words']=[0]*24
        with self.assertRaisesRegex(ValueError,'MISMATCH'):deploy.arm(self.out,self.pin,True)
        self.assertFalse(self.edge()['control']['enabled'])
    def test_explicit_trial_arms_then_disarm_retains_hardware_protection(self):
        deploy.apply(self.out,self.pin);r=deploy.arm(self.out,self.pin,True)
        self.assertEqual(r['status'],'CONTROLLED_TRIAL_REQUESTED');self.assertFalse(r['physical_closed_loop_accepted'])
        self.assertTrue(self.edge()['control']['enabled'])
        r=deploy.disarm(self.out,self.pin);self.assertFalse(self.edge()['control']['enabled']);self.assertFalse(r['pwm_zero_guaranteed'])
    def test_reboot_requires_restore_into_standby_before_rearm(self):
        deploy.apply(self.out,self.pin);deploy.arm(self.out,self.pin,True)
        self.cw=[0]*24;self.fw=[1,0,0]+[0]*14
        with patch('commissioning.deploy.time.time',return_value=1):r=deploy.apply(self.out,self.pin)
        self.assertFalse(self.edge()['control']['enabled']);self.assertTrue(r['registers_verified'])
    def test_retained_native_lease_cannot_be_overridden(self):
        (self.fs/'var/lib/cabinet/npu-lease/lease.json').write_text('{"state":"DIRTY"}')
        with self.assertRaisesRegex(ValueError,'cleanup'):deploy.apply(self.out,self.pin)
        self.assertEqual(self.writes,[])

if __name__=='__main__':unittest.main()

class OwnerMismatch(unittest.TestCase):
    def test_collector_continues_while_register_mismatch_suppresses_all_control_commands(self):
        from cabinet.service import Service
        from tests.test_local_display import CONFIG,CountingController
        with tempfile.TemporaryDirectory() as tmp:
            cfg=copy.deepcopy(CONFIG);cfg['database']=str(Path(tmp)/'events.db')
            cfg['control'].update(enabled=True,qualified=True,evidence='TEST')
            cfg['commissioning']=dict(source='REAL_USER_MEASUREMENTS',evidence_sha256='a'*64,control_words=[15,55]+[0]*22,feature_words=[0]*17)
            c=CountingController();commands=[]
            c.command=lambda *args:commands.append(args)
            c.io=type('IO',(),dict(read=lambda self,address:123 if address==0x1050 else 0))()
            packets=[]
            class Observer:
                def submit(self,packet):packets.append(packet);svc.stop.set()
            svc=Service(cfg,controller=c,observer=Observer())
            try:
                with patch('cabinet.service.read_control_words',return_value=[15,1]+[0]*22),patch('cabinet.service.read_feature_configuration',return_value=[0]*17),patch('cabinet.service.read_mailbox',return_value={'queued_frames':0,'dropped_frames':0}):
                    svc.io_loop()
                self.assertEqual(commands,[])
                self.assertTrue(packets);self.assertEqual(packets[-1]['link'],'ONLINE')
                self.assertFalse(packets[-1]['control']['enabled'])
                self.assertIn('MISMATCH',packets[-1]['control']['binding_error'])
            finally:svc.store.close()
