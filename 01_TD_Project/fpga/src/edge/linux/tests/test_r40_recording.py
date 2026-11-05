import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid
import zipfile

import test_capture as fixtures
from cabinet.capture import CaptureRecorder
from cabinet.capture_web import archive, command, status, verified_session
from cabinet.protocol import Frame
from cabinet.web import server

ROOT = Path(__file__).resolve().parents[2]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


prepare = module('r40_prepare', ROOT / 'deployment/prepare_recording.py')
verify = module('r40_verify', ROOT / 'deployment/verify_recording.py')


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.contract = fixtures.contract()
        self.contract['pl_build_id'] = 0x202610f7
        self.config = dict(device_id='HOST_R40_NO_HARDWARE', contract=copy.deepcopy(self.contract),
                           control=dict(enabled=False), model=dict(backend='disabled'))
        (self.root / 'capture').mkdir(mode=0o700)
        self.recorder = CaptureRecorder(self.config, self.root / 'capture', self.root / 'run/capture.sock', self.contract)
        self.service = SimpleNamespace(recorder=self.recorder)
        self.sequence = 0

    def observe(self):
        self.sequence += 1
        now = time.monotonic()
        packet = fixtures.packet(self.sequence, now)
        header = list(packet['frame'].header)
        header[26] = 0x202610f7
        packet['frame'] = Frame(tuple(header), packet['frame'].values)
        self.recorder.observe(packet, now)

    def payload(self, mode='REAL'):
        return dict(expected_boot=self.recorder.snapshot()['boot'], installation_id='HOST_ONLY_INSTALL',
                    operator='HOST_OPERATOR', label='unlabelled', duration_s=60, capture_mode=mode,
                    bitstream_sha256='1' * 64, calibration_evidence_sha256='2' * 64,
                    note='TEST FIXTURE, NOT BOARD OR LABEL EVIDENCE')

    def completed(self, mode='REAL'):
        self.observe()
        self.recorder.begin(self.payload(mode), time.monotonic())
        for unused in range(3):
            self.observe()
        self.recorder.finish('COMPLETED', 'OPERATOR_STOP', time.monotonic())
        return self.recorder.session_dir

    def test_absent_recorder_reports_not_configured_without_fake_success(self):
        self.assertFalse(status(SimpleNamespace())['available'])
        with self.assertRaises(ValueError):
            command(SimpleNamespace(), 'start', {})

    def test_f7_archive_keeps_original_32_plus_39_words_and_checksums(self):
        folder = self.completed()
        export, size = archive(self.service, folder.name)
        with export:
            data = export.read()
        self.assertEqual(len(data), size)
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            self.assertIsNone(package.testzip())
            for name in ('session.json', 'feature_contract.json', 'summary.json', 'frames.jsonl'):
                self.assertEqual(package.read(folder.name + '/' + name), (folder / name).read_bytes())
            row = json.loads(package.read(folder.name + '/frames.jsonl').splitlines()[0])
            self.assertEqual(row['header'][26], 0x202610f7)
            self.assertEqual(len(row['header']), 32)
            self.assertEqual(len(row['feature_words']), 39)
            self.assertFalse(json.loads(package.read(folder.name + '/download.json'))['training_ready'])
        report = verify.verify(folder)
        self.assertEqual(report['counts']['frames'], 3)
        self.assertFalse(report['training_qualified'])

    def test_diagnostic_bytes_can_be_downloaded_but_never_real_candidate(self):
        folder = self.completed('DIAGNOSTIC')
        report = verify.verify(folder)
        self.assertEqual(report['state'], 'DIAGNOSTIC_SAVED')
        self.assertEqual(report['counts']['accepted'], 0)
        self.assertFalse(report['real_candidate'])

    def test_unfinalized_empty_traversal_and_symlink_are_rejected(self):
        self.observe()
        self.recorder.begin(self.payload(), time.monotonic())
        with self.assertRaises(ValueError):
            archive(self.service, self.recorder.session_dir.name)
        self.recorder.finish('ABORTED', 'NO_FRAMES', time.monotonic())
        for name in [self.recorder.session_dir.name, '../escape', 'not-a-uuid']:
            with self.assertRaises(ValueError):
                archive(self.service, name)
        folder = self.completed()
        (folder / 'frames.jsonl').unlink()
        (folder / 'frames.jsonl').symlink_to(self.root / 'elsewhere')
        with self.assertRaises(ValueError):
            verified_session(self.recorder.directory, folder.name)

    def test_tampered_frames_and_summary_counts_rejected(self):
        folder = self.completed()
        (folder / 'frames.jsonl').write_text('{}\n')
        with self.assertRaises(ValueError):
            verify.verify(folder)
        folder = self.completed()
        summary = json.loads((folder / 'summary.json').read_text())
        summary['frames'] = summary['durable_frames'] = 9
        (folder / 'summary.json').write_text(json.dumps(summary))
        with self.assertRaises(ValueError):
            verify.verify(folder)

    def test_plan_cannot_enable_actuators_or_bypass_calibration(self):
        self.assertFalse(prepare.validate(self.config, self.contract)['actuators_enabled'])
        for section in ('control', 'temperature_loop', 'parameter_control', 'pressure_calibration'):
            config = copy.deepcopy(self.config)
            config[section] = dict(enabled=True)
            with self.assertRaises(ValueError):
                prepare.validate(config, self.contract)
        contract = dict(self.contract, calibration_id=0)
        config = dict(self.config, contract=contract)
        with self.assertRaises(ValueError):
            prepare.validate(config, contract)
        self.assertIn('DIAGNOSTIC', prepare.validate(config, contract, True)['mode'])
        with self.assertRaises(ValueError):
            prepare.validate(dict(self.config, model=dict(backend='npu_v4')), self.contract)

    def test_plan_only_private_output_unique_tokens_and_capture_startup_arguments(self):
        config = self.root / 'config.json'
        contract = self.root / 'contract.json'
        config.write_text(json.dumps(self.config))
        contract.write_text(json.dumps(self.contract))
        output = self.root / 'plan'
        result = prepare.prepare(config, contract, output)
        self.assertEqual(result['status'], 'PLAN_ONLY_NOT_INSTALLED_NOT_RECORDING')
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        values = (output / 'web.env').read_text().splitlines()
        self.assertNotEqual(values[0].split('=')[1], values[1].split('=')[1])
        self.assertEqual((output / 'web.env').stat().st_mode & 0o777, 0o600)
        dropin = (output / 'recording.conf').read_text()
        self.assertIn('--capture-dir /var/lib/cabinet/captures', dropin)
        self.assertNotIn('--no-http', dropin)
        self.assertNotIn('restart', dropin)
        with self.assertRaises(ValueError):
            prepare.prepare(config, contract, output)

    def test_adapter_preflight_pin_is_current_abi3_not_legacy(self):
        tool = module('r40_preflight', ROOT / 'tools/target_preflight.py')
        self.assertEqual(tool.ADAPTER_SHA256, '7031253aed7950a02ec2b771e211a3eef9c4bc0cc8d60323cf51637cc557a0d7')
        self.assertIn('libedge_npu_logits_ps.so', (ROOT / 'linux/systemd/npu-v4.env.example').read_text())

    def test_http_auth_rpc_record_stop_and_download_against_real_local_owner(self):
        self.recorder.start()
        stop = threading.Event()
        def pump():
            while not stop.wait(0.06):
                self.sequence += 1
                now = time.monotonic()
                packet = fixtures.packet(self.sequence, now)
                header = list(packet['frame'].header)
                header[26] = 0x202610f7
                packet['frame'] = Frame(tuple(header), packet['frame'].values)
                self.recorder.submit(packet)
        feeder = threading.Thread(target=pump, daemon=True)
        feeder.start()
        listener = server('127.0.0.1', 0, self.service, token='READ', control_token='C' * 40)
        http = threading.Thread(target=listener.serve_forever, daemon=True)
        http.start()
        try:
            deadline = time.monotonic() + 2
            while not self.recorder.snapshot()['ready'] and time.monotonic() < deadline:
                time.sleep(0.02)
            base = 'http://127.0.0.1:' + str(listener.server_port)
            headers = {'Authorization': 'Bearer READ', 'X-Cabinet-Control-Token': 'C' * 40, 'Content-Type': 'application/json'}
            data = dict(request_id=str(uuid.uuid4()), payload=self.payload())
            for changes, expected in [({'Authorization': ''}, 401), ({'X-Cabinet-Control-Token': ''}, 403), ({'Origin': 'http://evil.test'}, 403)]:
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(base + '/api/capture/start', data=json.dumps(data).encode(), headers=dict(headers, **changes)), timeout=3)
                self.assertEqual(failure.exception.code, expected)
            with urlopen(Request(base + '/api/capture/start', data=json.dumps(data).encode(), headers=headers), timeout=3) as response:
                started = json.load(response)
            self.assertEqual(started['status']['state'], 'RECORDING')
            time.sleep(0.2)
            request = dict(request_id=str(uuid.uuid4()), payload=dict(session_id=started['status']['session_id']))
            with urlopen(Request(base + '/api/capture/stop', data=json.dumps(request).encode(), headers=headers), timeout=3) as response:
                ended = json.load(response)
            self.assertEqual(ended['status']['state'], 'COMPLETED')
            identity = ended['status']['session_id']
            with urlopen(Request(base + '/api/capture/download/' + identity, headers=headers), timeout=3) as response:
                with zipfile.ZipFile(io.BytesIO(response.read())) as archive_file:
                    self.assertIsNone(archive_file.testzip())
            self.assertTrue(verify.verify(self.recorder.directory / identity)['real_candidate'])
        finally:
            listener.shutdown()
            listener.server_close()
            http.join(2)
            stop.set()
            feeder.join(2)
            self.recorder.close()


if __name__ == '__main__':
    unittest.main()
