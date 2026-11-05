import copy
import json
from pathlib import Path
import tempfile
import unittest

from cabinet.baseline import BaselineStore, Learner
from daily import build_daily
from reader import view_state
from test_baseline import config, frame, status


EDGES = [1, 13, 39, 65, 103, 154, 205, 257, 513]


def fixture():
    record = frame(123, 10).as_dict()
    record.update(state='RECEIVED_REAL', header=list(frame(123, 10).header))
    record['header'][18] = record['sample_mode_id'] = 2
    observation = dict(frame=record, status=status(10), feature_words=[1, 7, 1] + [0] * 5 + EDGES,
                       mailbox_before_read=dict(queued_frames=0, dropped_frames=0))
    view, _, _ = view_state(observation, None, None, 10, 1)
    baseline = dict(state='IDLE', reason='READY', evidence=dict(state='UNLEARNED', score=None))
    return view, observation, baseline


class InstrumentTests(unittest.TestCase):
    def test_admitted_fault_window_shows_unknown_fg(self):
        view,sample,baseline=fixture();view['quality']='0x00000800'
        sample['model']=dict(feature_config_id=1,calibration_id=7,test=False,probabilities=[.01,.01,.96,.01,.01],
            input_policy='FAULT_WINDOWS_FG_UNKNOWN_V1',rpm_measurement_available=False,protection_window=True,
            backend='Alnpu',label='stall',diagnostic_state='FORMAL_OBSERVATION')
        sample['model_formal']=True
        result=build_daily(view,sample,baseline)
        self.assertEqual(result['panel_model_valid'],'1')
        self.assertEqual(result['panel_model_note'],'FG UNKNOWN / FAULT CANDIDATE')
        sample['model_formal']=False
        self.assertEqual(build_daily(view,sample,baseline)['panel_model_valid'],'0')
        sample['model_formal']=True;view['quality']='0x00000900'
        self.assertEqual(build_daily(view,sample,baseline)['panel_model_valid'],'0')

    def test_pwm_normalized_scale_preserves_manual_and_pi_percentages(self):
        for counts, percentage in ((0, '0%'), (400, '10%'), (1000, '25%'),
                                   (2000, '50%'), (3000, '75%'), (4000, '100%')):
            with self.subTest(counts=counts):
                view, sample, baseline = fixture()
                sample['status']['applied_pwm_counts'] = counts
                self.assertEqual(build_daily(view, sample, baseline)['panel_pwm'], percentage)

    def test_pwm_invalid_counts_or_offline_status_do_not_claim_a_duty(self):
        for counts in (-1, 4001, 5000, 65535, True, None, float('nan'), 2000.5, 2000.0):
            with self.subTest(counts=counts):
                view, sample, baseline = fixture()
                sample['status']['applied_pwm_counts'] = counts
                self.assertEqual(build_daily(view, sample, baseline)['panel_pwm'], '--')
        view, sample, baseline = fixture()
        sample['status']['applied_pwm_counts'] = 2000
        view['frame_fresh'] = '0'
        self.assertEqual(build_daily(view, sample, baseline)['panel_pwm'], '50%')
        view['link'] = 'ERROR'
        self.assertEqual(build_daily(view, sample, baseline)['panel_pwm'], '--')

    def test_single_core_hmi_contract_has_no_legacy_temperature_alias_or_bmp_die_temperature(self):
        view, sample, baseline = fixture()
        sample['status']['temp_raw_1_16_C'] = 1040
        view['ui_temp_value'] = '25.0'
        daily = build_daily(view, sample, baseline)
        self.assertEqual(daily['panel_schema'], 'industrial-v2')
        self.assertEqual(daily['core_temperature_c'], '65.0')
        self.assertEqual(daily['core_temperature_valid'], '1')
        self.assertEqual(daily['core_temperature_source'], 'DS18B20/S4b')
        for field in ('daily_temp_value', 'daily_temp_valid', 'daily_temp_unit', 'bmp_temperature_c'):
            self.assertNotIn(field, daily)

    def test_missing_or_malformed_core_status_cannot_use_generic_display_or_environment_fallback(self):
        for raw in (None, True, '1040', 2001, -881):
            with self.subTest(raw=raw):
                view, sample, baseline = fixture()
                view.update(ui_temp_value='25.0', ui_temp_valid='1')
                sample['status']['temp_raw_1_16_C'] = raw
                daily = build_daily(view, sample, baseline)
                self.assertEqual(daily['core_temperature_c'], '--')
                self.assertEqual(daily['core_temperature_valid'], '0')

    def test_learning_display_does_not_claim_ready_when_web_clock_gate_is_closed(self):
        view, sample, baseline = fixture()
        baseline.update(can_start=True, reason='READY')
        sample['learning_web'] = dict(can_start=False, clock_trusted=False)
        result = build_daily(view, sample, baseline)
        self.assertEqual(result['ui_learn_can_start'], '0')
        self.assertIn('时间', result['ui_learn_note'])

    def test_rejected_normal_probabilities_are_not_rendered_as_healthy(self):
        view, sample, baseline = fixture()
        sample['model'] = dict(feature_config_id=1, calibration_id=7, test=False,
            probabilities=[0.6, 0.1, 0.1, 0.1, 0.1], diagnostic_state='REJECTED_CONFIDENCE', label='normal')
        sample['model_formal'] = True
        result = build_daily(view, sample, baseline)
        self.assertEqual(result['panel_model_valid'], '0')
        self.assertEqual(result['panel_prob_normal'], '--')

    def test_all_35_vibration_values_are_present(self):
        view, sample, baseline = fixture()
        daily = build_daily(view, sample, baseline)
        for point in ('a', 'b'):
            for kind in ('rms', 'pp', 'kurt'):
                for axis in 'xyz':
                    self.assertNotEqual(daily['daily_%s_%s_%s' % (kind, point, axis)], '--')
            for band in range(8):
                self.assertNotEqual(daily['daily_band%s%d' % (point, band)], '--')
        self.assertNotEqual(daily['daily_ratio_ab'], '--')

    def test_actual_edges_and_rate_define_frequency_labels(self):
        view, sample, baseline = fixture()
        view['frame_rate_a'] = view['frame_rate_b'] = '4000'
        daily = build_daily(view, sample, baseline)
        self.assertEqual(daily['panel_band1_hz'], '51-148')
        sample['feature_words'][9] = 14
        changed = build_daily(view, sample, baseline)
        self.assertEqual(changed['panel_band1_hz'], '55-148')

    def test_missing_or_invalid_edges_do_not_claim_nominal_bands(self):
        for edges in ([], [1, 7, 1] + [0] * 14):
            view, sample, baseline = fixture()
            sample['feature_words'] = edges
            self.assertEqual(build_daily(view, sample, baseline)['panel_band1_hz'], '--')

    def test_no_model_does_not_become_zero_probabilities(self):
        view, sample, baseline = fixture()
        daily = build_daily(view, sample, baseline)
        self.assertEqual(daily['panel_model_state'], 'MODEL_UNAVAILABLE')
        self.assertEqual(daily['panel_prob_normal'], '--')

    def test_model_class_order_and_backend_are_not_relabelled(self):
        view, sample, baseline = fixture()
        sample['model'] = dict(test=False, backend='CPU_ONNX', frame_id=123, feature_config_id=1,
                               calibration_id=7, probabilities=[0.1, 0.2, 0.3, 0.15, 0.25])
        daily = build_daily(view, sample, baseline)
        self.assertEqual(daily['panel_prob_stall'], '30.00')
        self.assertEqual(daily['panel_prob_clog'], '15.00')
        self.assertIn('CPU_ONNX', daily['panel_model_state'])
        self.assertIn('观察', daily['panel_model_state'])

    def test_invalid_model_and_test_source_are_hidden(self):
        for probabilities in ([True, 0, 0, 0, 0], [float('nan')] * 5, [1] * 5):
            view, sample, baseline = fixture()
            sample['model'] = dict(test=False, backend='ALNPU', feature_config_id=1, calibration_id=7,
                                   probabilities=probabilities)
            self.assertEqual(build_daily(view, sample, baseline)['panel_model_valid'], '0')
        view, sample, baseline = fixture()
        view['frame_state'] = 'REJECTED_TEST'
        sample['model'] = dict(test=True, backend='MOCK', feature_config_id=1, calibration_id=7,
                               probabilities=[1, 0, 0, 0, 0])
        self.assertEqual(build_daily(view, sample, baseline)['panel_model_valid'], '0')

    def test_fault_latch_and_unknown_input_are_not_green(self):
        view, sample, baseline = fixture()
        sample['status']['latched'] = ['OC_HARD']
        sample['status']['input_validity']['temperature'] = False
        daily = build_daily(view, sample, baseline)
        self.assertEqual(daily['panel_pl_oc'], 'LATCH')
        self.assertEqual(daily['panel_pl_ot'], 'UNKNOWN')
        self.assertIn('不控制电源', daily['panel_drive_note'])
        self.assertNotIn('panel_power', daily)

    def test_unconfigured_protection_cannot_claim_clear(self):
        view, sample, baseline = fixture()
        sample['status']['configured'] = False
        daily = build_daily(view, sample, baseline)
        self.assertEqual(daily['panel_pl_oc'], 'UNREADY')

    def test_group_scores_preserve_original_maximum_decision(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = BaselineStore(Path(temporary) / 'baseline.sqlite3')
            try:
                learner = Learner(store, config())
                reference = frame(1, 10)
                learner.profiles = [dict(signature='contract', id='baseline', center=list(reference.values),
                                         scale=[1] * 39, rpm_min=5000, rpm_max=7000)]
                values = list(reference.values)
                values[2] += 1
                values[9] += 2
                values[34] += 3
                values[36] += 4
                candidate = type(reference)(reference.header, tuple(values))
                result = learner.compare(candidate, 'contract', 10)
                self.assertEqual(result['score'], 4)
                self.assertEqual(result['group_scores'], dict(amplitude=1, spectrum=2, ratio=3, process=4))
                self.assertEqual(max(result['group_scores'].values()), result['score'])
            finally:
                store.close()

    def test_layout_preserves_readonly_default_and_requires_explicit_operator_input(self):
        source = Path(__file__).with_name('dashboard.c').read_text(encoding='utf-8')
        for text in ('learning_request', 'select_page', 'learning.sock', 'socket(', '/dev/mem'):
            self.assertNotIn(text, source)
        panel = Path(__file__).with_name('parameter_view.h').read_text(encoding='utf-8')
        self.assertIn('getenv("CABINET_OPERATOR_SOCKET")', panel)
        for text in ('if(operator_socket)', 'getenv("CABINET_OPERATOR_POINTER")', 'getenv("CABINET_OPERATOR_KEYBOARD")',
                     'S_ISCHR(info.st_mode)', 'lv_indev_set_group', 'operator_shutdown()'):
            self.assertIn(text, source)
        for field in ('model_state', 'pl_lights', 'matrix[6][3]', 'band_series[2]'):
            self.assertIn(field, source)

    def test_dashboard_font_covers_the_current_vocabulary(self):
        root = Path(__file__).resolve().parent
        glyphs = set(json.loads((root / 'fonts/manifest.json').read_text())['glyphs'])
        for name in ('dashboard.c', 'capture_view.h', 'instrument.py', 'daily.py', 'presentation.py'):
            missing = {character for character in (root / name).read_text() if ord(character) >= 128} - glyphs
            self.assertFalse(missing, name + ': ' + ''.join(sorted(missing)))


if __name__ == '__main__':
    unittest.main()
