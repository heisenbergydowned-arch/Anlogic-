import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from cabinet.store import Store
from cabinet.history import replay, csv_replay
from cabinet.waveform import checksum
from cabinet.web import server
from cabinet.predictive import ConditionBank, TrendPredictor, validate_lifetime_evidence
from cabinet.backhaul import Backhaul
from v4_runtime.bundle import Bundle, FEATURES
from v4_runtime.qualification import Admission, validate_evidence
from v4_runtime.profiles import PROFILE, PL_BUILD_ID
from model_release import transition
from v4_runtime.client import V4Model
from v4_runtime.frames import synthetic_frame, binding
from cloud_receiver import CloudStore, receiver
from cabinet.uplink import Uplink
from cabinet.predictive import Maintenance
from condition_bank import publish
from test_waveform_archive import WaveRegisters, capture
from hmi_daily.cabinet.baseline import DEFAULTS, digest as baseline_digest, signature_document


ROOT = Path(__file__).resolve().parents[2]


def write_json(path, document):
    data = json.dumps(document, allow_nan=False).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def admitted_fixture(root):
    directory = root / 'bundle'
    shutil.copytree(ROOT / 'models/bundle_003', directory)
    manifest = json.loads((directory / 'runtime_manifest.json').read_text())
    origin = json.loads((directory / 'training_manifest.json').read_text())
    contract = json.loads((directory / 'feature_contract.json').read_text())
    contract['calibration_id'] = 1
    origin['source'] = manifest['source'] = 'REAL_FRM1_DECLARED'
    contract_pin = write_json(directory / 'feature_contract.json', contract)
    origin['artifacts_sha256']['feature_contract.json'] = contract_pin
    manifest['artifacts_sha256']['feature_contract.json'] = contract_pin
    origin_pin = write_json(directory / 'training_manifest.json', origin)
    manifest['artifacts_sha256']['training_manifest.json'] = origin_pin
    manifest['training_manifest_sha256'] = origin_pin
    training = json.loads((directory / 'training_validation.json').read_text())
    training['status'] = 'PASS_IMPORTED_FRAME_TRAINING_ONLY'
    manifest['artifacts_sha256']['training_validation.json'] = write_json(directory / 'training_validation.json', training)
    pin = write_json(directory / 'runtime_manifest.json', manifest)
    evidence = root / 'admission'
    evidence.mkdir()
    train, test = 'a' * 64, 'b' * 64
    documents = {
        'dataset.json': dict(source='REAL_FRM1_DECLARED', calibration_id=1, train_sessions=[train], test_sessions=[test]),
        'predictions.json': [dict(session_sha256=test, test=False, actual=label, predicted=label,
            sample_sha256=hashlib.sha256((label+str(index)).encode()).hexdigest())
                             for label in manifest['labels'] for index in range(20)],
        'graph.json': dict(model_sha256=manifest['artifacts_sha256']['model_logits_u8.onnx'],
                           dimensions=[[39, 32], [32, 16], [16, 5]], transB=[1, 1, 1], forbidden_ops=[]),
        'target.json': dict(backend='Alnpu', hardware_executed=True, pl_build_id=PL_BUILD_ID,
                            model_sha256=manifest['artifacts_sha256']['model_logits_u8.onnx'], hardware_profile=PROFILE,
                            library_sha256='c' * 64, sdk_sha256='d' * 64, cases=40, class_agreement=1,
                            max_probability_lsb_error=1, p99_ms=10)
    }
    receipt = dict(schema='cabinet-model-admission-v1', model_id=manifest['model_id'],
                   bundle_manifest_sha256=pin, hardware_profile=PROFILE, pl_build_id=PL_BUILD_ID,
                   diagnostic_policy=dict(confidence_min=0.8, margin_min=0.1), minimum_accuracy=0.95,
                   evidence_sha256={name: write_json(evidence / name, document) for name, document in documents.items()})
    receipt_pin = write_json(evidence / 'release.json', receipt)
    release = dict(bundle=str(directory), manifest_sha256=pin, directory=str(evidence), sha256=receipt_pin)
    return release, documents, receipt


def baseline():
    config = copy.deepcopy(DEFAULTS)
    config.update(device_id='device', installation_id='installation')
    config['contract'].update(feature_config_id=1, calibration_id=1, sample_mode_id=2)
    header = maintenance_header()
    provenance = signature_document(config, header, [1, 1, 1] + [0] * 14, 1)
    return dict(schema=1, source='REAL', center=[0.0] * 39, scale=[1.0] * 39, samples=100,
                id='healthy', signature=baseline_digest(provenance), provenance=provenance,
                device_id='device', installation_id='installation',
                job_id='job', rpm_min=500, rpm_max=2500, advisory_qualified=False)


def maintenance_header():
    header = [0] * 32
    header[:3] = [0x46524d31, 0x10000, 284]
    header[16:23] = [1, 1, 2, 3, 4000, 100000000, 50000]
    header[26] = 0x202610f5
    return header


def condition():
    return dict(id='low-speed', baseline=baseline(), rpm=[500, 1500], temperature=[0, 80],
                context=dict(device_id='device',installation_id='installation', feature_config_id=1, calibration_id=1,
                             sample_mode_id=2, pl_build_id=0x202610f5, protection_config_id=1))


class AdmissionTests(unittest.TestCase):
    def test_graph_audit_rejects_non_sdk_gemm_and_unsupported_ops(self):
        import importlib.util
        import onnx
        from onnx import helper
        spec=importlib.util.spec_from_file_location('audit_classifier',ROOT/'tools/audit_classifier.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        data=(ROOT/'models/bundle_003/model_logits_u8.onnx').read_bytes()
        self.assertEqual(module.audit(data)['dimensions'],[[39,32],[32,16],[16,5]])
        model=onnx.load_model_from_string(data)
        gemm=next(node for node in model.graph.node if node.op_type=='Gemm')
        for attribute in gemm.attribute:
            if attribute.name=='transB':attribute.i=0
        with self.assertRaises(ValueError):module.audit(model.SerializeToString())

    def test_formal_client_exact_binding_native_only_and_revocation(self):
        import time
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);release, unused, receipt = admitted_fixture(root)
            registry = root / 'registry';transition(registry, 'activate', 0, release)
            qualification = dict(directory=release['directory'],sha256=release['sha256'],registry=str(registry))
            client = V4Model(dict(bundle=release['bundle'],bundle_manifest_sha256=release['manifest_sha256'],
                qualified=True,evidence=release['sha256'],qualification=qualification,model_id=receipt['model_id'],socket='/unused'))
            values = client.bundle.json('runtime_golden.json')['vectors'][0]['physical']
            frame = synthetic_frame(values,1,1000,client.bundle.contract,PL_BUILD_ID)
            request = client.request(frame,dict(session_id='session',boot_id='boot',generation=1,now_ms=1000,received_at=time.monotonic()))
            unused, encoded = client.bundle.encode(values)
            output = [255,0,0,0,0]
            reply = dict(binding(request),schema='cabinet-npu-result-v4',backend='Alnpu',formal=True,qualified=True,
                test_backend=False,mode='FORMAL_DIAGNOSTIC',admission_sha256=release['sha256'],
                hardware_profile=PROFILE,daemon_instance='a'*32,input_u8=encoded,output_u8=output,
                probabilities=client.bundle.decode(output),execution_model=client.bundle.manifest['execution_model'],
                postprocess=client.bundle.postprocess['algorithm'])
            self.assertTrue(client.validate_reply(reply,request,1)['formal'])
            for key,value in [('backend','ORT_CPU_REFERENCE'),('formal',1),('admission_sha256','0'*64),('generation',2)]:
                with self.subTest(key=key),self.assertRaises(ValueError):client.validate_reply(dict(reply,**{key:value}),request,1)
            transition(registry,'revoke',1)
            with self.assertRaises(ValueError):client.validate_reply(reply,request,1)

    def test_activate_revoke_rollback_and_stale_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            release, unused, receipt = admitted_fixture(root)
            registry = root / 'registry'
            transition(registry, 'activate', 0, release)
            config = dict(directory=release['directory'], sha256=release['sha256'], registry=str(registry))
            bundle = Bundle(release['bundle'], release['manifest_sha256'], qualification=config)
            self.assertEqual(bundle.admission.assert_current('c' * 64), release['sha256'])
            with self.assertRaises(ValueError):
                bundle.admission.assert_current('e' * 64)
            transition(registry, 'revoke', 1)
            with self.assertRaises(ValueError):
                bundle.admission.assert_current()
            transition(registry, 'rollback', 2, release)
            with self.assertRaises(ValueError):
                bundle.admission.assert_current()
            self.assertTrue(Bundle(release['bundle'], release['manifest_sha256'], qualification=config).admission)
            with self.assertRaises(ValueError):
                transition(registry, 'revoke', 2)

    def test_synthetic_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            release, unused, receipt = admitted_fixture(root)
            candidate = ROOT / 'models/bundle_003'
            release['bundle'] = str(candidate)
            release['manifest_sha256'] = hashlib.sha256((candidate / 'runtime_manifest.json').read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                transition(root / 'registry', 'activate', 0, release)

    def test_fail_closed_for_each_independent_evidence_gate(self):
        mutations = [
            ('dataset.json', lambda value: value.update(train_sessions=['b' * 64])),
            ('target.json', lambda value: value.update(hardware_executed=False)),
            ('target.json', lambda value: value.update(backend='ORT_CPU_REFERENCE')),
            ('target.json', lambda value: value.update(pl_build_id=0x202610f4)),
            ('target.json', lambda value: value.update(max_probability_lsb_error=2)),
            ('target.json', lambda value: value.update(class_agreement=True)),
            ('graph.json', lambda value: value.update(forbidden_ops=['MaxPool'])),
            ('predictions.json', lambda value: value[0].update(test=True)),
            ('predictions.json', lambda value: value[1].update(sample_sha256=value[0]['sample_sha256'])),
            ('predictions.json', lambda value: [row.update(predicted='normal') for row in value])]
        for filename, mutate in mutations:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                release, documents, receipt = admitted_fixture(root)
                mutate(documents[filename])
                receipt['evidence_sha256'][filename] = write_json(Path(release['directory']) / filename, documents[filename])
                release['sha256'] = write_json(Path(release['directory']) / 'release.json', receipt)
                with self.assertRaises(ValueError):
                    transition(root / 'registry', 'activate', 0, release)

    def test_tampered_receipt_or_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            release, documents, receipt = admitted_fixture(root)
            (Path(release['directory']) / 'target.json').write_text('{}')
            with self.assertRaises(ValueError):
                transition(root / 'registry', 'activate', 0, release)


class HistoryTests(unittest.TestCase):
    def test_verified_archive_replay_is_read_only(self):
        from cabinet.maintenance import archive_database
        from history_server import ArchiveStore
        unused,records=capture(WaveRegisters())
        record=records[0][1];identity=checksum(record)
        self.store.waveform(identity,record,'device')
        archive_database(self.path,Path(self.folder.name)/'archive')
        archive_path=Path(self.folder.name)/'archive/events.sqlite3'
        before=hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive=ArchiveStore(archive_path)
        try:
            self.assertEqual(archive.history.get_waveform('device',identity)['raw'],record)
            with self.assertRaises(ValueError):archive.acknowledge('event')
        finally:archive.close()
        self.assertEqual(hashlib.sha256(archive_path.read_bytes()).hexdigest(),before)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'history.sqlite'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def test_pagination_invalid_nulls_and_restart(self):
        state = dict(link='ONLINE', frame_age_ms=1, test=False,
                     status_age_ms=1,
                     frame=dict(calibration_id=1, quality=0, values=dict(current=2)),
                     status=dict(measured_rpm=1000, temp_raw_1_16_C=400, temp_age_ms=1,
                                 input_validity=dict(rpm=True, temperature=True)))
        for index in range(4):
            self.store.history.record('device', state, index)
        self.store.history.record('other', state, 5)
        self.store.history.record('device', dict(state, test=True), 6)
        first = self.store.history.query('device', 0, 10, limit=2)
        second = self.store.history.query('device', 0, 10, after=first['next_after'], limit=2)
        self.assertEqual([item['id'] for item in first['items'] + second['items']], [1, 2, 3, 4])
        last = self.store.history.query('device', 6, 6)['items'][0]
        self.assertFalse(last['valid']);self.assertIsNone(last['values']['current'])
        self.store.close();self.store = Store(self.path)
        self.assertEqual(len(self.store.history.query('device', 0, 10)['items']), 5)
        for args in [(float('nan'), 5, 0, 1), (10, 0, 0, 1), (0, 1, -1, 1), (0, 1, 0, 501)]:
            with self.assertRaises(ValueError):
                self.store.history.query('device', *args)

    def test_lossless_signed_axes_timestamps_and_device_isolation(self):
        unused, records = capture(WaveRegisters())
        record = records[0][1]
        identity = checksum(record)
        self.store.waveform(identity, record, 'device')
        result = self.store.history.get_waveform('device', identity)
        self.assertEqual(result['raw'], record)
        self.assertEqual(result['streams'][0][0]['xyz'], [-32768, -1, -32768])
        self.assertEqual(result['streams'][1][0]['ticks'], str(1 << 32))
        self.assertIn('x_raw', csv_replay(result))
        with self.assertRaises(KeyError):
            self.store.history.get_waveform('other', identity)
        with self.store.transaction() as database:
            database.execute('UPDATE waveforms SET payload=? WHERE record_id=?', ('{}', identity))
        with self.assertRaises(ValueError):
            self.store.history.get_waveform('device', identity)

    def test_real_http_auth_pagination_replay_csv_and_errors(self):
        service = Mock(config=dict(device_id='device'), store=self.store)
        listener = server('127.0.0.1', 0, service, token='secret')
        worker = threading.Thread(target=listener.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(listener.server_address[1])
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(base + '/api/history/samples')
            self.assertEqual(error.exception.code, 401)
            request = Request(base + '/api/history/samples?start=nan', headers={'Authorization': 'Bearer secret'})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 400)
            unused, records = capture(WaveRegisters())
            record = records[0][1];identity = checksum(record)
            self.store.waveform(identity, record, 'device')
            for suffix in ['/history', '/api/history/waveforms', '/api/history/waveform?id=' + identity,
                           '/api/history/waveform?id=' + identity + '&format=csv']:
                with urlopen(Request(base + suffix, headers={'Authorization': 'Bearer secret'})) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.read())
        finally:
            listener.shutdown();listener.server_close();worker.join(2)


class MaintenanceTests(unittest.TestCase):
    def test_bank_publish_conflict_and_byte_exact_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'private'/'bank.json'
            first=dict(schema='cabinet-condition-bank-v1',conditions=[condition()])
            pin=publish(path,first,None)
            second=copy.deepcopy(first);second['conditions'][0]['id']='replacement'
            next_pin=publish(path,second,pin)
            archived=path.with_name(path.name+'.'+pin+'.archived')
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(),pin)
            with self.assertRaises(ValueError):publish(path,first,pin)
            self.assertEqual(publish(path,json.loads(archived.read_text()),next_pin),pin)

    def test_integrated_condition_prediction_from_real_protocol_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bank.json';item=condition();item['baseline']['center'][36]=20
            pin=write_json(path,dict(schema='cabinet-condition-bank-v1',conditions=[item]))
            maintenance=Maintenance(dict(bank=str(path),bank_sha256=pin,device_id='device',installation_id='installation',dwell_seconds=0,
                forecast=dict(min_samples=5,min_span_s=4,max_gap_s=2)))
            values={name:0.0 for name in FEATURES};values.update(temp=20,rpm=1000)
            state=dict(link='ONLINE',test=False,boot_id='boot1',frame_age_ms=1,
                frame_header=maintenance_header(),feature_words=[1,1,1]+[0]*14,
                status=dict(configuration_id=1),frame=dict(quality=0,calibration_id=1,feature_config_id=1,
                    sample_mode_id=2,bitstream_id='202610f5',values=values))
            for index in range(5):
                values['rms_a_x']=1+index*0.1;state['frame']['frame_id']=index
                state['frame_header'][3]=index
                state['snapshot_monotonic']=index+0.001
                with patch('time.monotonic',return_value=index+0.001):
                    result=maintenance.update(state,index)
            self.assertEqual(result['state'],'THRESHOLD_FORECAST')
            self.assertAlmostEqual(result['threshold_crossing_s'],46)
            self.assertFalse(result['control_authority']);self.assertFalse(result['advisory_qualified'])
            self.assertIsNone(result['remaining_life_s'])
            state['test']=True
            self.assertEqual(maintenance.update(state,5)['state'],'INVALID_INPUT')

    def test_flat_negative_noisy_and_excess_horizon_never_invent_rul(self):
        for scores in [[5,4,3,2,1],[1,3,1,4,2],[1,1.0001,1.0002,1.0003,1.0004]]:
            predictor=TrendPredictor(min_samples=5,min_span_s=4,max_gap_s=2,horizon_s=10)
            for timestamp,score in enumerate(scores):result=predictor.update('same',timestamp,score)
            self.assertIsNone(result['remaining_life_s'])
            self.assertNotEqual(result['state'],'THRESHOLD_FORECAST')

    def test_condition_selection_dwell_coverage_conflict_and_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bank.json'
            first = condition();second = copy.deepcopy(first)
            second.update(id='high-speed', rpm=[1500, 2400])
            pin = write_json(path, dict(schema='cabinet-condition-bank-v1', conditions=[first, second]))
            bank = ConditionBank(path, pin, 5)
            context = first['context']
            self.assertEqual(bank.select(context, 1000, 20, 0, True)['state'], 'WAIT_STABLE')
            self.assertEqual(bank.select(context, 1000, 20, 5, True)['condition']['id'], 'low-speed')
            self.assertEqual(bank.select(context, 1500, 20, 6, True)['state'], 'WAIT_STABLE')
            self.assertEqual(bank.select(context, 1500, 20, 11, True)['condition']['id'], 'high-speed')
            self.assertEqual(bank.select(dict(context, calibration_id=2), 1000, 20, 12, True)['state'], 'OUT_OF_COVERAGE')
            self.assertEqual(bank.select(context, None, None, 13, False)['state'], 'INVALID_INPUT')
            second['rpm'] = [1000, 2400]
            pin = write_json(path, dict(schema='cabinet-condition-bank-v1', conditions=[first, second]))
            self.assertEqual(ConditionBank(path, pin, 0).select(context, 1200, 20, 0, True)['state'], 'AMBIGUOUS')

    def test_forecast_numeric_flat_reset_gap_context_and_bounds(self):
        predictor = TrendPredictor(threshold=6, min_samples=5, min_span_s=4, max_gap_s=2)
        for timestamp in range(5):
            result = predictor.update('condition', timestamp, 1 + timestamp * 0.1)
        self.assertEqual(result['state'], 'THRESHOLD_FORECAST')
        self.assertAlmostEqual(result['threshold_crossing_s'], 46)
        self.assertIsNone(result['remaining_life_s'])
        self.assertEqual(predictor.update('other', 5, 2)['state'], 'WARMUP')
        self.assertEqual(predictor.update('other', 99, 2)['state'], 'WARMUP')
        self.assertEqual(predictor.update('other', 100, 2, False)['state'], 'INVALID_INPUT')
        for timestamp in range(6):
            result = predictor.update('constant', timestamp, 1)
        self.assertEqual(result['state'], 'NO_RELIABLE_DEGRADATION_TREND')

    def test_default_forecast_covers_ten_minutes_at_fast_poll_rate(self):
        for gap in (90, 0.5):
            predictor = TrendPredictor(max_gap_s=gap)
            for index in range(6001):
                timestamp = index * 0.128
                score = 1 + timestamp * 0.001
                result = predictor.update('condition', timestamp, score)
                self.assertLessEqual(len(predictor.rows), 256)
                if timestamp >= 600:
                    self.assertEqual(result['state'], 'THRESHOLD_FORECAST')
                    self.assertAlmostEqual(result['threshold_crossing_s'], (6 - score) / 0.001, places=6)
            self.assertIsNone(result['remaining_life_s'])
            self.assertEqual(predictor.update('condition', timestamp + gap + 1, score)['state'], 'WARMUP')
        predictor = TrendPredictor(min_samples=256, min_span_s=240, max_gap_s=2)
        for timestamp in range(301):
            result = predictor.update('condition', timestamp, 1 + timestamp * 0.001)
        self.assertEqual(result['state'], 'THRESHOLD_FORECAST')

    def test_offline_reset_and_stale_public_state_remove_forecast(self):
        from cabinet.service import Service
        from test_local_display import CONFIG
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bank.json'
            pin=write_json(path,dict(schema='cabinet-condition-bank-v1',conditions=[condition()]))
            maintenance=Maintenance(dict(bank=str(path),bank_sha256=pin,device_id='device',installation_id='installation'))
            maintenance.predictor.update('old',0,1)
            result=maintenance.update(dict(link='OFFLINE'),1)
            self.assertEqual(result['state'],'INVALID_INPUT')
            self.assertEqual(maintenance.predictor.rows,[])
            config=copy.deepcopy(CONFIG);config['database']=str(Path(folder)/'service.sqlite')
            service=Service(config,mock=True)
            try:
                service.set(maintenance=dict(state='THRESHOLD_FORECAST',threshold_crossing_s=10,
                    remaining_life_s=10,lifetime_qualified=True))
                result=service.public_state()['maintenance']
                self.assertEqual(result['state'],'INVALID_INPUT')
                self.assertIsNone(result['remaining_life_s'])
                self.assertNotIn('threshold_crossing_s',result)
            finally:service.store.close()

    def test_rul_requires_disjoint_observed_failure_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lifetime.json';item = condition()
            evidence = dict(schema='cabinet-lifetime-calibration-v1', source='REAL_RUN_TO_FAILURE',
                            condition_id=item['id'], baseline_id=item['baseline']['id'], threshold=6,
                            context=item['context'], threshold_semantics='OBSERVED_END_OF_LIFE',
                            train_sessions=['one', 'two'], held_out=[dict(session='three', actual_seconds=100, predicted_seconds=105),
                                                                    dict(session='four', actual_seconds=200, predicted_seconds=190)])
            pin = write_json(path, evidence)
            self.assertTrue(validate_lifetime_evidence(dict(path=str(path), sha256=pin), item, 6))
            evidence['held_out'][0]['session'] = 'one'
            pin = write_json(path, evidence)
            with self.assertRaises(ValueError):
                validate_lifetime_evidence(dict(path=str(path), sha256=pin), item, 6)

    def test_backhaul_activation_never_shell_and_opt_in(self):
        links = [dict(medium='ethernet', interface='eth0', connection_uuid='12345678-1234-1234-1234-123456789abc'),
                 dict(medium='cellular', interface='wwan0', connection_uuid='22345678-1234-1234-1234-123456789abc')]
        runner = Mock()
        backhaul = Backhaul(dict(links=links), runner=runner, clock=lambda: 0)
        with patch('cabinet.backhaul.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = [OSError('wired down'), Mock()]
            backhaul.open(Request('https://example.invalid'), 1)
            self.assertEqual(backhaul.status['medium'], 'cellular')
            runner.assert_not_called()
        backhaul = Backhaul(dict(links=links, allow_network_changes=True), runner=runner)
        with patch('cabinet.backhaul.urllib.request.build_opener'):
            backhaul.open(Request('https://example.invalid'), 1)
        self.assertFalse(runner.call_args.kwargs['shell'])
        self.assertIn('uuid', runner.call_args.args[0])


class CloudTests(unittest.TestCase):
    def test_actual_tls_rejects_untrusted_server_then_accepts_explicit_ca(self):
        import os,ssl,subprocess
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);certificate=root/'cert.pem';key=root/'key.pem'
            configuration=root/'openssl.cnf'
            configuration.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\n')
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-config',str(configuration),
                '-keyout',str(key),'-out',str(certificate)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            cloud=CloudStore(root/'cloud.sqlite');local=Store(root/'edge.sqlite')
            listener=receiver(('127.0.0.1',0),cloud,{'device':'secret'},'admin')
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(str(certificate),str(key))
            listener.socket=context.wrap_socket(listener.socket,server_side=True)
            worker=threading.Thread(target=listener.serve_forever,daemon=True);worker.start()
            url='https://localhost:'+str(listener.server_address[1])+'/v1/devices/events'
            try:
                local.event(dict(event_id='tls',event_revision=1,device_id='device',source='MODEL',notify=True))
                with patch.dict(os.environ,{'CABINET_UPLINK_TOKEN':'secret'}):
                    self.assertEqual(Uplink(dict(url=url),local).once(),0)
                    local.reset_retry_clock()
                    trusted=ssl.create_default_context(cafile=str(certificate))
                    with patch('ssl._create_default_https_context',return_value=trusted):
                        self.assertEqual(Uplink(dict(url=url),local).once(),1)
                self.assertFalse(local.pending())
            finally:
                listener.shutdown();listener.server_close();worker.join(2);cloud.close();local.close()

    def test_real_http_durable_outbox_cloud_idempotency_and_device_auth(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cloud=CloudStore(root/'cloud.sqlite');local=Store(root/'edge.sqlite')
            listener=receiver(('127.0.0.1',0),cloud,{'device':'secret','other':'other-secret'},'admin')
            worker=threading.Thread(target=listener.serve_forever,daemon=True);worker.start()
            base='http://127.0.0.1:'+str(listener.server_address[1])
            event=dict(event_id='event',event_revision=1,device_id='device',source='PREDICTION',code='DEGRADATION_FORECAST',notify=True)
            try:
                local.event(event)
                with patch.dict(os.environ,{'CABINET_UPLINK_TOKEN':'secret'}):
                    uplink=Uplink(dict(url=base+'/v1/devices/events',loopback_test=True),local)
                    self.assertEqual(uplink.once(),1);self.assertFalse(local.pending())
                self.assertEqual(cloud.receive(event)['event_revision'],1)
                with self.assertRaises(ValueError):cloud.receive(dict(event,code='changed'))
                with urlopen(Request(base+'/api/workorders?device=device',headers={'Authorization':'Bearer admin'})) as response:
                    self.assertEqual(len(json.loads(response.read())['items']),1)
                local.event(dict(event,event_revision=2,device_id='other'))
                with patch.dict(os.environ,{'CABINET_UPLINK_TOKEN':'secret'}):
                    self.assertEqual(uplink.once(),0)
                self.assertTrue(local.pending() or uplink.last_error)
                cloud.close();cloud=CloudStore(root/'cloud.sqlite')
                self.assertEqual(len(cloud.list()['items']),1)
            finally:
                listener.shutdown();listener.server_close();worker.join(2);cloud.close();local.close()


if __name__ == '__main__':
    unittest.main()
