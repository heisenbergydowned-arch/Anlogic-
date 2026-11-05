"""Synthetic model/storage fixtures: no training, device, service or board access."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from normal_npu import baseline_store as store
from normal_npu import learning_deploy as deploy
from normal_npu.bundle import Bundle
from normal_npu.core import FEATURES,GROUPS

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
write=lambda p,value:Path(p).write_text(json.dumps(value),encoding='utf-8')
BOOT='11111111-1111-4111-8111-111111111111'


def bundle_fixture(root,model_id='OFFLINE_TEST_MODEL'):
    root.mkdir(parents=True)
    data={'model_u8.onnx':b'SYNTHETIC_NOT_EXECUTABLE_ONNX','model_alnpu_u8.onnx':b'SYNTHETIC_NOT_EXECUTABLE_ALNPU',
          'normalization.json':dict(features=FEATURES,normalization_fitted_on='train',mean=[0.]*39,scale=[1.]*39,
              input_scale=.1,output_scale=.1,input_zero_point=128,output_zero_point=128),
          'thresholds.json':dict(group_rmse={g:1. for g in GROUPS},abs_z_limit=[3.]*39,threshold_fitted_on='calibration'),
          'provenance.json':dict(input_contract={'fixture':True},raw_capture_qualification_changed=False,
              sessions={n:dict(session_id='OFFLINE_'+n,rows=512) for n in ('train','calibration','test')}),
          'golden.json':{'fixture':True}}
    data['alnpu_conversion.json']=dict(schema='cabinet-alnpu-half-lsb-bias-v1',
        source_model_sha256=hashlib.sha256(data['model_u8.onnx']).hexdigest(),
        hardware_model_sha256=hashlib.sha256(data['model_alnpu_u8.onnx']).hexdigest(),reference_and_thresholds_unchanged=True)
    for name,value in data.items():
        if isinstance(value,bytes):(root/name).write_bytes(value)
        else:write(root/name,value)
    write(root/'manifest.json',dict(schema='cabinet-real-normal-npu-v2',source='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC',
        qualified=False,fault_classes_trained=[],control_authority='NONE',input_shape=[1,39],output_shape=[1,39],
        architecture=[39,32,16,39],model_id=model_id,artifacts_sha256={n:sha(root/n) for n in data}))
    return sha(root/'manifest.json')


def admission_fixture(path,pin,adapter):
    report=dict(status='PASS_REAL_NORMAL_CAPTURE_ALNPU_RECONSTRUCTION_ONLY',npu_executed=True,native_cleanup_verified=True,
        qualified=False,fault_classes_trained=[],source='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC',model_sha256=pin,
        adapter_sha256=sha(adapter),boot_id=BOOT,kernel_release=os.uname().release,
        backend_audit=dict(assigned_backends=['Alnpu'],backend_assignment_verified=True),vectors=128,
        irq_delta={'HARD_NPU_IRQ':384,'SOFT_NPU_IRQ':0},max_quantized_error=0,normal_holdout_alarm_rate=0.,execute_ms={'p99':1.})
    write(path,report);return report


class SavedSelection(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.bundle=self.root/'learned/job-fixture/bundle';self.pin=bundle_fixture(self.bundle)
        self.adapter=self.root/'adapter.so';self.adapter.write_bytes(b'OFFLINE_NOT_A_LIBRARY')
        self.admission=self.bundle.parent/'admission.json';admission_fixture(self.admission,self.pin,self.adapter)
        self.env=self.root/'etc/normal-npu.env';self.env.parent.mkdir()
        self.learning=self.root/'learning';(self.learning/'jobs').mkdir(parents=True)
        self.values=dict(BUNDLE=str(self.bundle),BUNDLE_SHA256=self.pin,LIBRARY=str(self.adapter),LIBRARY_SHA256=sha(self.adapter),
                         ADMISSION=str(self.admission),ADMISSION_SHA256=sha(self.admission))
        self.env.write_text(''.join(k+'='+v+'\n' for k,v in self.values.items()))
        store._CACHE.clear()
        self.disk=patch.object(store,'storage_status',side_effect=lambda p:dict(path=str(p),persistent=True,is_sd=True,
            filesystem='ext4',device='/dev/mmcblk0p2',card_type='SD',writable=True,mount_point='/'))
        self.disk.start();self.addCleanup(self.disk.stop)
    def status(self):return store.saved_baseline_status(self.env,self.learning)
    def test_valid_saved_selection_is_sd_bound_and_never_requires_host_or_learning(self):
        value=self.status()
        self.assertTrue(value['saved_on_sd']);self.assertTrue(value['saved']);self.assertTrue(value['valid'])
        self.assertEqual(value['manifest_sha256'],self.pin);self.assertEqual(value['startup_policy'],'LOAD_SAVED_NO_AUTOMATIC_LEARNING')
        self.assertFalse(value['automatic_learning']);self.assertFalse(value['host_required_for_saved_inference'])
        self.assertFalse(value['boot_creates_training_job']);self.assertFalse(value['boot_captures_training_data'])
        self.assertIn('+00:00',value['saved_at']);self.assertEqual(len(value['training_sessions']),3)
    def test_missing_selection_is_explicit_without_creating_files(self):
        self.env.unlink();before=set(self.root.rglob('*'));value=self.status()
        self.assertEqual(value['status'],'NO_SAVED_MODEL');self.assertFalse(value['saved']);self.assertEqual(before,set(self.root.rglob('*')))
    def test_corrupt_environment_is_structured_error(self):
        self.env.write_text('not an environment')
        self.assertEqual(self.status()['status'],'INVALID_SAVED_MODEL')
    def test_corrupt_bundle_is_not_saved_merely_because_env_exists(self):
        (self.bundle/'model_alnpu_u8.onnx').write_bytes(b'corrupt')
        value=self.status();self.assertEqual(value['status'],'INVALID_SAVED_MODEL');self.assertFalse(value['valid'])
    def test_corrupt_admission_is_invalid(self):
        self.admission.write_text('{}');self.assertFalse(self.status()['valid'])
    def test_valid_model_on_tmpfs_is_not_reported_saved(self):
        with patch.object(store,'storage_status',return_value=dict(persistent=False,is_sd=False,writable=True)):
            value=self.status()
        self.assertEqual(value['status'],'VALID_MODEL_NOT_PERSISTENT');self.assertTrue(value['valid']);self.assertFalse(value['saved'])
    def test_unknown_storage_is_not_assumed_sd(self):
        with patch.object(store,'storage_status',return_value=dict(persistent=None,is_sd=None,writable=None)):
            value=self.status()
        self.assertEqual(value['status'],'VALID_MODEL_STORAGE_UNKNOWN');self.assertFalse(value['saved_on_sd'])
    def test_non_sd_persistent_storage_is_distinct(self):
        with patch.object(store,'storage_status',return_value=dict(persistent=True,is_sd=False,writable=True)):
            value=self.status()
        self.assertTrue(value['saved']);self.assertFalse(value['saved_on_sd'])
    def test_hot_status_avoids_rehashing_models(self):
        with patch.object(store,'_validated',wraps=store._validated) as validation:
            self.status();value=self.status()
            self.assertEqual(validation.call_count,1);self.assertTrue(value['validation_cached'])
    def test_changed_artifact_immediately_invalidates_cache(self):
        self.status();(self.bundle/'model_u8.onnx').write_bytes(b'tampered')
        value=self.status();self.assertFalse(value['valid']);self.assertFalse(value['validation_cached'])
    def test_cache_expires_even_if_stat_fingerprint_is_unchanged(self):
        with patch.object(store,'time') as clock,patch.object(store,'_validated',wraps=store._validated) as validation:
            clock.monotonic.return_value=100.;self.status()
            clock.monotonic.return_value=131.;self.status()
            self.assertEqual(validation.call_count,2)
    def test_pending_live_validation_does_not_claim_completed_saved_baseline(self):
        job=self.learning/'jobs'/self.bundle.parent.name;job.mkdir()
        write(job/'switch.json',dict(state='SWITCHED_AWAITING_LIVE',candidate_manifest_sha256=self.pin,current_env_sha256=sha(self.env)))
        value=self.status();self.assertEqual(value['status'],'SAVED_SELECTION_PENDING_VALIDATION')
        self.assertFalse(value['saved']);self.assertTrue(value['selection_persisted'])
        write(job/'switch.json',dict(state='COMPLETED',candidate_manifest_sha256=self.pin,current_env_sha256=sha(self.env)))
        self.assertTrue(self.status()['saved'])
    def test_existing_empty_or_mismatched_switch_never_claims_saved(self):
        job=self.learning/'jobs'/self.bundle.parent.name;job.mkdir()
        for transaction in ({},{'state':'COMPLETED','candidate_manifest_sha256':'0'*64,'current_env_sha256':sha(self.env)},
                {'state':'COMPLETED','candidate_manifest_sha256':self.pin,'current_env_sha256':'0'*64}):
            write(job/'switch.json',transaction)
            value=self.status();self.assertEqual(value['status'],'INVALID_SAVED_MODEL');self.assertFalse(value['saved'])

    def test_new_process_reads_same_persisted_selection_without_capture_or_training(self):
        before={str(p):sha(p) for p in self.root.rglob('*') if p.is_file()}
        code='''import json,sys
from normal_npu.learning import Learning
from normal_npu import learning_deploy
from normal_npu.baseline_store import saved_baseline_status
def forbidden(*a,**k):raise AssertionError('No training/capture/service may run on saved status')
Learning.start=forbidden;Learning.claim=forbidden;learning_deploy.run=forbidden
r=saved_baseline_status(sys.argv[1],sys.argv[2]);print(json.dumps(r))
'''
        for unused in range(2):
            raw=subprocess.check_output([sys.executable,'-B','-c',code,str(self.env),str(self.learning)],text=True)
            value=json.loads(raw);self.assertTrue(value['valid']);self.assertEqual(value['manifest_sha256'],self.pin)
        self.assertEqual(before,{str(p):sha(p) for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(list((self.learning/'jobs').iterdir()),[])


class MountIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.device='%d:%d'%(os.major(self.root.stat().st_dev),os.minor(self.root.stat().st_dev))
        self.info=self.root/'mountinfo';self.sys=self.root/'sys';self.sys.mkdir()
        self.block=self.root/'block/mmcblk0';(self.block/'device').mkdir(parents=True);(self.block/'mmcblk0p2').mkdir()
        (self.block/'device/type').write_text('SD');(self.sys/self.device).symlink_to(self.block/'mmcblk0p2')
        self.info.write_text('1 0 '+self.device+' / '+str(self.root)+' rw - ext4 /dev/mmcblk0p2 rw\n')
        self.patches=[patch.object(store,'MOUNTINFO',self.info),patch.object(store,'SYS_DEV_BLOCK',self.sys)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def test_sd_requires_real_sysfs_type_not_device_name(self):
        value=store.storage_status(self.root);self.assertTrue(value['is_sd']);self.assertEqual(value['card_type'],'SD')
        (self.block/'device/type').write_text('MMC');self.assertFalse(store.storage_status(self.root)['is_sd'])
    def test_missing_sysfs_type_is_unknown_not_assumed_sd(self):
        (self.block/'device/type').unlink();self.assertIsNone(store.storage_status(self.root)['is_sd'])
    def test_tmpfs_mount_is_not_persistent(self):
        self.info.write_text(self.info.read_text().replace('ext4','tmpfs'))
        self.assertFalse(store.storage_status(self.root)['persistent'])
    def test_readonly_mount_is_reported(self):
        self.info.write_text(self.info.read_text().replace(' rw',' ro'))
        self.assertFalse(store.storage_status(self.root)['writable'])


class DurableWrites(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.env=self.root/'env';self.env.write_bytes(b'previous')
    def test_atomic_order_is_file_sync_then_replace_then_directory_sync(self):
        events=[];real_sync=store.os.fsync;real_replace=store.os.replace
        def sync(fd):events.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file');return real_sync(fd)
        def replace(a,b):events.append('replace');return real_replace(a,b)
        with patch.object(store.os,'fsync',side_effect=sync),patch.object(store.os,'replace',side_effect=replace):
            store.durable_atomic(self.env,b'new')
        self.assertEqual(events,['file','replace','directory']);self.assertEqual(self.env.read_bytes(),b'new')
    def test_file_sync_failure_preserves_original_selection(self):
        with patch.object(store.os,'fsync',side_effect=OSError('disk sync failure')):
            with self.assertRaises(OSError):store.durable_atomic(self.env,b'new')
        self.assertEqual(self.env.read_bytes(),b'previous')
    def test_directory_sync_failure_cannot_return_success(self):
        with patch.object(store,'fsync_directory',side_effect=OSError('directory sync failure')):
            with self.assertRaisesRegex(OSError,'directory'):store.durable_atomic(self.env,b'new')
    def test_bundle_and_admission_copied_synced_and_revalidated(self):
        source=self.root/'candidate';pin=bundle_fixture(source);admission=self.root/'admission';admission.write_bytes(b'probe')
        target=self.root/'learned/id'
        with patch.object(store,'fsync_directory',wraps=store.fsync_directory) as sync:
            result=store.persist_candidate(source,admission,target,pin)
        self.assertTrue(result['files_synced']);self.assertTrue(result['directories_synced'])
        self.assertEqual(sha(target/'admission.json'),sha(admission));self.assertEqual(Bundle(target/'bundle',pin).pin,pin)
        dirs={Path(c.args[0]) for c in sync.call_args_list};self.assertTrue({target,target/'bundle',target.parent}<=dirs)
    def test_candidate_sync_failure_leaves_env_unchanged(self):
        source=self.root/'candidate';pin=bundle_fixture(source);admission=self.root/'admission';admission.write_bytes(b'probe')
        with patch.object(store,'fsync_directory',side_effect=OSError('no space')):
            with self.assertRaises(OSError):store.persist_candidate(source,admission,self.root/'target',pin)
        self.assertEqual(self.env.read_bytes(),b'previous')


class DeployRollback(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.previous=self.root/'old/bundle';oldpin=bundle_fixture(self.previous,'old')
        self.candidate=self.root/'source/bundle';self.pin=bundle_fixture(self.candidate,'new')
        self.adapter=self.root/'adapter';self.adapter.write_bytes(b'NOT_A_LIBRARY')
        self.admission=self.root/'old/admission.json';admission_fixture(self.admission,oldpin,self.adapter)
        self.env=self.root/'etc/env';self.env.parent.mkdir();self.config=self.root/'edge';self.config.write_bytes(b'{}')
        values=dict(BUNDLE=str(self.previous),BUNDLE_SHA256=oldpin,LIBRARY=str(self.adapter),LIBRARY_SHA256=sha(self.adapter),
                    ADMISSION=str(self.admission),ADMISSION_SHA256=sha(self.admission))
        self.raw=''.join(k+'='+v+'\n' for k,v in values.items()).encode();self.env.write_bytes(self.raw)
        self.job={'id':'job','state':'HOST_VALIDATED'};self.jobs=self.root/'learning';self.folder=self.jobs/'jobs/job';self.folder.mkdir(parents=True)
        self.updates=[]
        def update(i,w,**values):self.updates.append(values);return dict(self.job,**values)
        self.owner=SimpleNamespace(root=self.jobs,env=self.env,config=self.config,folder=lambda i:self.folder,
            owned=lambda i,w:self.job,check=lambda *a,**k:None,update=update,boot=lambda:BOOT,clock=lambda:100.)
        def command(args,**kwargs):return SimpleNamespace(stdout='active' if args[:3]==['systemctl','is-active','cabinet-normal-npu'] else '',returncode=0)
        def probe(args,**kwargs):
            out=Path(args[args.index('--output')+1]);out.mkdir();admission_fixture(out/'validation.json',self.pin,self.adapter)
            return SimpleNamespace(returncode=0)
        def unpack(a,d,p):import shutil;shutil.copytree(self.candidate,d)
        def live(*a):
            report=dict(status='PASS',observed_samples=512,required_samples=512,alarm_rate=0.,manifest_sha256=self.pin,npu_executed=True,
                samples=[dict(inference_count=n,state='BASELINE_MATCH') for n in range(1,513)])
            write(self.folder/'live-validation.json',report);return report
        self.patches=[patch.object(deploy,'run',side_effect=command),patch.object(deploy,'clean'),
            patch.object(deploy,'unpack',side_effect=unpack),patch.object(deploy.subprocess,'run',side_effect=probe),
            patch.object(deploy,'validate_candidate',side_effect=lambda s,j,b,p:(Bundle(b,p),{})),
            patch.object(deploy,'wait_live',side_effect=live)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def deploy(self):return deploy.deploy(self.owner,'job','worker','a'*64,self.pin,self.root/'learned')
    def test_success_records_durable_selection_policy(self):
        result=self.deploy();self.assertEqual(result['state'],'COMPLETED')
        self.assertTrue(result['result']['persistence']['directories_synced'])
        self.assertEqual(result['result']['startup_policy'],'LOAD_SAVED_NO_AUTOMATIC_LEARNING')
        self.assertEqual(json.loads((self.folder/'switch.json').read_text())['state'],'COMPLETED')
    def test_post_rename_directory_sync_failure_rolls_back_without_success(self):
        real=store.fsync_directory;failed=[False]
        def sync(path):
            if Path(path)==self.env.parent and self.env.read_bytes()!=self.raw and not failed[0]:
                failed[0]=True;raise OSError('injected post-rename dir sync failure')
            return real(path)
        with patch.object(store,'fsync_directory',side_effect=sync):
            with self.assertRaisesRegex(RuntimeError,'PREVIOUS_MODEL_RESTORED'):self.deploy()
        self.assertTrue(failed[0]);self.assertEqual(self.env.read_bytes(),self.raw)
        self.assertFalse(any(u['state']=='COMPLETED' for u in self.updates))
    def test_durable_copy_failure_never_selects_candidate(self):
        with patch.object(deploy,'persist_candidate',side_effect=OSError('copy sync failure')):
            with self.assertRaisesRegex(RuntimeError,'PREVIOUS_MODEL_RESTORED'):self.deploy()
        self.assertEqual(self.env.read_bytes(),self.raw);self.assertFalse(any(u['state']=='COMPLETED' for u in self.updates))
    def test_commit_then_job_write_failure_keeps_model_and_reconciles_without_services(self):
        original_update=self.owner.update
        def update(i,w,**values):
            if values['state']=='COMPLETED':raise OSError('power cut after model commit before job completion')
            return original_update(i,w,**values)
        self.owner.update=update
        with self.assertRaisesRegex(RuntimeError,'MODEL_COMMITTED_JOB_FINALIZATION_PENDING'):self.deploy()
        selected=self.env.read_bytes();self.assertNotEqual(selected,self.raw)
        self.assertEqual(json.loads((self.folder/'switch.json').read_text())['state'],'COMPLETED')
        self.job['state']='DEPLOYING'
        with patch.object(deploy,'run',side_effect=AssertionError('No service change after committed model')):
            self.assertTrue(deploy.recover_interrupted(self.owner,self.job))
            self.assertTrue(deploy.recover_interrupted(self.owner,self.job))
        self.assertEqual(self.env.read_bytes(),selected);self.assertEqual(self.job['state'],'COMPLETED')
        self.assertEqual(json.loads((self.folder/'job.json').read_text())['state'],'COMPLETED')
    def test_corrupt_committed_evidence_refuses_without_silent_rollback(self):
        self.deploy();selected=self.env.read_bytes();(self.folder/'live-validation.json').write_text('{}')
        self.job['state']='DEPLOYING'
        with patch.object(deploy,'run',side_effect=AssertionError('No unverified service change')):
            with self.assertRaisesRegex(ValueError,'COMMITTED_LIVE_EVIDENCE'):deploy.recover_interrupted(self.owner,self.job)
        self.assertEqual(self.env.read_bytes(),selected);self.assertEqual(self.job['state'],'DEPLOYING')

    def test_power_cut_after_env_rename_before_switched_receipt_recovers_planned_hash(self):
        (self.folder/'previous.env').write_bytes(self.raw);write(self.folder/'previous-service.json',{'active':True})
        self.env.write_bytes(b'planned candidate env')
        write(self.folder/'switch.json',dict(state='PREPARED_SWITCH',current_env_sha256=sha(self.env)))
        with patch('normal_npu.boot_recovery.recover'):
            deploy.recover_interrupted(self.owner,self.job)
        self.assertEqual(self.env.read_bytes(),self.raw)
        self.assertEqual(json.loads((self.folder/'switch.json').read_text())['state'],'INTERRUPTED_PREVIOUS_MODEL_RESTORED')


if __name__=='__main__':unittest.main(verbosity=2)
