import copy
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
import time
from unittest.mock import Mock, patch
from urllib.request import Request, build_opener

from cabinet.backhaul import BoundHTTPS, bound_connection
from cabinet.capture import CaptureRecorder
from cabinet.history import History
from cabinet.predictive import ConditionBank, Maintenance
from cabinet.protocol import Frame
from cabinet.store import Store
from cabinet.uplink import NoRedirect
from cloud_receiver import CloudStore, receiver
from export_capture import export
import test_capture as capture_fixture
from test_capture import contract, packet
from test_r31_features import condition, maintenance_header, write_json
from v4_runtime.bundle import FEATURES
from v4_runtime.import_frames import import_records


class CaptureIdentityTests(unittest.TestCase):
    def test_missing_or_unknown_build_contract_is_rejected_before_recording(self):
        for identity in [None, True, 0x202610f8]:
            value = contract()
            if identity is None:
                value.pop('pl_build_id')
            else:
                value['pl_build_id'] = identity
            with self.assertRaisesRegex(ValueError, 'PL_BUILD'):
                CaptureRecorder(dict(device_id='unit', contract=value), '/unused', '/unused.sock', value)

    def session(self, case, build):
        case.recorder.contract['pl_build_id'] = build
        original = case.observe
        def observe(**changes):
            value = packet(case.sequence + 1, case.now + 0.128)
            header = list(value['frame'].header)
            header[26] = build
            changes['frame'] = Frame(tuple(header), value['frame'].values)
            return original(**changes)
        case.observe = observe
        case.observe()
        return case.save()

    def test_current_f6_and_explicit_legacy_builds_record_export_import(self):
        for build in [0x202610f7, 0x202610f6, 0x202610f5, 0x202610f4]:
            with self.subTest(build=build):
                case = capture_fixture.CaptureTests()
                case.setUp()
                try:
                    directory = self.session(case, build)
                    exported = case.root / 'export'
                    report = export(case.review(directory), exported)
                    self.assertEqual(report['frames'], 2)
                    result = import_records(exported / 'frames.jsonl', exported / 'feature_contract.json', case.root / 'dataset')
                    self.assertEqual(result['accepted']['train'], 2)
                    self.assertEqual(result['pl_build_id'], build)
                    self.assertFalse(result['production_qualified'])
                    self.assertEqual(json.loads((case.root / 'dataset/feature_contract.json').read_text())['pl_build_id'], build)
                finally:
                    case.doCleanups()

    def test_in_session_identity_change_aborts_instead_of_mixing_builds(self):
        case = capture_fixture.CaptureTests()
        case.setUp()
        try:
            case.begin()
            value = packet(case.sequence + 1, case.now + 0.128)
            header = list(value['frame'].header)
            header[26] = 0x202610f5
            case.observe(frame=Frame(tuple(header), value['frame'].values))
            self.assertEqual(case.recorder.snapshot()['state'], 'ABORTED')
            self.assertEqual(case.recorder.snapshot()['reason'], 'PL_BUILD_IDENTITY_CHANGED')
        finally:
            case.doCleanups()

    def test_import_requires_explicit_build_and_rejects_wrong_one(self):
        case = capture_fixture.CaptureTests()
        case.setUp()
        try:
            directory = self.session(case, 0x202610f5)
            exported = case.root / 'export'
            export(case.review(directory), exported)
            value = json.loads((exported / 'feature_contract.json').read_text())
            for identity in [None, 0x202610f4]:
                changed = dict(value)
                if identity is None:
                    changed.pop('pl_build_id')
                else:
                    changed['pl_build_id'] = identity
                path = case.root / ('contract-' + str(identity) + '.json')
                write_json(path, changed)
                with self.assertRaises(ValueError):
                    import_records(exported / 'frames.jsonl', path, case.root / ('dataset-' + str(identity)))
        finally:
            case.doCleanups()


class HistoryValidityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name) / 'history.sqlite')
        self.addCleanup(self.store.close)
        self.state = dict(link='ONLINE', test=False, frame_age_ms=1, status_age_ms=1,
            frame=dict(calibration_id=7, quality=0, end_ms=100, values=dict(current=0.5, pressure=0.2)),
            status=dict(uptime_ms=101, measured_rpm=4200, requested_rpm=4300,
                        temp_raw_1_16_C=400, temp_age_ms=1, input_validity=dict(rpm=True, temperature=True)))

    def record(self):
        self.store.history.record('unit', self.state, 1)
        return self.store.history.query('unit', 0, 2)['items'][-1]

    def test_valid_current_status_and_window_metrics_have_distinct_sources(self):
        document = self.record()
        self.assertEqual(document['values']['temperature'], 25)
        self.assertEqual(document['values']['rpm'], 4200)
        self.assertTrue(all(document['measurement_validity'].values()))
        self.assertEqual(document['measurement_time_ms']['temperature'], 101)
        self.assertEqual(document['measurement_time_ms']['current'], 100)
        legacy = dict(recorded=2, valid=True, values=dict(temperature=25, rpm=4200))
        with self.store.transaction() as database:
            database.execute('INSERT INTO history_samples(device,recorded,payload) VALUES(?,?,?)',
                             ('unit', 2, json.dumps(legacy)))
        visible = self.store.history.query('unit', 2, 2)['items'][0]
        self.assertFalse(visible['valid'])
        self.assertTrue(visible['legacy_validity_unverified'])
        self.assertIsNone(visible['values']['temperature'])
        self.assertEqual(visible['unverified_legacy_values']['temperature'], 25)
        with self.store.lock:
            saved = self.store.db.execute('SELECT payload FROM history_samples WHERE recorded=2').fetchone()[0]
        self.assertEqual(json.loads(saved), legacy)

    def test_invalid_live_status_cannot_be_saved_as_valid_temperature_or_rpm(self):
        self.state['status'].update(temp_age_ms=5000, input_validity=dict(temperature=False, rpm=False))
        document = self.record()
        self.assertIsNone(document['values']['temperature'])
        self.assertIsNone(document['values']['rpm'])
        self.assertFalse(document['measurement_validity']['temperature'])
        self.assertEqual(document['values']['current'], 0.5)
        self.assertEqual(document['measurement_source']['current'], 'FRM1_WINDOW')
        self.assertIn('temperature', document['invalid_reasons'])

    def test_missing_stale_or_nonfinite_status_age_is_not_live_evidence(self):
        for age in [None, -1, 1001, float('nan'), True]:
            self.state['status_age_ms'] = age
            document = self.record()
            self.assertIsNone(document['values']['temperature'])
            self.assertIsNone(document['values']['rpm'])
            self.assertIsNone(document['values']['target_rpm'])

    def test_temperature_validity_age_and_numeric_type_are_each_required(self):
        for update in [dict(temp_age_ms=None), dict(temp_age_ms=2001), dict(temp_age_ms=float('inf')),
                       dict(temp_raw_1_16_C=True), dict(input_validity={})]:
            original = copy.deepcopy(self.state['status'])
            self.state['status'].update(update)
            self.assertIsNone(self.record()['values']['temperature'])
            self.state['status'] = original

    def test_journal_delay_and_invalid_snapshot_time_cannot_extend_freshness(self):
        self.state['snapshot_monotonic'] = 10
        with patch('cabinet.history.time.monotonic', return_value=12):
            self.assertFalse(self.record()['valid'])
        for value in [float('nan'), True, 13]:
            self.state['snapshot_monotonic'] = value
            with patch('cabinet.history.time.monotonic', return_value=12):
                self.assertFalse(self.record()['valid'])
        self.state['snapshot_monotonic'] = 11.5
        self.state['status']['temp_age_ms'] = 1800
        with patch('cabinet.history.time.monotonic', return_value=12):
            self.assertIsNone(self.record()['values']['temperature'])

    def test_stale_test_and_uncalibrated_frames_clear_all_metrics(self):
        for field, value in [('frame_age_ms', 1001), ('test', True), ('link', 'OFFLINE')]:
            original = self.state[field]
            self.state[field] = value
            self.assertFalse(self.record()['valid'])
            self.assertTrue(all(value is None for value in self.record()['values'].values()))
            self.state[field] = original
        for value in [0, True]:
            self.state['frame']['calibration_id'] = value
            self.assertFalse(self.record()['valid'])


class BaselineProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'bank.json'

    def bank(self, item):
        pin = write_json(self.path, dict(schema='cabinet-condition-bank-v1', conditions=[item]))
        return ConditionBank(self.path, pin, 0)

    def test_retagging_calibration_feature_build_sampling_or_protection_is_rejected(self):
        for key in ['calibration_id', 'feature_config_id', 'pl_build_id', 'sample_mode_id', 'protection_config_id']:
            item = condition()
            item['context'][key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.bank(item)

    def test_missing_or_tampered_original_provenance_is_rejected(self):
        from hmi_daily.cabinet.baseline import validate_profile
        legacy = condition()['baseline']
        legacy.pop('provenance')
        self.assertIs(validate_profile(legacy), legacy)
        for mutate in [lambda item: item['baseline'].pop('provenance'),
                       lambda item: item['baseline']['provenance']['feature_words'].__setitem__(8, 123),
                       lambda item: item['baseline']['provenance'].__setitem__('clock', 50000000),
                       lambda item: item['baseline'].__setitem__('signature', '0' * 64)]:
            item = condition()
            mutate(item)
            with self.assertRaises(ValueError):
                self.bank(item)

    def test_matching_original_provenance_selects_and_runtime_change_clears_window(self):
        item = condition()
        item['baseline']['center'][36] = 20
        self.bank(item)
        pin = write_json(self.path, dict(schema='cabinet-condition-bank-v1', conditions=[item]))
        state = dict(link='ONLINE', test=False, boot_id='unit', frame_age_ms=1, snapshot_monotonic=time.monotonic(),
            feature_words=[1, 1, 1] + [0] * 14, frame_header=maintenance_header(),
            frame=dict(frame_id=0, quality=0, calibration_id=1, feature_config_id=1,
                       sample_mode_id=2, bitstream_id='202610f5', values=dict.fromkeys(FEATURES, 0.0)),
            status=dict(configuration_id=1))
        state['frame']['values'].update(temp=20, rpm=1000)
        for change in [lambda value: value['feature_words'].__setitem__(8, 1),
                       lambda value: value['frame_header'].__setitem__(21, 50000000),
                       lambda value: value.pop('frame_header')]:
            maintenance = Maintenance(dict(bank=str(self.path), bank_sha256=pin, device_id='device',
                installation_id='installation', dwell_seconds=0))
            self.assertEqual(maintenance.update(state, 0)['state'], 'WARMUP')
            self.assertTrue(maintenance.predictor.rows)
            changed = copy.deepcopy(state)
            change(changed)
            self.assertEqual(maintenance.update(changed, 1)['state'], 'BASELINE_CONTEXT_MISMATCH')
            self.assertFalse(maintenance.predictor.rows)


class HTTPSAdapterTests(unittest.TestCase):
    def test_handler_uses_only_supported_context_arguments(self):
        handler = BoundHTTPS('unit0')
        handler.do_open = Mock(return_value='response')
        self.assertEqual(handler.https_open(Request('https://example.invalid')), 'response')
        factory, request = handler.do_open.call_args.args
        with patch('cabinet.backhaul.http.client.HTTPSConnection') as connection:
            factory('example.invalid', timeout=2)
        self.assertEqual(connection.call_args.kwargs, dict(context=handler.tls_context, timeout=2))
        self.assertEqual(handler.do_open.call_args.kwargs, {})

    def test_insecure_context_is_never_allowed(self):
        context = ssl._create_unverified_context()
        with self.assertRaises(ValueError):
            BoundHTTPS('unit0', context=context)

    def test_linux_socket_binding_is_preserved(self):
        stream = Mock()
        with patch('cabinet.backhaul.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), \
             patch('cabinet.backhaul.socket.socket', return_value=stream), \
             patch.object(socket, 'SO_BINDTODEVICE', 25, create=True):
            self.assertIs(bound_connection('wwan0')(('localhost', 443), 2), stream)
        stream.setsockopt.assert_called_once_with(socket.SOL_SOCKET, 25, b'wwan0\0')
        stream.connect.assert_called_once_with(('127.0.0.1', 443))

    def test_actual_bound_https_validates_certificate_and_hostname(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'openssl.cnf'
            config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\n')
            key, certificate = root / 'key.pem', root / 'cert.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-config', str(config), '-keyout', str(key), '-out', str(certificate)], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            store = CloudStore(root / 'cloud.sqlite')
            listener = receiver(('127.0.0.1', 0), store, {'unit': 'unit-token'}, 'admin')
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(certificate), str(key))
            listener.socket = context.wrap_socket(listener.socket, server_side=True)
            thread = threading.Thread(target=listener.serve_forever, daemon=True)
            thread.start()
            base = 'https://localhost:' + str(listener.server_address[1])
            try:
                with patch('cabinet.backhaul.bound_connection', return_value=socket.create_connection) as binding:
                    opener = build_opener(NoRedirect(), BoundHTTPS('unit0'))
                    with self.assertRaises(OSError):
                        opener.open(Request(base + '/api/workorders', headers={'Authorization': 'Bearer admin'}), timeout=2)
                    trusted = ssl.create_default_context(cafile=str(certificate))
                    opener = build_opener(NoRedirect(), BoundHTTPS('unit0', context=trusted))
                    with opener.open(Request(base + '/api/workorders', headers={'Authorization': 'Bearer admin'}), timeout=2) as response:
                        self.assertEqual(json.loads(response.read())['items'], [])
                    wrong_host = base.replace('localhost', '127.0.0.1')
                    with self.assertRaises(OSError):
                        opener.open(Request(wrong_host + '/api/workorders', headers={'Authorization': 'Bearer admin'}), timeout=2)
                    self.assertTrue(all(call.args == ('unit0',) for call in binding.call_args_list))
            finally:
                listener.shutdown()
                listener.server_close()
                thread.join(2)
                store.close()


if __name__ == '__main__':
    unittest.main()
