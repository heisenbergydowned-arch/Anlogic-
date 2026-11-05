"""Temporary-file/lock/proc fixtures; no NPU, systemd, training or board I/O."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from normal_npu import boot_selection as selection
from normal_npu import boot_recovery
from test_baseline_store_p25 import bundle_fixture,admission_fixture,sha,write,BOOT

NEW_BOOT='22222222-2222-4222-8222-222222222222'
OLD_ID='a'*32
NEW_ID='b'*32


class BootSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.learning=self.root/'learning';(self.learning/'jobs').mkdir(parents=True)
        self.proc=self.root/'proc';(self.proc/'sys/kernel/random').mkdir(parents=True)
        self.boot_file=self.proc/'sys/kernel/random/boot_id';self.boot_file.write_text(NEW_BOOT)
        self.adapter=self.root/'adapter';self.adapter.write_bytes(b'OFFLINE_NOT_EXECUTABLE')
        self.old=self.make_model(OLD_ID,'accepted-old');self.new=self.make_model(NEW_ID,'pending-new')
        self.env=self.root/'etc/normal-npu.env';self.env.parent.mkdir();self.env.write_bytes(self.raw(self.new))
        self.old_folder=self.learning/'jobs'/OLD_ID;self.old_folder.mkdir()
        write(self.old_folder/'job.json',dict(id=OLD_ID,state='COMPLETED',context={'os_boot_id':BOOT}))
        write(self.old_folder/'switch.json',dict(state='COMPLETED',candidate_manifest_sha256=self.old['BUNDLE_SHA256'],
            current_env_sha256=hashlib.sha256(self.raw(self.old)).hexdigest()))
        self.folder=self.learning/'jobs'/NEW_ID;self.folder.mkdir()
        self.job=dict(id=NEW_ID,state='DEPLOYING',context={'os_boot_id':BOOT},worker_id='c'*32,cancel_requested=False)
        write(self.folder/'job.json',self.job);(self.folder/'previous.env').write_bytes(self.raw(self.old))
        self.transaction=dict(state='SWITCHED_AWAITING_LIVE',candidate_manifest_sha256=self.new['BUNDLE_SHA256'],
            current_env_sha256=sha(self.env),previous_env_sha256=sha(self.folder/'previous.env'))
        write(self.folder/'switch.json',self.transaction)
        self.lease=self.root/'lease.json';write(self.lease,dict(schema='cabinet-native-lease-v1',state='CLEAN',boot_id=BOOT))
        self.selftest=self.root/'selftest.json'

    def make_model(self,identity,name):
        folder=self.root/'learned'/identity;bundle=folder/'bundle';pin=bundle_fixture(bundle,name)
        admission=folder/'admission.json';admission_fixture(admission,pin,self.adapter)
        return dict(BUNDLE=str(bundle),BUNDLE_SHA256=pin,LIBRARY=str(self.adapter),LIBRARY_SHA256=sha(self.adapter),
                    ADMISSION=str(admission),ADMISSION_SHA256=sha(admission))

    @staticmethod
    def raw(env):return ''.join(k+'='+env[k]+'\n' for k in sorted(env)).encode()

    def args(self,env=None):return argparse.Namespace(**{name:(env or self.new)[key] for key,name in selection.ARGUMENTS.items()})

    def prepare(self,args=None):
        return selection.prepare_selftest_selection(args or self.args(),self.env,self.learning,self.proc,self.lease)

    def live(self,args=None):
        return selection.require_live_selection(args or self.args(),self.env,self.learning,self.proc,self.selftest)

    def selftest_receipt(self,env=None):
        env=env or self.new;report=self.root/'current-probe.json'
        body=admission_fixture(report,env['BUNDLE_SHA256'],self.adapter)
        body['boot_id']=self.boot_file.read_text();write(report,body)
        write(self.selftest,dict(status='PASS_CURRENT_BOOT_HARDWARE_SELFTEST',boot_id=self.boot_file.read_text(),
            model_sha256=env['BUNDLE_SHA256'],selection_env_sha256=sha(self.env),admission_sha256=env['ADMISSION_SHA256'],
            report=str(report),report_sha256=sha(report)))

    @contextlib.contextmanager
    def owner(self):
        self.boot_file.write_text(BOOT)
        path=self.learning/'model-switch.lock';fd=os.open(str(path),os.O_RDWR|os.O_CREAT,0o600)
        fcntl.flock(fd,fcntl.LOCK_EX)
        info=os.fstat(fd);pid=31337;ticks='1234567';folder=self.proc/str(pid);folder.mkdir()
        fields=['S']+['0']*18+[ticks]
        (folder/'stat').write_text(str(pid)+' (python) '+' '.join(fields))
        command=['python3','-B',str(Path(selection.__file__).resolve().parents[1]/'npu_learning_cli.py'),
                 '--request-file',str(self.folder/'deploy-request.json')]
        (folder/'cmdline').write_bytes(b'\0'.join(s.encode() for s in command)+b'\0')
        (self.proc/'locks').write_text('1: FLOCK ADVISORY WRITE %d %x:%x:%d 0 EOF\n'%
                                    (pid,os.major(info.st_dev),os.minor(info.st_dev),info.st_ino))
        write(self.folder/'deployment-process.json',dict(pid=pid,start_ticks=ticks,boot_id=BOOT))
        write(self.folder/'deploy-request.json',dict(operation='deploy',job_id=NEW_ID,worker_id=self.job['worker_id'],
            manifest_sha256=self.new['BUNDLE_SHA256']))
        try:yield
        finally:os.close(fd)

    def test_new_boot_without_worker_restores_accepted_previous_before_candidate_can_load(self):
        original_args=self.args()
        with patch.object(boot_recovery,'recover',return_value={'status':'UNIT_CLEAN'}) as recover:
            args,receipt=self.prepare(original_args)
        self.assertEqual(receipt['action'],'RESTORED_PREVIOUS_ACCEPTED_SELECTION')
        self.assertEqual(self.env.read_bytes(),self.raw(self.old))
        self.assertEqual(args.bundle,self.old['BUNDLE'])
        self.assertEqual(original_args.bundle,self.new['BUNDLE'])
        self.assertEqual(json.loads((self.folder/'job.json').read_text())['state'],'INTERRUPTED')
        self.assertEqual(json.loads((self.folder/'switch.json').read_text())['state'],'INTERRUPTED_PREVIOUS_MODEL_RESTORED')
        recover.assert_called_once_with(file=self.lease)

    def test_prepared_switch_power_cut_uses_same_recovery(self):
        self.transaction['state']='PREPARED_SWITCH';write(self.folder/'switch.json',self.transaction)
        with patch.object(boot_recovery,'recover'):
            args,receipt=self.prepare()
        self.assertEqual(args.bundle,self.old['BUNDLE']);self.assertEqual(self.env.read_bytes(),self.raw(self.old))

    def test_legacy_completed_baseline_boot_is_read_only(self):
        self.env.write_bytes(self.raw(self.old));before=self.env.read_bytes()
        with patch.object(boot_recovery,'recover',side_effect=AssertionError('No selection recovery needed')):
            args,receipt=self.prepare(self.args(self.old))
        self.assertEqual(receipt['action'],'UNCHANGED_ACCEPTED_SELECTION')
        self.assertEqual(self.env.read_bytes(),before)
        self.assertEqual(json.loads((self.old_folder/'job.json').read_text())['state'],'COMPLETED')

    def test_same_boot_online_owner_may_validate_pending_candidate(self):
        with self.owner(),patch.object(boot_recovery,'recover'):
            args,receipt=self.prepare();self.selftest_receipt();live=self.live()
        self.assertEqual(receipt['action'],'ONLINE_PENDING_VALIDATION')
        self.assertEqual(args.bundle,self.new['BUNDLE'])
        self.assertEqual(live['model_sha256'],self.new['BUNDLE_SHA256'])
        self.assertEqual(self.env.read_bytes(),self.raw(self.new))

    def test_same_boot_pending_without_lock_owner_is_rejected(self):
        self.boot_file.write_text(BOOT)
        with patch.object(boot_recovery,'recover',side_effect=AssertionError('No unowned recovery')):
            with self.assertRaisesRegex(ValueError,'WITHOUT_DEPLOYMENT_OWNER'):self.prepare()
        self.assertEqual(self.env.read_bytes(),self.raw(self.new))

    def test_reused_pid_wrong_request_and_wrong_lock_owner_are_rejected(self):
        for mode in ('ticks','request','lock','script'):
            with self.subTest(mode=mode):
                with self.owner():
                    if mode=='ticks':
                        record=json.loads((self.folder/'deployment-process.json').read_text());record['start_ticks']='0';write(self.folder/'deployment-process.json',record)
                    elif mode=='request':
                        record=json.loads((self.folder/'deploy-request.json').read_text());record['worker_id']='d'*32;write(self.folder/'deploy-request.json',record)
                    elif mode=='lock':(self.proc/'locks').write_text('')
                    else:(self.proc/'31337/cmdline').write_bytes(b'python3\0wrong.py\0--request-file\0'+str(self.folder/'deploy-request.json').encode()+b'\0')
                    with self.assertRaises(ValueError):self.prepare()
                import shutil;shutil.rmtree(self.proc/'31337')
        self.assertEqual(self.env.read_bytes(),self.raw(self.new))

    def test_changed_backup_or_unaccepted_previous_is_not_restored(self):
        before=self.env.read_bytes()
        for mode in ('backup','previous_pending','artifact'):
            with self.subTest(mode=mode):
                if mode=='backup':(self.folder/'previous.env').write_bytes(b'changed')
                elif mode=='previous_pending':
                    transaction=json.loads((self.old_folder/'switch.json').read_text());transaction['state']='SWITCHED_AWAITING_LIVE';write(self.old_folder/'switch.json',transaction)
                else:(Path(self.old['BUNDLE'])/'model_u8.onnx').write_bytes(b'changed')
                with self.assertRaises(ValueError):self.prepare()
                (self.folder/'previous.env').write_bytes(self.raw(self.old))
                transaction=json.loads((self.old_folder/'switch.json').read_text());transaction['state']='COMPLETED';write(self.old_folder/'switch.json',transaction)
        self.assertEqual(self.env.read_bytes(),before)

    def test_dirty_native_or_failed_native_recovery_cannot_change_selection(self):
        write(self.lease,dict(schema='cabinet-native-lease-v1',state='ACTIVE',boot_id=BOOT))
        with patch.object(boot_recovery,'recover'):
            with self.assertRaisesRegex(ValueError,'NATIVE_NOT_CLEAN'):self.prepare()
        with patch.object(boot_recovery,'recover',side_effect=ValueError('Native recovery refused')):
            with self.assertRaisesRegex(ValueError,'Native recovery refused'):self.prepare()
        self.assertEqual(self.env.read_bytes(),self.raw(self.new))

    def test_stale_argv_is_rejected_before_any_recovery(self):
        with patch.object(boot_recovery,'recover',side_effect=AssertionError('No mutation')):
            with self.assertRaisesRegex(ValueError,'ARGV_ENV_MISMATCH'):self.prepare(self.args(self.old))

    def test_live_rejects_pending_new_boot_without_mac(self):
        self.selftest_receipt()
        with self.assertRaisesRegex(ValueError,'WITHOUT_DEPLOYMENT_OWNER'):self.live()

    def test_env_changed_between_selftest_and_live_is_rejected(self):
        with patch.object(boot_recovery,'recover'):args,receipt=self.prepare()
        self.selftest_receipt(self.old)
        self.assertEqual(self.live(args)['model_sha256'],self.old['BUNDLE_SHA256'])
        self.env.write_bytes(self.raw(self.new))
        with self.assertRaisesRegex(ValueError,'ARGV_ENV_MISMATCH'):self.live(args)

    def test_selftest_report_or_env_pin_change_is_rejected(self):
        self.env.write_bytes(self.raw(self.old));args=self.args(self.old);self.selftest_receipt(self.old)
        report=json.loads(self.selftest.read_text());report['selection_env_sha256']='0'*64;write(self.selftest,report)
        with self.assertRaisesRegex(ValueError,'SELFTEST_BINDING_CHANGED'):self.live(args)
        self.selftest_receipt(self.old);(self.root/'current-probe.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'SELFTEST_REPORT_CHANGED'):self.live(args)

    def test_selection_change_during_probe_cannot_publish_success(self):
        pin=sha(self.env);args=self.args();self.env.write_bytes(self.raw(self.old))
        with self.assertRaisesRegex(ValueError,'ARGV_ENV_MISMATCH'):
            selection.require_selftest_selection_unchanged(args,pin,self.env)

    def test_completed_commit_with_missing_job_tail_reconciles_without_native_or_service(self):
        live=self.folder/'live-validation.json'
        write(live,dict(status='PASS',manifest_sha256=self.new['BUNDLE_SHA256'],npu_executed=True,
            required_samples=512,observed_samples=512,alarm_rate=0.,
            samples=[dict(inference_count=n,state='BASELINE_MATCH') for n in range(1,513)]))
        hardware=json.loads(Path(self.new['ADMISSION']).read_text())
        deployment=self.folder/'deployment.json'
        write(deployment,dict(status='DEPLOYED_REAL_NORMAL_NPU',manifest_sha256=self.new['BUNDLE_SHA256'],
            model_id='pending-new',controls_changed=False,qualified=False,fault_classes_trained=[],hardware=hardware,
            live=dict(status='PASS',report_path=str(live),report_sha256=sha(live))))
        self.transaction.update(state='COMPLETED',commit_protocol='durable-normal-model-v1',deployment_sha256=sha(deployment))
        write(self.folder/'switch.json',self.transaction)
        with patch.object(boot_recovery,'recover',side_effect=AssertionError('No native change')):
            args,result=self.prepare()
        self.assertEqual(result['action'],'COMMITTED_JOB_RECONCILED')
        self.assertEqual(json.loads((self.folder/'job.json').read_text())['state'],'COMPLETED')
        self.assertEqual(self.env.read_bytes(),self.raw(self.new))

if __name__=='__main__':unittest.main()
