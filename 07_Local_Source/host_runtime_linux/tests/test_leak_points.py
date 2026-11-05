"""R46 regressions: physical samples and qualification cannot be fabricated."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from types import SimpleNamespace

from cabinet.protocol import Frame, FrameGate
from cabinet.mock import MockController
from cabinet.service import Service
from v4_runtime.frames import FrameValidator, binding
from v4_runtime.client import V4Model
from v4_runtime.backend_audit import verify_alnpu_graph

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / 'linux/config.example.json').read_text())
CONTRACT = dict(feature_config_id=0x2026f400, calibration_id=7, sample_mode_id=2,
                max_frame_age_ms=1000, max_temp_age_ms=2000, fs=4000, adc_fs=50000)


def frame(qualified=False):
    h = [0] * 32
    h[:5] = [0x46524d31, 0x10000, 284, 5232, 1000]
    h[9:15] = [25575000, 25441127, 1024, 1024, (25 << 16) | 12813, 128]
    h[16:23] = [CONTRACT['feature_config_id'], 7, 2, 3, 4000, 100000000, 50000]
    h[24:28] = [130, 0, 0x202610f7, 0]
    if not qualified:
        h[13:20] = [12813, 0, 0x3c00, 1, 0, 2, 1]
        h[25] = 2744767
    return Frame(tuple(h), tuple([0.05] * 34 + [1.0, 0.0, 25.0, 0.0, 0.0]))


def request(f):
    return dict(schema='cabinet-npu-request-v4', request_id='r1', session_id='s1', boot_id='b1',
                generation=1, model_id='m1', bundle_manifest_sha256='a'*64, now_ms=1000,
                sent_monotonic=time.monotonic(), header=list(f.header),
                feature_words=list(struct.unpack('<39I', struct.pack('<39f', *f.values))))


class PhysicalFrameTests(unittest.TestCase):
    def test_missing_unqualified_board_data_is_rejected_without_mutation(self):
        f = frame(); original = (f.header, f.values)
        reasons = FrameGate(CONTRACT).check(f, 1000)
        for reason in ('alignment', 'calibration', 'feature_config', 'quality', 'process_count', 'not_stable_run'):
            self.assertIn(reason, reasons)
        self.assertEqual((f.header, f.values), original)
        self.assertEqual([f.values[i] for i in (35, 37, 38)], [0.0, 0.0, 0.0])

    def test_ready_off_and_every_non_run_mode_stays_rejected(self):
        for mode in range(16):
            f = frame(True); h = list(f.header); h[19] = mode
            reasons = FrameGate(CONTRACT).check(Frame(tuple(h), f.values), 1000)
            self.assertEqual('not_stable_run' in reasons, mode != 3)

    def test_each_missing_process_quality_bit_is_rejected(self):
        for bit in range(8, 14):
            f = frame(True); h = list(f.header); h[15] = 1 << bit
            self.assertIn('quality', FrameGate(CONTRACT).check(Frame(tuple(h), f.values), 1000))

    def test_collector_and_recorder_keep_original_rejected_frame(self):
        observed = []
        class Recorder:
            def submit(self, value):
                observed.append(value)
                service.stop.set()
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as directory:
            config = copy.deepcopy(CONFIG)
            config['database'] = str(Path(directory) / 'state.db')
            config['contract'].update(CONTRACT)
            raw = frame()
            service = Service(config, controller=MockController([raw]), recorder=Recorder())
            try:
                service.io_loop()
                self.assertEqual(len(observed), 1, service.state)
                self.assertEqual(observed[0]['frame'], raw)
                self.assertIn('alignment', observed[0]['rejected'])
                self.assertEqual(service.state['frame']['calibration_id'], 0)
                self.assertEqual(service.state['frame']['feature_config_id'], 1)
                self.assertFalse(service.valid_input)
                self.assertIsNone(service.state['model'])
                self.assertEqual(service.controller.commands, [])
            finally:
                service.close()

    def test_client_request_preserves_raw_header_and_features(self):
        model = V4Model.__new__(V4Model)
        model.bundle = SimpleNamespace(vector=lambda values: values, manifest_sha256='a'*64)
        model.config = {'model_id': 'm1'}
        f = frame()
        r = model.request(f, dict(received_at=time.monotonic(), session_id='s', boot_id='b', generation=1, now_ms=1000))
        self.assertEqual(r['header'], list(f.header))
        self.assertEqual(struct.unpack('<39f', struct.pack('<39I', *r['feature_words']))[-4:], (0.0, 25.0, 0.0, 0.0))

    def test_runtime_rejects_uncalibrated_request_and_does_not_rewrite_binding(self):
        bundle = SimpleNamespace(contract=CONTRACT, synthetic=False, manifest_sha256='a'*64,
            manifest=dict(model_id='m1', compatible_pl_build_ids=[0x202610f7]))
        r = request(frame()); original = copy.deepcopy(r); before = binding(r)
        with self.assertRaises(ValueError):
            FrameValidator(bundle).check(r)
        self.assertEqual(r, original)
        self.assertEqual(binding(r), before)

    def test_qualified_control_example_is_accepted_and_binding_preserved(self):
        bundle = SimpleNamespace(contract=CONTRACT, synthetic=False, manifest_sha256='a'*64,
            manifest=dict(model_id='m1', compatible_pl_build_ids=[0x202610f7]))
        r = request(frame(True)); original = copy.deepcopy(r)
        result, identity = FrameValidator(bundle).check(r)
        self.assertEqual(r, original)
        self.assertEqual(identity, binding(original))
        self.assertEqual(result.header, tuple(original['header']))

    def test_real_model_rejects_test_replay(self):
        bundle = SimpleNamespace(contract=CONTRACT, synthetic=False, manifest_sha256='a'*64,
            manifest=dict(model_id='m1', compatible_pl_build_ids=[0x202610f7]))
        f = frame(True); h = list(f.header); h[27] = 1
        with self.assertRaisesRegex(ValueError, 'TEST'):
            FrameValidator(bundle).check(request(Frame(tuple(h), f.values)))


class BackendAuditTests(unittest.TestCase):
    def test_old_mislabelled_adapter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'rebuild'):
            verify_alnpu_graph({'requested_backends': ['Alnpu']}, 'digraph G { n[label="backend: CpuAcc"]; }')

    def test_cpu_gpu_unknown_and_absent_graph_assignments_fail_closed(self):
        info = dict(requested_backends=['Alnpu'], backend_audit_schema='cabinet-alnpu-graph-v1')
        for backend in ('CpuAcc', 'CpuRef', 'GpuAcc', 'Unknown'):
            with self.assertRaises(ValueError):
                verify_alnpu_graph(info, 'digraph G { n[label="backend: %s"]; }' % backend)
        with self.assertRaises(ValueError):
            verify_alnpu_graph(info, 'digraph G { label="requested Alnpu"; }')

    def test_explicit_alnpu_graph_assignment_is_required_and_pinned(self):
        info = dict(requested_backends=['Alnpu'], backend_audit_schema='cabinet-alnpu-graph-v1')
        result = verify_alnpu_graph(info, 'digraph G { n[label="FullyConnected\\nbackend: Alnpu"]; }')
        self.assertTrue(result['backend_assignment_verified'])
        self.assertFalse(result['hardware_qualified'])
        self.assertEqual(len(result['graph_sha256']), 64)


class ModbusResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('poll_r46', ROOT / 'tools/rs485_master_poll.py')
        cls.poll = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.poll)

    def packet(self, slave=1, function=3, count=32):
        payload = bytes([slave, function, count]) + struct.pack('>16H', *range(16))
        return payload + struct.pack('<H', self.poll.modbus_crc16(payload))

    def test_correct_frame_is_accepted(self):
        self.assertEqual(self.poll.validate_response(self.packet(), 1), tuple(range(16)))

    def test_crc_valid_wrong_device_function_and_byte_count_are_rejected(self):
        for values in [(2, 3, 32), (1, 4, 32), (1, 3, 30)]:
            response = self.packet(*values)
            self.assertEqual(self.poll.modbus_crc16(response), 0)
            with self.assertRaises(ValueError): self.poll.validate_response(response, 1)

    def test_truncated_or_crc_corrupted_response_is_rejected(self):
        good = self.packet()
        for invalid in (good[:-1], bytes([good[0] ^ 1]) + good[1:]):
            with self.assertRaises(ValueError): self.poll.validate_response(invalid, 1)


if __name__ == '__main__':
    unittest.main()
