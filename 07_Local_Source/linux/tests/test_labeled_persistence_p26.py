"""Synthetic fault-injection fixtures; no model training, board or NPU access."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid
from normal_npu.baseline_store import durable_save as save, file_sha as sha
from labeled_npu import persistence as p, boot_selection as b, deploy as d

LABELS=['normal','imbalance','stall','clog','overheat']

class DurableLabeledTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);p._CACHE.clear()
    def test_tree_copy_syncs_files_directories_and_readback(self):
        source=self.base/'source';source.mkdir();(source/'x').write_bytes(b'raw');(source/'nested').mkdir();(source/'nested/y').write_bytes(b'labels')
        with patch.object(p,'fsync_directory',wraps=p.fsync_directory) as sync:hashes=p.durable_copy_tree(source,self.base/'target')
        self.assertEqual(hashes,{'x':sha(source/'x'),'nested/y':sha(source/'nested/y')});self.assertEqual(sync.call_count,3)
    def test_symlink_and_existing_target_refused(self):
        source=self.base/'source';source.mkdir();(source/'bad').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):p.durable_copy_tree(source,self.base/'target')
        (source/'bad').unlink();(self.base/'target').mkdir()
        with self.assertRaises(ValueError):p.durable_copy_tree(source,self.base/'target')
    def test_sync_failure_never_reports_persistence_success(self):
        source=self.base/'source';source.mkdir();(source/'manifest.json').write_text('{}');admission=self.base/'admission';admission.write_text('{}')
        with patch.object(p,'fsync_directory',side_effect=OSError('disk flush failed')):
            with self.assertRaises(OSError):p.persist_candidate(source,admission,self.base/'candidate','a'*64)
        self.assertFalse((self.base/'labeled-npu.env').exists())
    def archive(self,name='job'):
        folder=self.base/name;episode=folder/'captures/episode';episode.mkdir(parents=True)
        job=dict(id='1'*32,label='normal',episode_id='physical-1',episode_split='train',corpus_key='b'*64,context={'fixture':True},sessions={'episode':{'status':{'session_id':'session-1'}}})
        save(episode/'session.json',dict(session_id='session-1'));save(episode/'feature_contract.json',dict(qualified=False));(episode/'frames.jsonl').write_text('fixture\n')
        save(episode/'summary.json',dict(session_id='session-1',frames=600,durable_frames=600,files_sha256={n:sha(episode/n) for n in ['session.json','feature_contract.json','frames.jsonl']}))
        save(folder/'sessions.json',job['sessions']);save(folder/'learning.json',dict(job,job_id=job['id']));(folder/'captures.tar.gz').write_bytes(b'fixture archive');job['export_sha256']=sha(folder/'captures.tar.gz');return folder,job
    def test_archive_reconstruction_loads_same_saved_data(self):
        folder,job=self.archive()
        with patch.object(p,'storage_status',return_value={'persistent':True,'is_sd':True}):
            one=p.archive_status(folder,job);p._CACHE.clear();two=p.archive_status(folder,job)
        self.assertTrue(one['saved_on_sd']);self.assertTrue(two['saved_on_sd']);self.assertEqual(two['session_id'],'session-1')
    def test_archive_tamper_or_missing_file_cannot_report_saved(self):
        for variant in ('tar','row','missing','malformed','sessions'):
            folder,job=self.archive(variant)
            if variant=='tar':(folder/'captures.tar.gz').write_bytes(b'changed')
            if variant=='row':(folder/'captures/episode/frames.jsonl').write_text('changed')
            if variant=='missing':(folder/'learning.json').unlink()
            if variant=='malformed':(folder/'captures/episode/summary.json').write_text('[]')
            if variant=='sessions':(folder/'sessions.json').write_text('{}')
            result=p.archive_status(folder,job);self.assertFalse(result['saved']);self.assertFalse(result['valid'])
    def test_cache_expires_despite_unchanged_stat(self):
        check=Mock(return_value={'ok':True})
        with patch.object(p.time,'monotonic',return_value=1):p.cached_validation('x',('same',),check)
        with patch.object(p.time,'monotonic',return_value=2):self.assertTrue(p.cached_validation('x',('same',),check)[1])
        with patch.object(p.time,'monotonic',return_value=32):self.assertFalse(p.cached_validation('x',('same',),check)[1])
        self.assertEqual(check.call_count,2)
    def test_invalid_env_is_contained(self):
        env=self.base/'labeled-npu.env';env.write_text('BUNDLE=/tmp/no\n')
        with patch.object(p,'validate_saved') as verify:result=p.saved_classifier_status(env,self.base)
        self.assertEqual(result['status'],'INVALID_SAVED_CLASSIFIER');self.assertFalse(result['saved']);verify.assert_not_called()
    def test_absent_selection_has_no_mac_or_learning_dependency(self):
        result=p.saved_classifier_status(self.base/'absent',self.base)
        self.assertEqual(result['status'],'NO_SAVED_CLASSIFIER');self.assertFalse(result['host_required_for_saved_inference']);self.assertFalse(result['automatic_learning'])

class ClassifierBootTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.root=self.base/'learning';self.folder=self.root/'jobs'/('1'*32);self.folder.mkdir(parents=True)
        self.env=self.base/'labeled-npu.env';self.unit=self.base/'classifier.service';self.normal=self.base/'normal-npu.env'
        self.proc=self.base/'proc';(self.proc/'sys/kernel/random').mkdir(parents=True);self.boot=str(uuid.uuid4());self.oldboot=str(uuid.uuid4());(self.proc/'sys/kernel/random/boot_id').write_text(self.boot)
        self.lease=self.base/'lease.json';save(self.lease,dict(schema='cabinet-native-lease-v1',state='CLEAN'))
        self.bundle=self.base/'models'/('1'*32)/'bundle';self.bundle.mkdir(parents=True);(self.bundle/'manifest.json').write_text('fixture')
        self.library=self.base/'lib.so';self.library.write_bytes(b'fixture');self.admission=self.base/'admission.json';save(self.admission,dict(fixture=True))
        self.values=dict(BUNDLE=str(self.bundle),BUNDLE_SHA256='a'*64,LIBRARY=str(self.library),LIBRARY_SHA256=sha(self.library),ADMISSION=str(self.admission),ADMISSION_SHA256=sha(self.admission))
        self.env.write_text(''.join(k+'='+v+'\n' for k,v in self.values.items()));self.unit.write_text('candidate unit');self.normal.write_text(''.join(k+'='+v+'\n' for k,v in dict(self.values,BUNDLE=str(self.base/'normalbundle')).items()))
        self.job=dict(id='1'*32,kind='labeled_classifier',state='DEPLOYING',worker_id='2'*32,cancel_requested=False,label='normal',context={'os_boot_id':self.oldboot})
        self.previous=dict(normal={'active':True,'enabled':True},labeled={'active':False,'enabled':False},env_exists=False,unit_exists=False,env_sha256=None,unit_sha256=None,normal_env_path=str(self.normal),normal_env_sha256=sha(self.normal),normal_model_pin='a'*64)
        save(self.folder/'previous-services.json',self.previous)
        self.t=dict(state='SWITCHED_AWAITING_LIVE',commit_protocol=p.PROTOCOL,manifest_sha256='a'*64,env_path=str(self.env),unit_path=str(self.unit),current_env_sha256=sha(self.env),current_unit_sha256=sha(self.unit),previous=self.previous,previous_services_sha256=sha(self.folder/'previous-services.json'));self.write()
    def write(self):save(self.folder/'job.json',self.job);save(self.folder/'switch.json',self.t)
    def reconcile(self):return b.reconcile_boot(self.root,self.env,self.unit,self.normal,self.proc,self.lease)
    def args(self):
        names={'BUNDLE':'bundle','BUNDLE_SHA256':'manifest_sha256','LIBRARY':'library','LIBRARY_SHA256':'library_sha256','ADMISSION':'admission','ADMISSION_SHA256':'admission_sha256'}
        return SimpleNamespace(**{names[k]:v for k,v in self.values.items()})
    def patches(self):
        import contextlib
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        native=stack.enter_context(patch.object(b,'_clean_native',return_value={'status':'CLEAN'}))
        enabled={'cabinet-normal-npu':'disabled','cabinet-labeled-npu':'enabled'}
        def command(argv,**kwargs):
            name=argv[-1]
            if argv[:2]==['systemctl','is-enabled']:
                state='not-found' if name=='cabinet-labeled-npu' and not self.unit.exists() else enabled[name]
                return SimpleNamespace(stdout=state,returncode=0 if state=='enabled' else 1)
            if argv[:2]==['systemctl','is-active']:
                return SimpleNamespace(stdout='unknown' if name=='cabinet-labeled-npu' and not self.unit.exists() else 'inactive',
                    returncode=4 if name=='cabinet-labeled-npu' and not self.unit.exists() else 3)
            if argv[:2]==['systemctl','enable']:enabled[name]='enabled'
            if argv[:2]==['systemctl','disable']:enabled[name]='disabled'
            return SimpleNamespace(stdout='',returncode=0)
        run=stack.enter_context(patch.object(d,'run',side_effect=command))
        stack.enter_context(patch('normal_npu.baseline_store._validated',return_value={'fixture':True}));stack.enter_context(patch('normal_npu.boot_selection._selected_job',return_value=None));return native,run
    def test_no_transaction_readonly_no_lock_or_native(self):
        (self.folder/'switch.json').unlink();before=set(self.base.rglob('*'));native,run=self.patches();result=self.reconcile()
        self.assertEqual(result['status'],'PASS_NO_RECOVERY');self.assertEqual(before,set(self.base.rglob('*')));native.assert_not_called();run.assert_not_called()
    def test_new_boot_first_classifier_restores_normal_nonblocking(self):
        old=self.normal.read_bytes();native,run=self.patches();result=self.reconcile()
        self.assertEqual(result['status'],'PASS_PREVIOUS_NPU_SELECTION_RESTORED');self.assertEqual(result['queued_start'],['cabinet-normal-npu']);self.assertFalse(self.env.exists());self.assertFalse(self.unit.exists());self.assertEqual(self.normal.read_bytes(),old)
        self.assertIn(['systemctl','--no-block','start','cabinet-normal-npu'],[c.args[0] for c in run.call_args_list]);self.assertNotIn(['systemctl','start','cabinet-normal-npu'],[c.args[0] for c in run.call_args_list]);native.assert_called_once()
        self.assertEqual(json.loads((self.folder/'job.json').read_text())['state'],'INTERRUPTED');self.assertFalse(result['npu_inference_verified'])
    def test_changed_candidate_env_refuses_restore(self):
        self.env.write_bytes(b'tampered');native,run=self.patches()
        with self.assertRaises(ValueError):self.reconcile()
        self.assertEqual(self.env.read_bytes(),b'tampered');native.assert_not_called();run.assert_not_called()
    def test_changed_normal_pointer_refuses_restore(self):
        self.normal.write_bytes(b'tampered');native,run=self.patches()
        with self.assertRaises(ValueError):self.reconcile()
        native.assert_not_called();run.assert_not_called()
    def test_dirty_lease_never_restores_or_starts(self):
        native,run=self.patches();native.side_effect=ValueError('DIRTY_SAME_BOOT');old=self.env.read_bytes()
        with self.assertRaisesRegex(ValueError,'DIRTY_SAME_BOOT'):self.reconcile()
        self.assertEqual(self.env.read_bytes(),old);run.assert_not_called()
    def test_same_boot_unowned_candidate_fails_closed(self):
        self.job['context']['os_boot_id']=self.boot;self.write();native,run=self.patches()
        with self.assertRaisesRegex(ValueError,'WITHOUT_DEPLOYMENT_OWNER'):self.reconcile()
        native.assert_not_called();run.assert_not_called();self.assertTrue(self.env.exists())
    def test_selftest_refuses_new_boot_pending_without_native(self):
        native,run=self.patches()
        with self.assertRaisesRegex(ValueError,'REQUIRES_BOOT_RECONCILIATION'):b.prepare_selftest_selection(self.args(),self.env,self.root,self.proc)
        native.assert_not_called();run.assert_not_called()
    def test_selftest_argv_env_binding(self):
        args=self.args();args.bundle='/incorrect'
        with self.assertRaisesRegex(ValueError,'ARGV_ENV_MISMATCH'):b.prepare_selftest_selection(args,self.env,self.root,self.proc)
    def owner(self):
        self.job['context']['os_boot_id']=self.boot;self.write();pid=321;(self.proc/str(pid)).mkdir();fields=['S']+['0']*18+['12345'];(self.proc/str(pid)/'stat').write_text('321 (fixture) '+' '.join(fields))
        (self.proc/str(pid)/'cmdline').write_bytes(b'python3\0-B\0-m\0labeled_npu.deploy\0--request-file\0'+str(self.folder/'deploy-request.json').encode()+b'\0')
        save(self.folder/'deployment-process.json',dict(pid=pid,boot_id=self.boot,start_ticks='12345'));save(self.folder/'deploy-request.json',dict(job_id=self.job['id'],worker_id=self.job['worker_id'],manifest_sha256='a'*64,archive_sha256='b'*64))
        lock=self.root/'model-switch.lock';lock.touch();info=lock.stat();(self.proc/'locks').write_text('1: FLOCK ADVISORY WRITE %d %x:%x:%d 0 EOF\n'%(pid,os.major(info.st_dev),os.minor(info.st_dev),info.st_ino));return info
    def test_online_owner_requires_process_and_actual_lock(self):
        info=self.owner();b.online_owner(self.folder,self.job,self.t,self.boot,self.proc,info)
        for name in ('locks','321/cmdline','321/stat'):
            old=(self.proc/name).read_bytes();(self.proc/name).write_bytes(b'changed')
            with self.subTest(name=name),self.assertRaises((ValueError,IndexError)):b.online_owner(self.folder,self.job,self.t,self.boot,self.proc,info)
            (self.proc/name).write_bytes(old)
    def committed(self):
        live=dict(status='PASS_CURRENT_USER_DECLARED_CONDITION',manifest_sha256='a'*64,user_declared_label='normal',samples=[dict(inference_count=i,fault_class='normal') for i in range(128)],required_samples=128,observed_samples=128,boot_id=self.oldboot,npu_executed=True,agreement=1.)
        save(self.folder/'live-validation.json',live);result=dict(status='DEPLOYED_REAL_LABELED_NPU_ADVISORY',manifest_sha256='a'*64,model_id='fixture',controls_changed=False,qualified=False,control_authority='NONE',fault_classes_trained=LABELS[1:],hardware=dict(boot_id=self.oldboot,kernel_release='fixture'),live={k:v for k,v in live.items() if k!='samples'},live_report_sha256=sha(self.folder/'live-validation.json'))
        save(self.folder/'deployment.json',result);self.t.update(state='COMPLETED',deployment_sha256=sha(self.folder/'deployment.json'));self.write()
        self.addCleanup(patch.stopall);patch.object(d,'validate_saved',return_value=dict(model_id='fixture',labels=LABELS)).start();patch.object(d,'validate_report').start();return live,result
    def test_power_loss_after_commit_reconciles_job_only(self):
        self.committed();native,run=self.patches();old=self.env.read_bytes();result=self.reconcile()
        self.assertEqual(result['status'],'PASS_COMMITTED_CLASSIFIER_RECONCILED');native.assert_not_called();run.assert_not_called();self.assertEqual(self.env.read_bytes(),old)
        job=json.loads((self.folder/'job.json').read_text());self.assertEqual(job['state'],'COMPLETED');self.assertEqual(job['completion_reconciled_from'],'DURABLE_CLASSIFIER_COMMIT');self.assertEqual(self.reconcile()['status'],'PASS_NO_RECOVERY')
    def test_commit_rejects_short_duplicate_wrong_label_env_and_result(self):
        live,result=self.committed()
        for variant in ('short','duplicate','wrong_label','env','result'):
            with self.subTest(variant=variant):
                lv=copy.deepcopy(live);res=copy.deepcopy(result);tx=copy.deepcopy(self.t)
                if variant=='short':lv['samples']=lv['samples'][:127];lv['observed_samples']=127
                if variant=='duplicate':lv['samples'][1]['inference_count']=0
                if variant=='wrong_label':lv['samples'][0]['fault_class']='clog';lv['agreement']=1.
                if variant=='env':tx['current_env_sha256']='c'*64
                if variant=='result':res['qualified']=True
                save(self.folder/'live-validation.json',lv);res['live']={k:v for k,v in lv.items() if k!='samples'};res['live_report_sha256']=sha(self.folder/'live-validation.json');save(self.folder/'deployment.json',res);tx['deployment_sha256']=sha(self.folder/'deployment.json')
                with self.assertRaises(ValueError):d.validate_commit(self.folder,self.job,tx,self.env,self.unit)
    def test_job_write_failure_keeps_durable_commit_selected(self):
        self.committed();native,run=self.patches();old=self.env.read_bytes()
        with patch.object(d,'save',side_effect=OSError('job fsync failure')):
            with self.assertRaises(OSError):self.reconcile()
        self.assertEqual(self.env.read_bytes(),old);self.assertEqual(json.loads((self.folder/'switch.json').read_text())['state'],'COMPLETED');native.assert_not_called();run.assert_not_called()
    def test_live_refuses_old_boot_selftest(self):
        self.committed();record=self.base/'selftest.json';save(record,dict(status='PASS_CURRENT_BOOT_HARDWARE_SELFTEST',boot_id=self.oldboot,model_sha256='a'*64,selection_env_sha256=sha(self.env),admission_sha256=sha(self.admission)))
        with patch.object(b,'require_selection',return_value=({'boot_id':self.boot,'env_sha256':sha(self.env)},self.values)):
            with self.assertRaisesRegex(ValueError,'SELFTEST_BINDING_CHANGED'):b.require_live_selection(self.args(),self.env,self.root,self.proc,record)

    def test_saved_pending_selection_is_not_accepted_on_sd(self):
        with patch.object(p,'validate_saved',return_value={'model_id':'fixture'}),patch.object(p,'storage_status',return_value={'persistent':True,'is_sd':True}):
            result=p.saved_classifier_status(self.env,self.root)
        self.assertTrue(result['valid']);self.assertTrue(result['selection_persisted']);self.assertFalse(result['saved']);self.assertFalse(result['saved_on_sd']);self.assertEqual(result['status'],'SAVED_SELECTION_PENDING_VALIDATION')
    def test_saved_committed_selection_reconstructed_without_host(self):
        self.committed()
        with patch.object(p,'validate_saved',return_value={'model_id':'fixture'}),patch.object(p,'storage_status',return_value={'persistent':True,'is_sd':True}):
            one=p.saved_classifier_status(self.env,self.root);p._CACHE.clear();two=p.saved_classifier_status(self.env,self.root)
        self.assertTrue(one['saved_on_sd']);self.assertTrue(two['saved_on_sd']);self.assertFalse(two['host_required_for_saved_inference']);self.assertEqual(two['manifest_sha256'],'a'*64)
    def test_saved_model_on_tmpfs_is_not_persistent(self):
        self.committed()
        with patch.object(p,'validate_saved',return_value={'model_id':'fixture'}),patch.object(p,'storage_status',return_value={'persistent':False,'is_sd':False}):result=p.saved_classifier_status(self.env,self.root)
        self.assertTrue(result['valid']);self.assertFalse(result['saved']);self.assertFalse(result['saved_on_sd'])
    def test_missing_managed_switch_not_accepted(self):
        (self.folder/'switch.json').unlink()
        with patch.object(p,'validate_saved',return_value={'model_id':'fixture'}),patch.object(p,'storage_status',return_value={'persistent':True,'is_sd':True}):result=p.saved_classifier_status(self.env,self.root)
        self.assertEqual(result['status'],'INVALID_SAVED_CLASSIFIER');self.assertFalse(result['saved'])
    def test_restore_job_tail_power_loss_needs_no_native(self):
        self.t.update(state='PREVIOUS_MODEL_RESTORED',recovered_on_boot=self.boot);self.env.unlink();self.unit.unlink();self.write();native,run=self.patches();result=self.reconcile()
        self.assertEqual(result['status'],'PASS_PREVIOUS_NPU_SELECTION_RESTORED');self.assertEqual(result['queued_start'],[]);native.assert_not_called();run.assert_not_called();self.assertEqual(json.loads((self.folder/'job.json').read_text())['state'],'INTERRUPTED')
    def test_same_boot_owned_selftest_requires_no_service_actions(self):
        import contextlib
        info=self.owner()
        @contextlib.contextmanager
        def held_elsewhere(*args,**kwargs):yield False,info
        native,run=self.patches()
        with patch.object(b,'_lock',held_elsewhere):args,result=b.prepare_selftest_selection(self.args(),self.env,self.root,self.proc)
        self.assertEqual(result['action'],'ONLINE_PENDING_VALIDATION');native.assert_not_called();run.assert_not_called()
    def test_previous_classifier_restores_exact_env_and_unit(self):
        old=''.join(k+'='+v+'\n' for k,v in dict(self.values,BUNDLE=str(self.base/'oldmanual/bundle')).items()).encode()
        (self.folder/'previous-labeled.env').write_bytes(old);(self.folder/'previous-labeled.unit').write_bytes(b'old unit')
        self.previous.update(normal={'active':False,'enabled':False},labeled={'active':True,'enabled':True},env_exists=True,unit_exists=True,env_sha256=sha(self.folder/'previous-labeled.env'),unit_sha256=sha(self.folder/'previous-labeled.unit'))
        save(self.folder/'previous-services.json',self.previous);self.t.update(previous=self.previous,previous_services_sha256=sha(self.folder/'previous-services.json'));self.write();native,run=self.patches()
        with patch.object(b,'validate_saved',return_value={}):result=self.reconcile()
        self.assertEqual(result['previous_backend'],'LABELED');self.assertEqual(self.env.read_bytes(),old);self.assertEqual(self.unit.read_bytes(),b'old unit');self.assertEqual(result['queued_start'],['cabinet-labeled-npu'])
    def test_historical_contract_samples_are_visible_but_not_merged(self):
        from labeled_npu.learning import Learning,corpus_key
        context=dict(input_contract=dict(device_id='fixture',configuration_words=[1],controller_mode='STOPPING'),bitstream_sha256='a'*64,config_sha256='c'*64);changed=dict(context,bitstream_sha256='b'*64)
        job=dict(id='1'*32,corpus_key=corpus_key(context),context=context,collection_finalized=True,label='normal',episode_id='physical-1',episode_split='train')
        store=object.__new__(Learning);store.root=self.root;store.captures=self.base/'captures';result=store.storage_diagnostics([job],changed,corpus_key(changed),None)
        self.assertEqual(result['current_coverage_state']['status'],'NO_CURRENT_SAMPLES_HISTORICAL_AVAILABLE');self.assertFalse(result['current_coverage_state']['historical_samples_merged'])
        history=result['historical_corpora'][0];self.assertEqual(history['coverage']['normal']['train'],1);self.assertEqual([x['field'] for x in history['contract_differences']],['bitstream_sha256']);self.assertEqual(history['verified_archives'],0)
        offline=store.storage_diagnostics([job],None,None,'COLLECTOR_STALE');self.assertEqual(offline['current_coverage_state']['status'],'CONTEXT_UNAVAILABLE');self.assertEqual(offline['historical_corpora'][0]['episodes'],1)
    def test_actual_deploy_job_tail_failure_keeps_committed_candidate(self):
        import contextlib
        self.env.unlink();self.unit.unlink();self.job['state']='HOST_VALIDATED';self.job['context']['os_boot_id']=self.boot
        bundle=SimpleNamespace(manifest={'model_id':'fixture','labels':LABELS},validation={'fixture':True},policy={'confidence_min':.6,'margin_min':.1})
        def update(identity,worker,**values):
            if values.get('state')=='COMPLETED':raise OSError('job durable write interrupted')
            self.job.update(values);return self.job
        store=SimpleNamespace(root=self.root,env=self.normal,folder=lambda unused:self.folder,owned=lambda *args:self.job,check=lambda *a,**k:None,update=update,boot=lambda:self.boot)
        enabled={d.NORMAL:'enabled',d.SERVICE:'disabled'};active={d.NORMAL:True,d.SERVICE:False};calls=[]
        def run(argv,**kwargs):
            calls.append(argv);name=argv[-1];absent=name==d.SERVICE and not self.unit.exists()
            if argv[:2]==['systemctl','is-active']:
                state='active' if active.get(name,False) else 'unknown' if absent else 'inactive'
                return SimpleNamespace(stdout=state,returncode={'active':0,'inactive':3,'unknown':4}[state])
            if argv[:2]==['systemctl','is-enabled']:
                state='not-found' if absent else enabled[name]
                return SimpleNamespace(stdout=state,returncode=0 if state=='enabled' else 1)
            if argv[:2]==['systemctl','enable']:enabled[name]='enabled'
            if argv[:2]==['systemctl','disable']:enabled[name]='disabled'
            if argv[:2]==['systemctl','start']:active[name]=True
            if argv[:2]==['systemctl','stop']:active[name]=False
            return SimpleNamespace(stdout='',returncode=0)
        def probe(*args,**kwargs):
            folder=self.folder/'hardware-probe';folder.mkdir();save(folder/'validation.json',dict(boot_id=self.boot,kernel_release='fixture'));return SimpleNamespace(returncode=0)
        def persist(candidate,admission,target,pin):
            (target/'bundle').mkdir(parents=True);(target/'bundle/manifest.json').write_text('fixture');(target/'admission.json').write_bytes(admission.read_bytes())
        def wait(pin,store,job,output,policy=None):
            report=dict(status='PASS_CURRENT_USER_DECLARED_CONDITION',manifest_sha256=pin,user_declared_label='normal',samples=[dict(inference_count=i,fault_class='normal') for i in range(128)],required_samples=128,observed_samples=128,boot_id=self.boot,npu_executed=True,agreement=1.)
            save(output,report);return {k:v for k,v in report.items() if k!='samples'}
        with contextlib.ExitStack() as stack:
            for name,value in [('LABELED_ENV',self.env),('UNIT',self.unit),('LIBRARY',self.library),('LIBRARY_SHA256',sha(self.library))]:stack.enter_context(patch.object(d,name,value))
            stack.enter_context(patch.object(d,'run',side_effect=run));stack.enter_context(patch.object(d,'clean'));stack.enter_context(patch.object(d,'unpack'));stack.enter_context(patch.object(d,'validate_candidate',return_value=bundle));stack.enter_context(patch.object(d.subprocess,'run',side_effect=probe))
            stack.enter_context(patch.object(d,'persist_candidate',side_effect=persist));stack.enter_context(patch.object(d,'validate_report'));stack.enter_context(patch.object(d,'validate_saved',return_value={'model_id':'fixture','labels':LABELS}));stack.enter_context(patch.object(d,'wait_live',side_effect=wait));restore=stack.enter_context(patch.object(d,'restore'))
            with self.assertRaisesRegex(RuntimeError,'MODEL_COMMITTED_JOB_FINALIZATION_PENDING'):d.deploy(store,self.job['id'],self.job['worker_id'],'b'*64,'a'*64,self.base/'deployed')
        restore.assert_not_called();self.assertEqual(json.loads((self.folder/'switch.json').read_text())['state'],'COMPLETED');self.assertIn(str(self.base/'deployed'),self.env.read_text())
        self.assertNotIn(['systemctl','stop',d.SERVICE],calls);self.assertEqual(enabled,{d.NORMAL:'disabled',d.SERVICE:'enabled'})
        self.assertIn(['systemctl','enable',d.SERVICE],calls);self.assertGreaterEqual(calls.count(['systemctl','is-enabled',d.SERVICE]),4)


    def restored_tail(self):
        self.previous['normal']['enabled']=False
        save(self.folder/'previous-services.json',self.previous)
        self.t.update(state='PREVIOUS_MODEL_RESTORED',recovered_on_boot=self.oldboot,queued_start=['cabinet-normal-npu'],
            previous=self.previous,previous_services_sha256=sha(self.folder/'previous-services.json'))
        self.env.unlink();self.unit.unlink();self.write()
    def test_next_boot_requeues_active_disabled_owner_then_retry_only_repairs_job(self):
        self.restored_tail();native,run=self.patches()
        # Boot reconciliation uses its durable_save, not deploy.save. Simulate
        # interruption after the new boot's queue receipt but before job commit.
        original_save=b.durable_save
        def fail_job(path,value):
            if path.name=='job.json':raise OSError('job tail interrupted again')
            return original_save(path,value)
        with patch.object(b,'durable_save',side_effect=fail_job):
            with self.assertRaisesRegex(OSError,'interrupted again'):self.reconcile()
        self.assertIn(['systemctl','--no-block','start','cabinet-normal-npu'],[c.args[0] for c in run.call_args_list])
        transaction=json.loads((self.folder/'switch.json').read_text());self.assertEqual(transaction['recovered_on_boot'],self.boot)
        self.assertFalse(transaction['previous']['normal']['enabled']);native.assert_called_once()
        native.reset_mock();run.reset_mock();result=self.reconcile()
        self.assertEqual(result['queued_start'],[]);self.assertFalse(result['npu_inference_verified']);native.assert_not_called();run.assert_not_called()
        self.assertEqual(self.reconcile()['status'],'PASS_NO_RECOVERY')
    def test_next_boot_restored_tail_dirty_lease_does_not_queue_or_complete(self):
        self.restored_tail();native,run=self.patches();native.side_effect=ValueError('DIRTY_REQUIRES_REVIEW')
        with self.assertRaisesRegex(ValueError,'DIRTY_REQUIRES_REVIEW'):self.reconcile()
        run.assert_not_called();self.assertEqual(json.loads((self.folder/'job.json').read_text())['state'],'DEPLOYING')
        self.assertEqual(json.loads((self.folder/'switch.json').read_text())['recovered_on_boot'],self.oldboot)
    def test_next_boot_restored_tail_queue_failure_is_not_recorded_complete(self):
        self.restored_tail();native,run=self.patches();run.side_effect=RuntimeError('systemd queue failed')
        with self.assertRaisesRegex(RuntimeError,'queue failed'):self.reconcile()
        self.assertEqual(json.loads((self.folder/'job.json').read_text())['state'],'DEPLOYING')
        self.assertEqual(json.loads((self.folder/'switch.json').read_text())['recovered_on_boot'],self.oldboot)

if __name__=='__main__':unittest.main()
