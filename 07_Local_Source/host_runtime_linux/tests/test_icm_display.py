import copy
import unittest

from cabinet.icm_display import display_fields


class IcmDisplayTests(unittest.TestCase):
    def setUp(self):
        self.document = dict(state='DIAGNOSTIC_ONLY', test=False, boot_id='board/cookie', snapshot_age_ms=100,
                             sensors=[dict(channel=channel, who=0x2e, fresh=True, error=False, config_verified=True,
                                           config_bad_mask=0, sample_age_ms=0.1, raw=[-32768, 0, 32767], observed_rate_hz=2800)
                                      for channel in 'AB'])

    def fields(self, **changes):
        values = dict(document=self.document, now=100.2, received_at=100.0, boot='board/cookie/session')
        values.update(changes)
        return display_fields(**values)

    def test_unqualified_rate_is_visible_as_raw_not_features(self):
        result = self.fields()
        self.assertIn('-32768', result['panel_icm_a_raw'])
        self.assertIn('2800Hz', result['panel_icm_a_info'])
        self.assertEqual(result['panel_icm_a_deadline_ms'], '101400')
        self.assertNotIn('daily_rms_a_x', result)
        self.assertNotIn('panel_vibration_valid', result)

    def test_no_mutation(self):
        before = copy.deepcopy(self.document)
        self.fields()
        self.assertEqual(before, self.document)

    def test_absent_diagnostics_hide_raw(self):
        self.assertEqual(self.fields(document=None)['panel_icm_a_deadline_ms'], '0')

    def test_test_mode_hides_raw(self):
        self.document['test'] = True
        self.assertEqual(self.fields()['panel_icm_a_deadline_ms'], '0')

    def test_rejected_test_history_hides_raw(self):
        self.assertEqual(self.fields(reject_test=True)['panel_icm_a_deadline_ms'], '0')

    def test_wrong_boot_hides_raw(self):
        self.assertEqual(self.fields(boot='different/session')['panel_icm_a_deadline_ms'], '0')

    def test_queued_age_counts_toward_expiry(self):
        self.document['snapshot_age_ms'] = 1400
        self.assertEqual(self.fields()['panel_icm_a_deadline_ms'], '0')

    def test_future_packet_hides_raw(self):
        self.assertEqual(self.fields(received_at=101)['panel_icm_a_deadline_ms'], '0')

    def test_faulted_channel_does_not_hide_healthy_channel(self):
        self.document['sensors'][0]['error'] = True
        result = self.fields()
        self.assertEqual(result['panel_icm_a_deadline_ms'], '0')
        self.assertNotEqual(result['panel_icm_b_deadline_ms'], '0')

    def test_malformed_raw_is_hidden(self):
        for raw in [[1, 2], [1, 2, 32768], [True, 2, 3], [1.1, 2, 3]]:
            self.document['sensors'][0]['raw'] = raw
            self.assertEqual(self.fields()['panel_icm_a_deadline_ms'], '0')

    def test_repeated_or_reordered_channels_hidden(self):
        self.document['sensors'][1]['channel'] = 'A'
        self.assertEqual(self.fields()['panel_icm_a_deadline_ms'], '0')

    def test_nonfinite_age_is_hidden(self):
        self.document['snapshot_age_ms'] = float('nan')
        self.assertEqual(self.fields()['panel_icm_a_deadline_ms'], '0')

    def test_bad_configuration_hides_raw(self):
        self.document['sensors'][0]['config_bad_mask'] = 1
        self.assertEqual(self.fields()['panel_icm_a_deadline_ms'], '0')

    def test_nan_rate_not_displayed(self):
        self.document['sensors'][0]['observed_rate_hz'] = float('nan')
        self.assertIn('rate --', self.fields()['panel_icm_a_info'])


if __name__ == '__main__':
    unittest.main()
