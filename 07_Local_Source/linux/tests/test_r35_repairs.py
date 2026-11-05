import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import threading
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from cabinet.freshness import aged_ms
from cabinet.model import Model
from cabinet.predictive import Maintenance
from cabinet.service import Service
from cabinet.web import server
from run_edge import load_config
from test_chain import CONFIG, real_frame
from test_r31_features import admitted_fixture, condition, maintenance_header, write_json, FEATURES
from model_release import transition
from v4_runtime.client import V4Model

ROOT=Path(__file__).resolve().parents[2]


class ModelAdmissionRepairTests(unittest.TestCase):
    def test_all_legacy_backends_reject_formal_configuration(self):
        for backend in ['disabled','mock','onnx','command','tcp','unix']:
            for evidence in ['unreviewed','a'*64]:
                config=dict(backend=backend,qualified=True,evidence=evidence)
                with self.subTest(backend=backend,evidence=evidence),self.assertRaises(ValueError):Model(config)

    def test_exact_boolean_and_complete_pinned_v4_required(self):
        for flag in [1,'true',None]:
            with self.subTest(flag=flag),self.assertRaises(ValueError):Model(dict(backend='npu_v4',qualified=flag))
        for qualification in [None,{},dict(sha256='g'*64,directory='x',registry='y')]:
            with self.subTest(qualification=qualification),self.assertRaises(ValueError):
                Model(dict(backend='npu_v4',qualified=True,evidence='g'*64,qualification=qualification))

    def test_load_config_and_service_block_counterexample_before_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=copy.deepcopy(CONFIG)
            config['database']=str(Path(temporary)/'events.sqlite3')
            config['model'].update(backend='onnx',qualified=True,evidence='NONEXISTENT_EVIDENCE')
            settings=Path(temporary)/'config.json';settings.write_text(json.dumps(config))
            with self.assertRaises(ValueError):load_config(settings)
            with self.assertRaises(ValueError):Service(config)
            self.assertFalse(Path(config['database']).exists())

    def test_external_cpu_claims_never_become_formal(self):
        import sys
        config=dict(backend='command',model_id='fixture',qualified=False,evidence=None,timeout_ms=2000,
            command=[sys.executable,'-B','-c',
                'import json,sys; result=json.load(sys.stdin); result.update(probabilities=[1,0,0,0,0],'
                'backend="Alnpu",formal=True,qualified=True,test_backend=False); print(json.dumps(result))'])
        model=Model(config);result=model.infer(real_frame())
        self.assertEqual(result['backend'],'EXTERNAL_COMMAND')
        self.assertFalse(result['formal']);self.assertFalse(result['qualified'])
        self.assertFalse(model.formal_result(dict(result,formal=True,qualified=True)))

    def test_only_current_admitted_v4_can_publish_formal_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);release,unused,receipt=admitted_fixture(root)
            registry=root/'registry';transition(registry,'activate',0,release)
            config=dict(backend='npu_v4',qualified=True,evidence=release['sha256'],
                qualification=dict(directory=release['directory'],sha256=release['sha256'],registry=str(registry)),
                bundle=release['bundle'],bundle_manifest_sha256=release['manifest_sha256'],model_id=receipt['model_id'])
            model=Model(config);model.v4=V4Model(config)
            result=dict(formal=True,qualified=True,test=False,backend='Alnpu',admission_sha256=release['sha256'])
            self.assertTrue(model.formal_result(result))
            for key,value in [('backend','CPU_ONNX'),('formal',1),('qualified',False),('test',True),('admission_sha256','0'*64)]:
                with self.subTest(key=key):self.assertFalse(model.formal_result(dict(result,**{key:value})))
            transition(registry,'revoke',1)
            with self.assertRaises(ValueError):model.formal_result(result)


class MaintenanceAgeRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        root=Path(self.temporary.name);item=condition();item['baseline']['center'][36]=20
        bank=root/'bank.json';pin=write_json(bank,dict(schema='cabinet-condition-bank-v1',conditions=[item]))
        self.config=dict(bank=str(bank),bank_sha256=pin,device_id='device',installation_id='installation',dwell_seconds=0,
            forecast=dict(min_samples=5,min_span_s=0.5,max_gap_s=2))
        self.state=dict(link='ONLINE',test=False,boot_id='boot',frame_age_ms=1,snapshot_monotonic=100,
            frame_header=maintenance_header(),feature_words=[1,1,1]+[0]*14,status=dict(configuration_id=1),
            frame=dict(frame_id=0,quality=0,calibration_id=1,feature_config_id=1,sample_mode_id=2,
                bitstream_id='202610f5',values=dict.fromkeys(FEATURES,0.0)))
        self.state['frame']['values'].update(temp=20,rpm=1000,rms_a_x=1)
        self.state['frame_header'][3]=0

    def update(self,maintenance,sequence,delay=0,wall=0):
        self.state['snapshot_monotonic']=100+sequence*0.2
        self.state['frame']['frame_id']=self.state['frame_header'][3]=sequence
        self.state['frame']['values']['rms_a_x']=1+sequence*0.1
        with patch('time.monotonic',return_value=self.state['snapshot_monotonic']+delay):
            return maintenance.update(self.state,wall)

    def test_queue_stale_counterexample_is_invalid_and_resets_forecast(self):
        maintenance=Maintenance(self.config)
        for sequence in range(5):result=self.update(maintenance,sequence)
        self.assertEqual(result['state'],'THRESHOLD_FORECAST')
        self.assertEqual(self.update(maintenance,5,delay=120)['state'],'INVALID_INPUT')
        self.assertFalse(maintenance.predictor.rows)
        self.assertEqual(self.update(maintenance,6)['state'],'WARMUP')

    def test_capture_time_not_wall_clock_or_processing_delay_controls_slope(self):
        results=[]
        for delayed in [False,True]:
            maintenance=Maintenance(self.config)
            for sequence in range(5):
                result=self.update(maintenance,sequence,delay=0.1*sequence if delayed else 0,wall=sequence*10000)
            results.append(result)
        self.assertAlmostEqual(results[0]['slope_per_second'],results[1]['slope_per_second'])
        self.assertAlmostEqual(results[0]['threshold_crossing_s'],results[1]['threshold_crossing_s'])

    def test_missing_malformed_and_future_snapshot_rejected(self):
        for snapshot in [None,True,float('nan'),float('inf'),101]:
            state=copy.deepcopy(self.state);state['snapshot_monotonic']=snapshot
            with self.subTest(snapshot=snapshot),patch('time.monotonic',return_value=100):
                self.assertEqual(Maintenance(self.config).update(state,0)['state'],'INVALID_INPUT')
        state=copy.deepcopy(self.state);state.pop('snapshot_monotonic')
        self.assertEqual(Maintenance(self.config).update(state,0)['state'],'INVALID_INPUT')

    def test_boot_and_reordered_frame_reset_window(self):
        maintenance=Maintenance(self.config)
        self.update(maintenance,2)
        self.assertEqual(self.update(maintenance,1)['state'],'INVALID_INPUT')
        self.update(maintenance,3);self.state['boot_id']='new-boot'
        self.assertEqual(self.update(maintenance,4)['state'],'WARMUP')

    def test_age_policy_matches_history_without_accepting_boolean_age(self):
        self.assertEqual(aged_ms(dict(frame_age_ms=1,snapshot_monotonic=100),'frame_age_ms',now=101),1001)
        self.assertIsNone(aged_ms(dict(frame_age_ms=True),'frame_age_ms'))
        self.assertIsNone(aged_ms(dict(frame_age_ms=1),'frame_age_ms',require_snapshot=True))


class AuthenticatedPageRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        config=copy.deepcopy(CONFIG);config['database']=str(Path(self.temporary.name)/'events.sqlite3')
        self.service=Service(config);self.addCleanup(self.service.close)
        self.http=server('127.0.0.1',0,self.service,token='REVIEW_ONLY_NOT_A_REAL_SECRET')
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close_http)
        self.base='http://127.0.0.1:'+str(self.http.server_address[1])

    def close_http(self):
        self.http.shutdown();self.http.server_close();self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def test_shell_is_public_but_all_data_stays_authenticated(self):
        for route in ['/','/history']:
            with urlopen(self.base+route,timeout=2) as response:
                html=response.read().decode();self.assertEqual(response.status,200)
                self.assertIn('id="token"',html)
                self.assertNotIn('REVIEW_ONLY_NOT_A_REAL_SECRET',html)
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        for route in ['/api/status','/api/events','/api/history/samples','/api/maintenance','/health']:
            with self.subTest(route=route),self.assertRaises(HTTPError) as failure:urlopen(self.base+route,timeout=2)
            self.assertEqual(failure.exception.code,401)

    def test_explicit_token_fetch_works_without_cookie_or_query_bypass(self):
        request=Request(self.base+'/api/status',headers={'Authorization':'Bearer REVIEW_ONLY_NOT_A_REAL_SECRET'})
        with urlopen(request,timeout=2) as response:self.assertEqual(json.load(response)['link'],'OFFLINE')
        for route,token in [('/api/status','wrong'),('/api/status?token=REVIEW_ONLY_NOT_A_REAL_SECRET','')]:
            request=Request(self.base+route,headers={'Authorization':'Bearer '+token})
            with self.assertRaises(HTTPError) as failure:urlopen(request,timeout=2)
            self.assertEqual(failure.exception.code,401)

    def test_writes_are_protected_and_browser_token_is_not_persisted(self):
        request=Request(self.base+'/api/ack',data=b'{"event_id":"fixture"}',headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as failure:urlopen(request,timeout=2)
        self.assertEqual(failure.exception.code,401)
        html=(ROOT/'linux/static/index.html').read_text()
        self.assertIn('headers:authHeaders()',html);self.assertIn("...authHeaders()",html)
        self.assertNotIn('localStorage',html);self.assertNotIn('sessionStorage',html)
