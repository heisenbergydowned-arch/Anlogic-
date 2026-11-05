import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from normal_npu import staging
from normal_npu.baseline_store import file_sha


class StagingTests(unittest.TestCase):
    def test_explicit_hold_survives_missing_policy_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(staging.activation_allowed({'auto_deploy': False}, Path(d)/'absent'))

    def test_sd_policy_holds_old_auto_deploy_job(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'policy.json'
            p.write_text(json.dumps(dict(schema='cabinet-npu-deployment-policy-v1',mode='STAGE_ONLY',automatic_activation=False)))
            self.assertFalse(staging.activation_allowed({'auto_deploy': True},p))
            p.write_text('{')
            with self.assertRaises(ValueError):staging.activation_allowed({},p)

    def test_staging_never_starts_process_or_changes_selected_model(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);env=p/'normal.env';env.write_text('EXISTING_MODEL')
            archive=p/'candidate.tar.gz';archive.write_bytes(b'archive')
            manifest=b'candidate manifest';mp=p/'manifest.fixture';mp.write_bytes(manifest);pin=file_sha(mp)
            store=SimpleNamespace(env=env,folder=lambda _:p,clock=lambda:123,check=lambda _:None)
            bundle=SimpleNamespace(manifest={'model_id':'candidate-normal','labels':['normal']})
            job={'id':'j','state':'HOST_VALIDATED','auto_deploy':False}
            def unpack(a,destination,checksum):
                destination.mkdir();(destination/'manifest.json').write_bytes(manifest)
            with patch('normal_npu.learning_deploy.unpack',side_effect=unpack), \
                 patch('normal_npu.learning_deploy.validate_candidate',return_value=(bundle,{'normal_holdout_frames':700,'normal_holdout_alarm_rate':0})), \
                 patch.object(staging,'storage_status',return_value={'persistent':True,'is_sd':True}), \
                 patch('subprocess.Popen',side_effect=AssertionError('staging must not start services')):
                result=staging.stage_candidate(store,job,file_sha(archive),pin)
                self.assertEqual(result['state'],'COMPLETED')
                self.assertFalse(result['result']['deployed'])
                self.assertTrue(result['result']['saved_on_sd'])
                self.assertEqual(env.read_text(),'EXISTING_MODEL')
                self.assertFalse((p/'deploy-request.json').exists())
                self.assertEqual(staging.stage_candidate(store,job,file_sha(archive),pin),result)
                (p/'staged-bundle/manifest.json').write_text('changed')
                with self.assertRaisesRegex(ValueError,'STAGED_CANDIDATE_CHANGED'):
                    staging.stage_candidate(store,job,file_sha(archive),pin)

    def test_normal_launch_routes_held_job_to_staging(self):
        import npu_learning_cli
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);job={'worker_id':'w','state':'HOST_VALIDATED','auto_deploy':False}
            (p/'job.json').write_text(json.dumps(job))
            store=SimpleNamespace(folder=lambda _:p,lock=contextlib.nullcontext)
            with patch.object(staging,'stage_candidate',return_value={'state':'COMPLETED'}) as stage, \
                 patch('subprocess.Popen',side_effect=AssertionError('unexpected deploy')):
                self.assertEqual(npu_learning_cli.launch(store,{'job_id':'j','worker_id':'w','archive_sha256':'a','manifest_sha256':'m'}),{'state':'COMPLETED'})
                stage.assert_called_once()


if __name__=='__main__':unittest.main()
