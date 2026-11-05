"""A previous model's advisory must not veto user-labelled replacement data."""
import copy
import unittest
from normal_npu.learning import save
from tests.test_npu_learning import LearningTests
from tests.test_learning_recovery_p19 import RetryFixture


class LearningAdvisoryTests(RetryFixture, unittest.TestCase):
    setUp = LearningTests.setUp
    body = LearningTests.body
    start = LearningTests.start

    def advisory(self, source=0x52, extra=None):
        s = self.document['observation']['status']
        s['raw_words'][31] = (source << 16) | 4
        s['active'] = ['CONFIG_UNQUALIFIED', 'STOP_UNCONFIRMED', 'SOFT_PS'] + (extra or [])
        save(self.root/'state.json', self.document)

    def test_user_can_relearn_despite_previous_model_advisory(self):
        self.advisory()
        j = self.start()
        self.store.check(j)
        self.assertTrue(j['healthy_confirmed'])
        self.assertFalse(j['controls_changed'])

    def test_unrelated_advisory_and_actual_fault_still_reject(self):
        j = self.start()
        for source, extra in ((0x53, []), (0x52, ['OC_HARD'])):
            self.advisory(source, extra)
            with self.subTest(source=source, extra=extra), self.assertRaisesRegex(ValueError, 'HARDWARE_FAULT_ACTIVE'):
                self.store.check(j)

    def test_capture_retry_keeps_original_advisory_evidence(self):
        self.advisory()
        self.start()
        j = self.store.claim(self.worker)
        j, status, folder = self.failed_capture(j, 'train')
        before = (folder/'frames.jsonl').read_bytes()
        result = self.store.capture_poll(j['id'], self.worker)
        self.assertEqual(result['state'], 'CAPTURING_TRAIN')
        self.assertEqual((folder/'frames.jsonl').read_bytes(), before)
        self.assertIn(b'SOFT_PS', before)

    def test_terminal_fault_is_not_hidden_by_advisory_filter(self):
        self.advisory()
        self.start()
        j = self.store.claim(self.worker)
        j, status, folder = self.failed_capture(j, 'train')
        import json
        summary = json.loads((folder/'summary.json').read_text())
        summary['terminal_observation']['status']['active'].append('OC_HARD')
        with self.assertRaisesRegex(ValueError, 'HARDWARE_FAULT_ACTIVE'):
            self.store._check_capture_terminal(j, summary)


if __name__ == '__main__':
    unittest.main()
