import importlib.util
from pathlib import Path
import struct
import unittest

from cabinet.protocol import Frame, FrameGate


def make_frame(mode=2, adc_count=12787, pressure_count=25, quality=0):
    header = [0] * 32
    header[:5] = [0x46524d31, 0x10000, 284, 1, 500]
    header[9:13] = [25575000, 25575000, 1024, 1024]
    header[13] = (pressure_count << 16) | adc_count if mode == 2 else adc_count
    header[14:23] = [20, quality, 2, 123, mode, 3, 4000, 100000000, 50000]
    header[26] = 0x202610b0
    values = [1.0] * 39
    values[37] = 0.1
    values[38] = 6000.0
    words = list(struct.unpack('<39I', struct.pack('<39f', *values)))
    return header, words


class PressureProfileTests(unittest.TestCase):
    def setUp(self):
        self.contract = dict(sample_mode_id=2, feature_config_id=2, calibration_id=123)

    def test_profile_two_counts_and_units(self):
        frame = Frame.from_words(*make_frame())
        self.assertEqual(frame.adc_count, 12787)
        self.assertEqual(frame.pressure_count, 25)
        self.assertEqual(frame.as_dict()['pressure_source'], 'SDP810-500Pa')
        self.assertAlmostEqual(frame.as_dict()['values']['pressure'], 0.1, places=6)
        self.assertEqual(FrameGate(self.contract).check(frame, 500), [])

    def test_no_pressure_samples_rejected_even_if_quality_missing(self):
        frame = Frame.from_words(*make_frame(pressure_count=0))
        self.assertIn('process_count', FrameGate(self.contract).check(frame, 500))

    def test_no_current_samples_rejected(self):
        frame = Frame.from_words(*make_frame(adc_count=0))
        self.assertIn('process_count', FrameGate(self.contract).check(frame, 500))

    def test_old_contract_rejects_new_sensor_profile(self):
        contract = dict(self.contract, sample_mode_id=1)
        self.assertIn('sample_mode', FrameGate(contract).check(Frame.from_words(*make_frame()), 500))

    def test_legacy_counts_still_identical(self):
        frame = Frame.from_words(*make_frame(mode=1))
        self.assertEqual(frame.adc_count, 12787)
        self.assertEqual(frame.pressure_count, 12787)
        self.assertEqual(FrameGate(dict(self.contract, sample_mode_id=1)).check(frame, 500), [])

    def test_pressure_fault_and_new_calibration_required(self):
        frame = Frame.from_words(*make_frame(quality=1 << 10))
        self.assertIn('quality', FrameGate(self.contract).check(frame, 500))
        self.assertIn('calibration', FrameGate(dict(self.contract, calibration_id=122)).check(frame, 500))

    def test_python36_hmi_reader_has_identical_semantics(self):
        path = Path(__file__).resolve().parents[1] / 'hmi_daily/cabinet/protocol.py'
        spec = importlib.util.spec_from_file_location('pressure_hmi_protocol', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        frame = module.Frame.from_words(*make_frame())
        self.assertEqual(frame.as_dict(), Frame.from_words(*make_frame()).as_dict())
        self.assertEqual(module.FrameGate(self.contract).check(frame, 500), [])
        invalid = module.Frame.from_words(*make_frame(pressure_count=0))
        self.assertIn('process_count', module.FrameGate(self.contract).check(invalid, 500))


if __name__ == '__main__':
    unittest.main()
