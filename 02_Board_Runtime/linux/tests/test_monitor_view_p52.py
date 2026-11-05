import unittest
from types import SimpleNamespace
from cabinet.monitor_view import snapshot


class MonitorView(unittest.TestCase):
    def observer(self, **changes):
        fields=dict(daily_current_value='0.400', daily_current_valid='1',
                    panel_nn_valid='1', panel_nn_deadline_ms='100500',
                    panel_classifier_valid='1', panel_classifier_deadline_ms='100500',
                    panel_prob_normal='91.2', unrelated='not public')
        value=dict(advisory_sample=dict(boot='device/session/1',link='ONLINE',received_at=100.),
                   advisory_rendered=fields,advisory_refreshed_at=100.1)
        value.update(changes)
        return SimpleNamespace(**value)

    def test_exact_hdmi_values_and_no_unrelated_fields(self):
        v=snapshot(self.observer(),'device/session/1',100.2)
        self.assertTrue(v['available'])
        self.assertEqual(v['fields']['daily_current_value'],'0.400')
        self.assertEqual(v['fields']['panel_prob_normal'],'91.2')
        self.assertNotIn('unrelated',v['fields'])

    def test_wrong_session_or_stale_snapshot_unavailable(self):
        for identity,now in [('device/session/2',100.2),('device/session/1',102.)]:
            self.assertEqual(snapshot(self.observer(),identity,now),dict(available=False,fields={}))
        self.assertFalse(snapshot(None,'device/session/1',100.2)['available'])

    def test_result_deadline_expires_without_modifying_hdmi_snapshot(self):
        o=self.observer();v=snapshot(o,'device/session/1',100.6)
        self.assertEqual(v['fields']['panel_nn_valid'],'0')
        self.assertEqual(v['fields']['panel_classifier_valid'],'0')
        self.assertEqual(o.advisory_rendered['panel_nn_valid'],'1')

    def test_offline_and_nonfinite_stamp_rejected(self):
        o=self.observer();o.advisory_sample['link']='OFFLINE'
        self.assertFalse(snapshot(o,'device/session/1',100.2)['available'])
        self.assertFalse(snapshot(self.observer(advisory_refreshed_at=float('nan')),'device/session/1',100.2)['available'])
