import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cabinet.service import Service
from fcb1_client import decode_status
from hmi_daily.cabinet.baseline import BaselineStore, DEFAULTS, Learner
from test_local_display import CONFIG, healthy_status
from run_edge import load_config


class NoPowerCutTests(unittest.TestCase):
    def test_decoded_reserved_fields_are_not_power_commands(self):
        for bits in range(4):
            words = [0] * 32
            words[2] = bits << 9
            status = decode_status(words)
            self.assertEqual(status['reserved_meta_bits'], bits)
            self.assertNotIn('load_request', status)

    def test_removed_executor_module_is_not_importable(self):
        self.assertIsNone(importlib.util.find_spec('cabinet.load'))

    def test_examples_do_not_offer_power_execution(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('config.example.json', 'config.v4.example.json'):
            self.assertNotIn('load_executor', load_config(root / name))

    def test_legacy_enabled_executor_is_rejected_even_for_live_mode(self):
        for mock, diagnostic in ((False, False), (False, True), (True, False)):
            config = copy.deepcopy(CONFIG)
            config['diagnostic_test'] = diagnostic
            config['load_executor'] = dict(enabled=True, command=['/bin/false'])
            with self.assertRaisesRegex(ValueError, 'removed'):
                Service(config, mock=mock)

    def test_only_data_and_pwm_workers_can_start(self):
        with tempfile.TemporaryDirectory() as directory:
            config = copy.deepcopy(CONFIG)
            config['database'] = str(Path(directory) / 'events.sqlite')
            service = Service(config, mock=True)
            with patch('cabinet.service.threading.Thread') as thread:
                service.start()
                names = [keywords['name'] for arguments, keywords in thread.call_args_list]
                self.assertEqual(names, ['cabinet-hardware', 'cabinet-model', 'cabinet-journal', 'cabinet-uplink'])
            service.threads = []
            self.assertNotIn('load', service.public_state())
            service.close()

    def test_learning_still_requires_no_alarm_and_zero_reserved_bits(self):
        with tempfile.TemporaryDirectory() as directory:
            config = copy.deepcopy(DEFAULTS)
            config['installation_id'] = 'UNIT_TEST_NOT_BOARD'
            config['device_id'] = 'UNIT_DEVICE'
            config['contract']['calibration_id'] = 7
            store = BaselineStore(Path(directory) / 'learning.sqlite')
            self.addCleanup(store.close)
            learner = Learner(store, config)
            status = healthy_status(1)
            self.assertIsNone(learner.guard(status))
            for fault in ('OC_HARD', 'TEMP_HARD', 'STALL_CORROBORATED', 'VIB_HARD'):
                self.assertEqual(learner.guard(dict(status, active=[fault], alarm_level=3)), 'ACTIVE_ALARM')
            self.assertEqual(learner.guard(dict(status, reserved_meta_bits=2)), 'CONTROL_CONFLICT')
            self.assertEqual(learner.guard(dict(status, hard_inhibit=True)), 'NOT_STABLE_RUN')


if __name__ == '__main__':
    unittest.main()
