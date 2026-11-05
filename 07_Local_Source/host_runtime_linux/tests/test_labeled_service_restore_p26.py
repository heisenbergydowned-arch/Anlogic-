"""Systemd recovery fault fixtures; never invoke real services/native APIs."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from labeled_npu import deploy as d
import test_labeled_persistence_p26 as fixtures


def result(state='',code=0):return SimpleNamespace(stdout=state,returncode=code)

class ServiceReadbackTests(unittest.TestCase):
    def test_enable_and_disable_require_exact_readback(self):
        for enabled in (True,False):
            before='disabled' if enabled else 'enabled';after='enabled' if enabled else 'disabled'
            with self.subTest(enabled=enabled),patch.object(d,'run',side_effect=[result(before,1 if enabled else 0),result(),result(after,0 if enabled else 1)]) as run:
                receipt=d.set_service_enabled('fixture',enabled)
                self.assertEqual(receipt['state'],after)
                self.assertEqual([c.args[0] for c in run.call_args_list],[['systemctl','is-enabled','fixture'],['systemctl','enable' if enabled else 'disable','fixture'],['systemctl','is-enabled','fixture']])
    def test_permission_denied_is_not_swallowed(self):
        with patch.object(d,'run',side_effect=[result('enabled'),result('Permission denied removing symlink',1)]) as run:
            with self.assertRaisesRegex(RuntimeError,'Permission denied'):d.set_service_enabled('fixture',False)
        self.assertEqual(run.call_args_list[-1].args[0],['systemctl','disable','fixture'])
    def test_success_exit_with_wrong_readback_is_rejected(self):
        with patch.object(d,'run',side_effect=[result('enabled'),result(),result('enabled')]):
            with self.assertRaisesRegex(ValueError,'READBACK_DIFFERS'):d.set_service_enabled('fixture',False)
    def test_failed_readback_is_not_disabled(self):
        with patch.object(d,'run',side_effect=[result('enabled'),result(),result('Failed to connect to bus: Permission denied',1),result('Access denied',1)]):
            with self.assertRaisesRegex(ValueError,'ENABLEMENT_UNVERIFIED'):d.set_service_enabled('fixture',False)
    def test_unrecognized_query_never_mutates_service(self):
        for state,code in [('',1),('disabled',0),('enabled',1),('not-found',0),('Failed to get unit file state',1),('static',0)]:
            with self.subTest(state=state,code=code),patch.object(d,'run',return_value=result(state,code)) as run:
                with self.assertRaises(ValueError):d.set_service_enabled('fixture',False)
                self.assertTrue(all(c.args[0][1] in ('is-enabled','show') for c in run.call_args_list))
    def test_absent_disabled_is_explicit_noop_but_absent_enable_fails(self):
        with patch.object(d,'run',return_value=result('not-found',1)) as run:
            self.assertEqual(d.set_service_enabled('fixture',False),dict(state='not-found',changed=False));self.assertEqual(run.call_count,1)
            with self.assertRaisesRegex(ValueError,'UNIT_NOT_FOUND'):d.set_service_enabled('fixture',True)
    def test_absent_inactive_stop_does_not_issue_failing_stop(self):
        with patch.object(d,'run',side_effect=[result('not-found',1),result('unknown',4)]) as run:
            self.assertFalse(d.service_action('fixture',False,nonblocking=True))
        self.assertEqual([c.args[0] for c in run.call_args_list],[['systemctl','is-enabled','fixture'],['systemctl','is-active','fixture']])
    def test_absent_but_loaded_active_service_is_stopped(self):
        with patch.object(d,'run',side_effect=[result('not-found',1),result('active',0),result()]) as run:
            self.assertTrue(d.service_action('fixture',False))
        self.assertEqual(run.call_args_list[-1].args[0],['systemctl','stop','fixture'])
    def test_absent_stop_activity_error_not_mistaken_for_inactive(self):
        with patch.object(d,'run',side_effect=[result('not-found',1),result('Access denied',4)]) as run:
            with self.assertRaisesRegex(ValueError,'ACTIVITY_UNVERIFIED'):d.service_action('fixture',False)
        self.assertEqual(run.call_count,2)
    def test_absent_start_is_never_queued(self):
        with patch.object(d,'run',return_value=result('not-found',1)) as run:
            with self.assertRaisesRegex(ValueError,'UNIT_NOT_FOUND'):d.service_action('fixture',True,nonblocking=True)
        self.assertEqual(run.call_count,1)
    def test_nonzero_stop_result_is_not_success(self):
        with patch.object(d,'run',side_effect=[result('disabled',1),result('Permission denied',1)]):
            with self.assertRaisesRegex(RuntimeError,'ACTION_FAILED'):d.service_action('fixture',False,nonblocking=True)
    def test_snapshot_activity_query_error_not_assumed_inactive(self):
        with patch.object(d,'run',side_effect=[result('disabled',1),result('Failed to connect to bus',1)]):
            with self.assertRaisesRegex(ValueError,'ACTIVITY_UNVERIFIED'):d.service_state('fixture')

    def missing_properties(self,**changes):
        values=dict(LoadState='not-found',ActiveState='inactive',FragmentPath='',UnitFileState='');values.update(changes)
        return ''.join(k+'='+v+'\n' for k,v in values.items())
    def test_target_board_missing_unit_error_uses_structured_proof(self):
        # Literal target observation, not a guessed error-message classifier.
        message='Failed to get unit file state for cabinet-labeled-npu.service: No such file or directory\n'
        with patch.object(d,'run',side_effect=[result(message,1),result(self.missing_properties())]) as run:
            self.assertEqual(d.set_service_enabled('cabinet-labeled-npu.service',False),dict(state='not-found',changed=False))
        self.assertEqual(run.call_args_list[-1].args[0],['systemctl','show','cabinet-labeled-npu.service','--property=LoadState,UnitFileState,FragmentPath,ActiveState'])
        self.assertFalse(any(c.args[0][1]=='disable' for c in run.call_args_list))
    def test_empty_query_output_supported_only_with_structured_absence(self):
        with patch.object(d,'run',side_effect=[result('',1),result(self.missing_properties())]):
            self.assertEqual(d.service_enablement('fixture'),'not-found')
    def test_missing_unit_stop_uses_real_target_inactive_result(self):
        with patch.object(d,'run',side_effect=[result('No such file or directory',1),result(self.missing_properties()),result('inactive',3)]) as run:
            self.assertFalse(d.service_action('fixture',False,nonblocking=True))
        self.assertFalse(any('stop' in c.args[0] for c in run.call_args_list))
    def test_error_words_never_prove_missing_if_show_fails_or_is_loaded(self):
        for proof in (result('Permission denied',1),result(self.missing_properties(LoadState='loaded',UnitFileState='disabled',FragmentPath='/etc/systemd/system/fixture.service'))):
            with self.subTest(proof=proof),patch.object(d,'run',side_effect=[result('No such file or directory',1),proof]):
                with self.assertRaisesRegex(ValueError,'ENABLEMENT_UNVERIFIED'):d.service_enablement('fixture')
    def test_permission_error_for_loaded_service_is_not_absent(self):
        proof=self.missing_properties(LoadState='loaded',ActiveState='active',UnitFileState='enabled',FragmentPath='/etc/systemd/system/fixture.service')
        with patch.object(d,'run',side_effect=[result('Permission denied',1),result(proof)]):
            with self.assertRaisesRegex(ValueError,'ENABLEMENT_UNVERIFIED'):d.set_service_enabled('fixture',False)
    def test_incomplete_duplicate_extra_or_contradictory_show_is_not_absence(self):
        valid=self.missing_properties()
        variants=[valid.replace('ActiveState=inactive\n',''),valid+'LoadState=not-found\n',valid+'Other=unexpected\n',
            valid.replace('FragmentPath=\n','FragmentPath=/etc/systemd/system/fixture.service\n'),
            valid.replace('UnitFileState=\n','UnitFileState=disabled\n'),valid.replace('ActiveState=inactive','ActiveState=active'),
            'warning\n'+valid]
        for proof in variants:
            with self.subTest(proof=proof),patch.object(d,'run',side_effect=[result('',1),result(proof)]):
                with self.assertRaisesRegex(ValueError,'ENABLEMENT_UNVERIFIED'):d.service_enablement('fixture')
    def test_show_notfound_with_failure_exit_still_rejected(self):
        with patch.object(d,'run',side_effect=[result('',1),result(self.missing_properties(),1)]):
            with self.assertRaisesRegex(ValueError,'ENABLEMENT_UNVERIFIED'):d.service_enablement('fixture')

class RestoreIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ClassifierBootTests(methodName='test_new_boot_first_classifier_restores_normal_nonblocking');self.fx.setUp();self.addCleanup(self.fx.doCleanups)
    def test_boot_first_classifier_absent_unit_is_restored_without_stop(self):
        f=self.fx;native,run=f.patches();receipt=f.reconcile()
        self.assertEqual(receipt['queued_start'],['cabinet-normal-npu']);self.assertFalse(receipt['npu_inference_verified'])
        calls=[c.args[0] for c in run.call_args_list]
        self.assertNotIn(['systemctl','disable','cabinet-labeled-npu'],calls);self.assertNotIn(['systemctl','--no-block','stop','cabinet-labeled-npu'],calls)
        self.assertIn(['systemctl','is-enabled','cabinet-labeled-npu'],calls)
    def test_boot_disable_permission_failure_does_not_commit_restoration(self):
        import json
        f=self.fx
        # Previous unit exists, so disable must run; this is not the absent-unit path.
        (f.folder/'previous-labeled.unit').write_bytes(b'previous unit')
        from normal_npu.baseline_store import durable_save,file_sha
        f.previous.update(unit_exists=True,unit_sha256=file_sha(f.folder/'previous-labeled.unit'))
        durable_save(f.folder/'previous-services.json',f.previous);f.t.update(previous=f.previous,previous_services_sha256=file_sha(f.folder/'previous-services.json'));f.write()
        native,run=f.patches();original=run.side_effect
        def command(argv,**kwargs):
            if argv==['systemctl','disable','cabinet-labeled-npu']:return result('Permission denied removing enablement symlink',1)
            return original(argv,**kwargs)
        run.side_effect=command
        with self.assertRaisesRegex(RuntimeError,'Permission denied'):f.reconcile()
        self.assertIn(['systemctl','disable','cabinet-labeled-npu'],[c.args[0] for c in run.call_args_list])
        self.assertEqual(json.loads((f.folder/'switch.json').read_text())['state'],'RESTORING_PREVIOUS_SELECTION')
        self.assertEqual(json.loads((f.folder/'job.json').read_text())['state'],'DEPLOYING')
    def test_inprocess_restore_handles_unit_absent_before_stop_and_after_delete(self):
        f=self.fx;f.env.unlink();f.unit.unlink();native,run=f.patches()
        with patch.object(d,'clean') as clean,patch.object(d,'verify_restored') as verified:
            d.restore(f.previous,f.folder,f.env,f.unit)
        clean.assert_called_once();verified.assert_called_once_with(f.previous,f.folder)
        calls=[c.args[0] for c in run.call_args_list]
        self.assertNotIn(['systemctl','stop','cabinet-labeled-npu'],calls);self.assertNotIn(['systemctl','disable','cabinet-labeled-npu'],calls)
        self.assertIn(['systemctl','start','cabinet-normal-npu'],calls)

if __name__=='__main__':unittest.main()
