"""Synthetic MMIO/file fixtures; no physical calibration or board actions."""
import ast,copy,os,subprocess,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
from cabinet.protocol import initial_configuration_flags
from commissioning import configuration_permission as permission,deploy
from hmi_daily.read_real import normalize_status
from tests import test_commissioning_deploy as deploy_fixture
from tests import test_control_completion as control_fixture
from tests.test_commissioning_ready import SOURCE


def initial_status():
 raw=[0]*32;raw[0]=(1<<19)|(1<<20)|(1<<18)|(1<<11)|(1<<12)|(1<<4)
 raw[1]=100;raw[3]=1<<16;raw[8]=1020;raw[22]=3000;raw[23]=400
 return dict(raw_words=raw,configured=False,configuration_id=0,hard_inhibit=True,test_mode=True,
  applied_pwm_counts=0,requested_rpm=0,ramped_rpm=0,latched=[],active=['CONFIG_UNQUALIFIED'],
  input_validity=dict(adc=True,temperature=True,rpm=True,pressure=True),uptime_ms=100,
  measured_rpm=1020,temp_raw_1_16_C=400,alarm_level=1,mode='STOPPING',fan_action='MANUAL')

class ProtocolTests(unittest.TestCase):
 def test_old_firmware_does_not_gain_remote_permission(self):
  raw=[0]*32;raw[0]=0x8000
  decoded=initial_configuration_flags(raw)
  self.assertTrue(decoded['local_permission']);self.assertFalse(decoded['remote_initial_config_supported'])
  self.assertFalse(normalize_status({'raw_words':raw})['initial_config_eligible'])
 def test_capability_and_eligibility_do_not_forge_key(self):
  status=initial_status();decoded=normalize_status(status,keep_raw=True)
  self.assertTrue(decoded['remote_initial_config_supported']);self.assertTrue(decoded['initial_config_eligible'])
  self.assertFalse(decoded['local_permission']);self.assertEqual(decoded['raw_words'],status['raw_words'])
 def test_invalid_combinations_rejected_even_if_physical_key_set(self):
  mutations=[lambda w:w.__setitem__(0,w[0]&~(1<<19)),lambda w:w.__setitem__(0,w[0]|(1<<14)),
   lambda w:w.__setitem__(0,w[0]|(1<<7)),lambda w:w.__setitem__(7,400),lambda w:w.__setitem__(7,400<<16),
   lambda w:w.__setitem__(8,1000<<16),lambda w:w.__setitem__(9,1000<<16),lambda w:w.__setitem__(4,1),lambda w:w.__setitem__(18,12)]
  for mutate in mutations:
   words=initial_status()['raw_words'];words[0]|=1<<15;mutate(words)
   with self.subTest(words=words),self.assertRaises(ValueError):initial_configuration_flags(words)
 def test_output_zero_confirmation_never_means_power_off_and_word26_is_not_relabelled(self):
  s=initial_status();s['raw_words'][0]|=1<<21;s['raw_words'][26]=3
  d=normalize_status(s,True);self.assertTrue(d['output_zero_confirmed']);self.assertFalse(d['output_zero_is_power_disconnected'])
  self.assertNotIn('output_zero_age_ms',d)
  s['raw_words'][0]&=~((1<<19)|(1<<20))
  with self.assertRaisesRegex(ValueError,'OUTPUT_ZERO'):normalize_status(s,True)

class LegacyHmiEntryTests(unittest.TestCase):
 def test_root_and_legacy_hmi_protocol_decoders_remain_exactly_identical(self):
  root=Path(__file__).resolve().parents[1]
  def decoder(path):
   return next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='initial_configuration_flags')
  self.assertEqual(ast.dump(decoder(root/'cabinet/protocol.py')),ast.dump(decoder(root/'hmi_daily/cabinet/protocol.py')))
 def test_actual_hmi_working_directory_import_and_reader_entrypoint(self):
  hmi=Path(__file__).resolve().parents[1]/'hmi_daily';env=os.environ.copy();env['PYTHONPATH']='';env.pop('PYTHONOPTIMIZE',None)
  code='import read_real; from cabinet.protocol import initial_configuration_flags; w=[0]*32; print(initial_configuration_flags(w)); w[0]=1<<20; read_real.normalize_status({"raw_words":w})'
  p=subprocess.run([sys.executable,'-B','-c',code],cwd=str(hmi),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=10)
  self.assertNotEqual(p.returncode,0);self.assertIn('ELIGIBLE_WITHOUT_CAPABILITY',p.stderr);self.assertNotIn('ImportError',p.stderr)
  for entry in ('read_real.py','run_live.py'):
   p=subprocess.run([sys.executable,'-B',str(hmi/entry),'--help'],cwd=str(hmi),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=10)
   with self.subTest(entry=entry):self.assertEqual(p.returncode,0,p.stderr)

class FirstApplyTransactions(unittest.TestCase):
 def setUp(self):
  self.fixture=deploy_fixture.Transactions();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
  f=self.fixture;f.status=initial_status();f.obs=dict(status=f.status,control={'control_words':f.cw},feature_words=f.fw,
   received_at=time.monotonic(),bench={'state':'IDLE','controls_enabled':False})
  self.patch=patch.object(permission,'SOURCE',SOURCE);self.patch.start();self.addCleanup(self.patch.stop)
 def apply(self):
  f=self.fixture;f.obs['received_at']=time.monotonic();return deploy.apply(f.out,f.pin)
 def test_first_apply_without_key_applies_both_bindings_and_stays_disarmed(self):
  f=self.fixture;r=self.apply()
  self.assertEqual(r['apply_permission']['authorization'],permission.REMOTE);self.assertFalse(r['apply_permission']['local_permission'])
  self.assertEqual(f.cw,f.binding['control_words']);self.assertEqual(f.fw,f.binding['feature_words'])
  self.assertFalse(f.edge()['control']['enabled']);self.assertFalse(r['arm_requested'])
  self.assertTrue(all(0x300<=a<0x360 or a==0x18 for a,v in f.writes))
 def test_readback_must_be_virgin_not_just_unconfigured(self):
  f=self.fixture
  for index in (0,1):
   f.cw[index]=1
   with self.subTest(index=index),self.assertRaisesRegex(ValueError,'VIRGIN'):self.apply()
   f.cw[index]=0
  self.assertEqual(f.calls,[]);self.assertEqual(f.writes,[])
 def test_stale_or_changed_idle_status_is_rejected_before_stopping_services(self):
  f=self.fixture;f.obs['received_at']=time.monotonic()-1
  with self.assertRaises(ValueError):deploy.apply(f.out,f.pin)
  self.assertEqual(f.calls,[])
  f.status['requested_rpm']=1000
  with self.assertRaisesRegex(ValueError,'IDLE'):self.apply()
  self.assertEqual(f.calls,[])
 def test_hardware_eligibility_rechecked_after_sole_owner_is_opened(self):
  f=self.fixture;changed=copy.deepcopy(f.status);changed['raw_words'][0]&=~(1<<20)
  with patch.object(f.ctrl,'status',return_value=changed):
   with self.assertRaisesRegex(ValueError,'NOT_ELIGIBLE'):self.apply()
  self.assertEqual(f.writes,[]);self.assertFalse(f.edge()['control']['enabled'])
 def test_remote_exception_requires_complete_measured_package(self):
  f=self.fixture;pkg=list(deploy.check(f.out,f.pin));pkg[2]=copy.deepcopy(pkg[2]);pkg[2]['qualifications']['pi']=False
  with self.assertRaisesRegex(ValueError,'COMPLETE_REAL'):permission.require_apply_permission(f.status,f.cw,1,pkg,f.fw)
  pkg=list(deploy.check(f.out,f.pin));pkg[1]=dict(pkg[1],source='SYNTHETIC')
  with self.assertRaisesRegex(ValueError,'COMPLETE_REAL'):permission.require_apply_permission(f.status,f.cw,1,pkg,f.fw)
 def test_running_bench_is_rejected_before_side_effects(self):
  f=self.fixture;f.obs['bench']={'state':'QUEUED_NOT_APPLIED','controls_enabled':False}
  with self.assertRaisesRegex(ValueError,'bench'):self.apply()
  self.assertEqual(f.calls,[]);self.assertEqual(f.writes,[])
 def test_partial_feature_success_control_failure_does_not_arm(self):
  f=self.fixture;f.fail_commit=True
  with self.assertRaises(IOError):self.apply()
  self.assertFalse(f.edge()['control']['enabled']);self.assertEqual(f.fw,f.binding['feature_words'])
 def test_same_already_qualified_feature_can_resume_control_commit_without_key(self):
  f=self.fixture;f.fw=list(f.binding['feature_words']);f.obs['feature_words']=f.fw
  with patch.object(deploy,'commit_feature') as feature_commit:r=self.apply()
  feature_commit.assert_not_called();self.assertEqual(r['apply_permission']['authorization'],permission.REMOTE)
  self.assertEqual(f.cw,f.binding['control_words'])
 def test_different_already_qualified_feature_cannot_use_first_control_permission(self):
  f=self.fixture;f.fw=list(f.binding['feature_words']);f.fw[3]^=1;f.obs['feature_words']=f.fw
  with self.assertRaisesRegex(ValueError,'FEATURE_CONFIGURATION_ALREADY_CALIBRATED'):self.apply()
  self.assertEqual(f.calls,[]);self.assertEqual(f.writes,[])
 def test_feature_becoming_qualified_after_preview_is_rechecked_before_register_write(self):
  f=self.fixture;changed=list(f.binding['feature_words']);changed[3]^=1
  with patch.object(deploy,'read_feature_configuration',return_value=changed):
   with self.assertRaisesRegex(ValueError,'FEATURE_CONFIGURATION_ALREADY_CALIBRATED'):self.apply()
  self.assertEqual(f.writes,[]);self.assertFalse(f.edge()['control']['enabled'])
 def test_queued_remote_authorization_cannot_expand_to_local_maintenance(self):
  f=self.fixture;f.fw=list(f.binding['feature_words']);f.fw[3]^=1;f.obs['feature_words']=f.fw
  f.status['raw_words'][0]|=1<<15;f.obs['received_at']=time.monotonic()
  with self.assertRaisesRegex(ValueError,'authorization changed'):
   deploy.apply(f.out,f.pin,expected_authorization=permission.REMOTE)
  self.assertEqual(f.calls,[]);self.assertEqual(f.writes,[])
 def test_existing_configuration_without_key_still_cannot_use_first_exception(self):
  f=self.fixture;f.status['raw_words'][0]&=~(1<<20);f.status['configured']=True;f.status['configuration_id']=77
  f.status['raw_words'][0]|=1<<14;f.status['raw_words'][18]=77
  with self.assertRaisesRegex(ValueError,'KEY2'):self.apply()
  self.assertEqual(f.writes,[])

class FirstApplyWebTransactions(unittest.TestCase):
 def setUp(self):
  self.fixture=control_fixture.ControlTransactions();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  f=self.fixture;f.state['status']=initial_status();f.state['control_words']=[0]*24;f.state['feature_words']=[1,0,0]+[0]*14
  self.patch=patch.object(permission,'SOURCE',SOURCE);self.patch.start();self.addCleanup(self.patch.stop)
 def test_preview_and_summary_have_same_dynamic_key_requirement_without_applying(self):
  f=self.fixture
  with patch.object(deploy,'apply') as apply:
   preview=f.work.action('control-preview',f.request());summary=f.work.control.summary()
  apply.assert_not_called();self.assertFalse(preview['local_key_required']);self.assertFalse(summary['local_key_required']['apply'])
  self.assertEqual(preview['apply_authorization'],permission.REMOTE);self.assertFalse(summary['local_permission'])
 def test_changed_eligibility_after_preview_refuses_confirmation(self):
  f=self.fixture;p=f.work.action('control-preview',f.request());f.state['status']['raw_words'][0]&=~(1<<20)
  with self.assertRaisesRegex(ValueError,'KEY2'):f.work.action('control-confirm',dict(nonce=p['nonce'],confirm=True))
  self.assertEqual(f.work.control.records(),[])
 def test_arm_still_requires_explicit_preview_confirmation_and_exact_package(self):
  f=self.fixture
  with self.assertRaisesRegex(ValueError,'standby'):f.work.action('control-preview',f.request('arm','speed',2000))
  self.assertEqual(f.work.control.records(),[])

if __name__=='__main__':unittest.main(verbosity=2)
