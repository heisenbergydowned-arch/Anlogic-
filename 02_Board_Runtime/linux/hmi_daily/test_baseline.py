import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid

from cabinet.baseline import BaselineStore, Learner, DEFAULTS, digest, validate_config
from cabinet.learning_rpc import LearningRPC, request
from cabinet.protocol import Frame, FEATURES
from daily import build_daily
from reader import view_state


def config():
    value = copy.deepcopy(DEFAULTS)
    value.update(device_id='test-device', installation_id='test-installation',
                 stable_seconds=0.1, capture_seconds=6, timeout_seconds=20,
                 min_samples=12, confirm_seconds=5)
    value['contract']['calibration_id'] = 7
    return value


def frame(identity, now, modify=None):
    header = [0] * 32
    header[:5] = [0x46524d31, 0x10000, 284, identity, int(now * 1000) & 0xffffffff]
    header[9:13] = [25575000, 25575000, 1024, 1024]
    header[13:23] = [12800, 50, 0, 1, 7, 1, 3, 4000, 100000000, 50000]
    header[24:28] = [500, 1, 0x202610a0, 0]
    values = ([0.05] * 3 + [0.2] * 3 + [3.0] * 3 + [0.125] * 8) * 2 + [1, 0.2, 30, 0.1, 6000]
    if modify:
        modify(header, values)
    return Frame(tuple(header), tuple(values))


def status(now):
    return dict(uptime_ms=int(now * 1000) & 0xffffffff, configured=True, configuration_id=3,
                alarm_level=0, active=[], latched=[], hard_inhibit=False, mode='RUN',
                fan_action='PI', reserved_meta_bits=0, measured_rpm=6000, ramped_rpm=6000,
                requested_rpm=6000, test_mode=False, event_sequence=0, lost_events=0,
                current_distance_raw_code=20, pressure_raw_code=8,
                temp_raw_1_16_C=480, input_validity=dict(rpm=True, adc=True, temperature=True, pressure=True))


WORDS = [1, 7, 1] + [0] * 14


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'baseline.sqlite'
        self.store = BaselineStore(self.path)
        self.learner = Learner(self.store, config())
        self.now = 1.0
        self.identity = 0

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def observe(self, modify=None, status_modify=None, session=123, model=None):
        self.now += 0.5
        self.identity += 1
        current = status(self.now)
        if status_modify:
            status_modify(current)
        incoming = frame(self.identity, self.now, modify)
        self.learner.observe(incoming, current, WORDS, session, self.now, model_result=model)
        return incoming

    def command(self, operation, **kwargs):
        return self.learner.command(dict(operation=operation, request_id=str(uuid.uuid4()), **kwargs), self.now)

    def start(self):
        self.observe()
        result = self.command('start', healthy_confirmed=True)
        self.assertTrue(result['ok'], result)

    def candidate(self):
        self.start()
        for _ in range(20):
            self.observe()
            if self.learner.state == 'PENDING_CONFIRM':
                return
        self.fail(self.learner.snapshot())

    def commit(self):
        self.candidate()
        result = self.command('commit', candidate_hash=digest(self.learner.candidate))
        self.assertTrue(result['ok'], result)
        return result['baseline_id']

    def test_empty_cannot_learn(self):
        self.learner.observe(None, status(1), WORDS, 123, 1)
        self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])

    def test_health_confirmation_is_required(self):
        self.observe()
        self.assertEqual(self.command('start')['reason'], 'HEALTHY_CONFIRMATION_REQUIRED')

    def test_no_qualification_bypass(self):
        for change in (lambda value: value.update(configured=False),
                       lambda value: value.update(test_mode=True),
                       lambda value: value.update(active=['OC_HARD'], alarm_level=3),
                       lambda value: value.update(measured_rpm=0),
                       lambda value: value.update(lost_events=1)):
            self.observe(status_modify=change)
            self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])

    def test_test_source_and_quality_rejected(self):
        for index, value in ((27, 1), (15, 0x1000), (17, 0), (11, 1023), (24, 2001), (19, 4)):
            self.observe(modify=lambda header, values: header.__setitem__(index, value))
            self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])

    def test_full_learn_validate_commit_and_reload(self):
        identity = self.commit()
        self.observe()
        self.assertEqual(self.learner.evidence['state'], 'CONSISTENT')
        self.assertEqual(self.learner.evidence['level'], 0)
        self.store.close()
        self.store = BaselineStore(self.path)
        self.learner = Learner(self.store, config())
        self.observe()
        self.assertEqual(self.learner.evidence['baseline_id'], identity)
        self.assertEqual(self.learner.evidence['state'], 'CONSISTENT')

    def test_wrong_hash_never_activates(self):
        self.candidate()
        self.assertEqual(self.command('commit', candidate_hash='wrong')['reason'], 'CANDIDATE_HASH_MISMATCH')
        self.assertEqual(self.store.profiles(), [])

    def test_existing_profile_remains_until_confirmation(self):
        previous = self.commit()
        self.candidate()
        self.assertEqual(self.store.profiles()[0]['id'], previous)
        self.assertTrue(self.command('cancel', job_id=self.learner.job_id)['ok'])
        self.assertEqual(self.store.profiles()[0]['id'], previous)

    def test_fault_during_capture_aborts_without_changing_status(self):
        self.start()
        current = status(self.now + 0.1)
        current.update(active=['OC_HARD'], alarm_level=3, hard_inhibit=True, fan_action='INHIBIT')
        original = copy.deepcopy(current)
        self.learner.observe(None, current, WORDS, 123, self.now + 0.1)
        self.assertEqual(self.learner.state, 'ABORTED')
        self.assertEqual(current, original)
        self.assertEqual(self.store.profiles(), [])

    def test_short_protection_event_without_active_alarm_still_aborts(self):
        self.start()
        self.observe(status_modify=lambda current: current.update(event_sequence=2))
        self.assertEqual(self.learner.state, 'ABORTED')

    def test_contract_and_session_change_aborts(self):
        self.start()
        self.observe(session=456)
        self.assertEqual(self.learner.state, 'ABORTED')
        self.observe(session=456)
        self.assertTrue(self.command('start', healthy_confirmed=True)['ok'])
        self.observe(status_modify=lambda current: current.update(configuration_id=4), session=456)
        self.assertEqual(self.learner.state, 'ABORTED')

    def test_gap_blocks_pending_commit(self):
        self.candidate()
        checksum = digest(self.learner.candidate)
        self.now += 2
        self.learner.observe(None, status(self.now), WORDS, 123, self.now)
        self.assertEqual(self.learner.state, 'ABORTED')
        self.assertFalse(self.command('commit', candidate_hash=checksum)['ok'])

    def test_empty_poll_between_valid_frames_does_not_block_commit(self):
        self.candidate()
        checksum = digest(self.learner.candidate)
        self.now += 0.1
        self.learner.observe(None, status(self.now), WORDS, 123, self.now)
        self.assertTrue(self.command('commit', candidate_hash=checksum)['ok'])

    def test_model_conflict_aborts(self):
        self.start()
        self.observe(model=dict(formal=True, label='imbalance'))
        self.assertEqual(self.learner.state, 'ABORTED')

    def test_out_of_coverage_is_not_normal(self):
        self.commit()
        self.observe(modify=lambda header, values: values.__setitem__(38, 3000),
                     status_modify=lambda current: current.update(measured_rpm=3000, ramped_rpm=3000))
        self.assertEqual(self.learner.evidence['state'], 'OUT_OF_COVERAGE')

    def test_gradual_deviation_is_not_absorbed(self):
        self.commit()
        reference = copy.deepcopy(self.learner.profiles[0])
        for _ in range(12):
            self.observe(modify=lambda header, values: values.__setitem__(0, 0.1))
        self.assertEqual(self.learner.evidence['state'], 'DEVIATION')
        self.assertEqual(self.learner.evidence['level'], 0)
        self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])
        self.assertEqual(self.learner.profiles[0], reference)

    def test_duplicate_request_is_persistent_and_idempotent(self):
        self.observe()
        payload = dict(operation='start', request_id='persistent', healthy_confirmed=True)
        first = self.learner.command(payload, self.now)
        self.assertEqual(self.learner.command(payload, self.now), first)
        self.store.close()
        self.store = BaselineStore(self.path)
        self.learner = Learner(self.store, config())
        self.assertEqual(self.learner.command(payload, self.now), first)
        self.assertEqual(self.learner.state, 'IDLE')
        changed = dict(payload, healthy_confirmed=False)
        self.assertEqual(self.learner.command(changed, self.now)['reason'], 'REQUEST_ID_REUSED')

    def test_crash_does_not_activate_candidate(self):
        self.candidate()
        self.store.close()
        self.store = BaselineStore(self.path)
        self.assertEqual(self.store.profiles(), [])
        self.assertEqual(self.store.profiles('CANDIDATE'), [])

    def test_corrupt_baseline_does_not_load(self):
        self.commit()
        with self.store.connection:
            self.store.connection.execute("UPDATE profiles SET checksum='bad'")
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.store.profiles()

    def test_malformed_statistics_are_rejected_even_with_matching_checksum(self):
        self.commit()
        body = copy.deepcopy(self.learner.profiles[0])
        body['scale'][0] = 0
        with self.store.connection:
            self.store.connection.execute('UPDATE profiles SET body=?,checksum=?', (json.dumps(body), digest(body)))
        with self.assertRaisesRegex(ValueError, 'scale'):
            self.store.profiles()

    def test_confirmation_timeout_keeps_previous_baseline(self):
        previous = self.commit()
        self.candidate()
        for _ in range(12):
            self.observe()
        self.assertEqual(self.learner.state, 'TIMEOUT')
        self.assertEqual(self.store.profiles()[0]['id'], previous)

    def test_incompatible_profile_cannot_be_rolled_back(self):
        first = self.commit()
        self.commit()
        self.observe(status_modify=lambda current: current.update(configuration_id=4))
        self.assertFalse(self.command('rollback', baseline_id=first)['ok'])

    def test_compatible_profile_can_be_rolled_back(self):
        first = self.commit()
        self.commit()
        self.observe()
        self.assertTrue(self.command('rollback', baseline_id=first)['ok'])
        self.assertEqual(self.learner.profiles[0]['id'], first)

    def test_nonoverlapping_selection_does_not_count_128ms_hops_as_independent(self):
        self.start()
        for _ in range(12):
            self.now += 0.128
            self.identity += 1
            self.learner.observe(frame(self.identity, self.now), status(self.now), WORDS, 123, self.now)
        self.assertLess(len(self.learner.rows), 5)
        self.assertEqual(self.learner.state, 'CAPTURING')

    def test_invalid_noise_floors_and_widened_gate_are_rejected(self):
        value = config()
        value['noise_floors'][0] = 0
        with self.assertRaises(ValueError):
            validate_config(value)
        value = config()
        value['noise_floors'][0] = 1e-320
        with self.assertRaises(ValueError):
            validate_config(value)
        value = config()
        value['contract']['max_frame_age_ms'] = 5000
        with self.assertRaises(ValueError):
            validate_config(value)

    def test_temperature_drift_rejects_candidate(self):
        self.start()
        for index in range(20):
            self.observe(modify=lambda header, values: values.__setitem__(36, 30 + index * 0.4))
            if self.learner.state not in ('WAIT_STABLE', 'CAPTURING'):
                break
        self.assertEqual(self.learner.state, 'REJECTED')
        self.assertEqual(self.store.profiles(), [])

    def test_zero_band_power_cannot_be_learned(self):
        self.observe(modify=lambda header, values: values.__setitem__(slice(9, 17), [0] * 8))
        self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])

    def test_nan_does_not_remain_qualified(self):
        self.observe()
        self.observe(modify=lambda header, values: values.__setitem__(0, float('nan')))
        self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])
        self.now += 0.1
        self.learner.observe(None, status(self.now), WORDS, 123, self.now)
        self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])

    def test_invalid_frame_then_empty_cannot_requalify_old_data(self):
        self.observe()
        self.observe(modify=lambda header, values: header.__setitem__(15, 4))
        self.now += 0.1
        self.learner.observe(None, status(self.now), WORDS, 123, self.now)
        self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])

    def test_empty_poll_cannot_clear_existing_deviation(self):
        self.commit()
        for _ in range(12):
            self.observe(modify=lambda header, values: values.__setitem__(0, 0.1))
        self.now += 0.1
        self.learner.observe(None, status(self.now), WORDS, 123, self.now)
        self.assertFalse(self.command('start', healthy_confirmed=True)['ok'])

    def test_local_rpc_is_collector_owned_and_no_mmio(self):
        rpc = LearningRPC(Path(self.directory.name) / 'runtime/learning.sock')
        results = []
        caller = threading.Thread(target=lambda: results.append(request(rpc.path, {'operation': 'status'})))
        try:
            caller.start()
            for _ in range(30):
                rpc.poll(self.learner, self.now)
                if not caller.is_alive():
                    break
                time.sleep(0.02)
            caller.join(timeout=2)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]['ok'])
            self.assertEqual(results[0]['state'], 'IDLE')
        finally:
            rpc.close()


class DailyTests(unittest.TestCase):
    def sample(self, calibration=7, quality=0):
        incoming = frame(1, 1)
        record = incoming.as_dict()
        record.update(state='RECEIVED_REAL', calibration_id=calibration, quality=quality)
        return dict(status=status(1), frame=record, mailbox_before_read=dict(queued_frames=0, dropped_frames=0),
                    feature_words=[1, calibration, 1] + [0] * 14)

    def daily(self, sample):
        view, _, _ = view_state(sample, None, None, 1, 1)
        return build_daily(view, sample, dict(state='IDLE', reason='NO_FRAME', can_start=False,
                                             evidence=dict(state='UNLEARNED', score=None)))

    def test_calibrated_process_units_and_percentage_are_true_conversions(self):
        daily = self.daily(self.sample())
        self.assertEqual(daily['daily_current_unit'], 'A')
        self.assertEqual(daily['daily_current_value'], '0.200')
        self.assertEqual(daily['daily_pressure_unit'], 'kPa')
        self.assertEqual(daily['daily_banda0'], '12.5')

    def test_uncalibrated_window_never_becomes_engineering_units(self):
        daily = self.daily(self.sample(calibration=0, quality=0x1000))
        self.assertEqual(daily['daily_current_unit'], '原始码')
        self.assertEqual(daily['daily_rms_a_x'], '--')

    def test_invalid_missing_values_never_become_zero(self):
        sample = self.sample()
        sample['frame'] = dict(state='EMPTY')
        sample['status']['input_validity'] = {}
        daily = self.daily(sample)
        for name in ('rpm', 'current', 'pressure'):
            self.assertEqual(daily['daily_' + name + '_value'], '--')
        self.assertEqual(daily['core_temperature_c'], '--')
        self.assertEqual(daily['core_temperature_valid'], '0')
        self.assertEqual(daily['ui_learn_can_start'], '0')

    def test_lost_adc_does_not_display_cached_calibrated_current(self):
        sample = self.sample()
        sample['status']['input_validity']['adc'] = False
        daily = self.daily(sample)
        self.assertEqual(daily['daily_current_valid'], '0')
        self.assertEqual(daily['daily_current_value'], '--')

    def test_adc_without_other_sensors_shows_signed_sample_not_current_magnitude(self):
        for raw, expected in ((0, '0'), (0x7fff, '32767'), (0x8000, '-32768'), (0xffff, '-1')):
            with self.subTest(raw=raw):
                sample = self.sample()
                sample['frame'] = dict(state='EMPTY')
                sample['status']['input_validity'] = dict(adc=True, rpm=False, temperature=False, pressure=False)
                sample['status']['raw_words'] = [0] * 32
                sample['status']['raw_words'][22] = 0x12340000 | raw
                sample['status']['current_distance_raw_code'] = 42
                daily = self.daily(sample)
                self.assertEqual(daily['daily_current_value'], expected)
                self.assertEqual(daily['daily_current_unit'], '原始码')
                self.assertEqual(daily['daily_current_kind'], 'raw_sample')
                self.assertEqual(daily['daily_current_valid'], '1')
                for name in ('rpm', 'pressure'):
                    self.assertEqual(daily['daily_' + name + '_value'], '--')
                self.assertEqual(daily['core_temperature_c'], '--')
                self.assertEqual(daily['ui_learn_can_start'], '0')

    def test_stale_adc_does_not_show_retained_raw_sample(self):
        sample = self.sample()
        sample['frame'] = dict(state='EMPTY')
        sample['status']['raw_words'] = [0] * 32
        sample['status']['raw_words'][22] = 1234
        sample['status']['input_validity']['adc'] = False
        daily = self.daily(sample)
        self.assertEqual(daily['daily_current_value'], '--')
        self.assertEqual(daily['daily_current_valid'], '0')

    def test_calibrated_frame_overrides_raw_sample_only_when_qualified(self):
        sample = self.sample()
        sample['status']['raw_words'] = [0] * 32
        sample['status']['raw_words'][22] = 0x8000
        daily = self.daily(sample)
        self.assertEqual(daily['daily_current_value'], '0.200')
        self.assertEqual(daily['daily_current_unit'], 'A')
        self.assertEqual(daily['daily_current_kind'], 'calibrated')

    def test_malformed_raw_word_does_not_become_signed_measurement(self):
        for raw in (True, -1, 0x100000000, '123'):
            with self.subTest(raw=raw):
                sample = self.sample(calibration=0)
                sample['status']['raw_words'] = [0] * 32
                sample['status']['raw_words'][22] = raw
                self.assertEqual(self.daily(sample)['daily_current_kind'], 'raw_distance')

    def test_changed_active_contract_hides_old_vibration_units(self):
        sample = self.sample()
        sample['feature_words'][1] = 8
        daily = self.daily(sample)
        self.assertEqual(daily['daily_rms_a_x'], '--')
        self.assertEqual(daily['daily_current_unit'], '原始码')

    def test_thermal_alarm_has_no_removed_power_action(self):
        sample = self.sample()
        sample['status'].update(active=['TEMP_HARD'], alarm_level=3)
        daily = self.daily(sample)
        self.assertNotIn('负载', daily['daily_notice'])
        self.assertNotIn('断电', daily['daily_notice'])
        self.assertNotIn('ui_load_request', daily)

    def test_unknown_quality_bits_hide_vibration_values(self):
        daily = self.daily(self.sample(quality=0x8000))
        self.assertEqual(daily['daily_rms_a_x'], '--')
        self.assertEqual(daily['daily_banda0'], '--')


if __name__ == '__main__':
    unittest.main()
