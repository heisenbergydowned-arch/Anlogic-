import copy
from pathlib import Path
import tempfile
import unittest

from cabinet.baseline import digest
from cabinet.learning_agent import AgentJournal, HTTPSExchange, LearningAgent, NoRedirect
from test_learning_web import WebHarness


class FakeTransport:
    def __init__(self):
        self.command = None
        self.failure = False
        self.bad_ack = False
        self.device_id = 'test-device'
        self.sent = []

    def exchange(self, payload):
        self.sent.append(copy.deepcopy(payload))
        if self.failure:
            raise OSError('offline')
        receipts = [{'request_id': item['request_id'], 'result_hash': item['result_hash']} for item in payload['results']]
        if self.bad_ack and receipts:
            receipts[0]['result_hash'] = '0' * 64
        return {'schema': 'cabinet-learning-exchange-reply-v1', 'device_id': self.device_id,
                'acknowledged_results': receipts, 'command': self.command}


class LearningAgentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.harness = WebHarness(self.directory.name)
        self.path = Path(self.directory.name) / 'agent.sqlite'
        self.journal = AgentJournal(self.path)
        self.transport = FakeTransport()
        self.calls = []
        self.agent = LearningAgent('test-device', 'unused-socket', self.journal, self.transport, self.local)

    def tearDown(self):
        self.journal.close()
        self.harness.store.close()
        self.directory.cleanup()

    def local(self, path, payload):
        self.calls.append(copy.deepcopy(payload))
        if 'schema' in payload:
            return self.harness.execute(payload)
        return self.harness.web.query(payload, self.harness.now)

    def test_outbound_exchange_and_exact_ack(self):
        self.transport.command = self.harness.envelope()
        self.assertTrue(self.agent.tick()['ok'])
        self.assertEqual(len(self.journal.pending()), 1)
        self.transport.command = None
        self.agent.tick()
        self.assertEqual(self.journal.pending(), [])
        self.assertEqual(self.transport.sent[1]['results'][0]['result']['command_state'], 'SUCCEEDED')

    def test_repeated_delivery_does_not_reexecute(self):
        self.transport.command = self.harness.envelope()
        self.agent.tick()
        original = self.harness.learner.job_id
        self.agent.tick()
        self.assertEqual(sum('schema' in item for item in self.calls), 1)
        self.assertEqual(self.harness.learner.job_id, original)

    def test_changed_request_rejected_after_ack(self):
        envelope = self.harness.envelope()
        self.agent.receive(envelope)
        self.journal.acknowledge([{'request_id': item['request_id'], 'result_hash': item['result_hash']} for item in self.journal.pending()], self.journal.pending())
        envelope['actor']['audit_id'] = 'different-audit'
        with self.assertRaisesRegex(ValueError, 'REQUEST_ID_REUSED'):
            self.agent.receive(envelope)

    def test_network_failure_preserves_result(self):
        self.agent.receive(self.harness.envelope())
        self.transport.failure = True
        with self.assertRaises(OSError):
            self.agent.tick()
        self.assertEqual(len(self.journal.pending()), 1)
        self.transport.failure = False
        self.agent.tick()
        self.assertEqual(self.journal.pending(), [])

    def test_wrong_ack_never_removes_result(self):
        self.agent.receive(self.harness.envelope())
        self.transport.bad_ack = True
        with self.assertRaisesRegex(ValueError, 'INVALID_RESULT_RECEIPTS'):
            self.agent.tick()
        self.assertEqual(len(self.journal.pending()), 1)

    def test_timeout_after_execution_reconciles_original_id(self):
        envelope = self.harness.envelope()

        def timeout(path, payload):
            if 'schema' in payload:
                self.local(path, payload)
                raise OSError('reply lost')
            return self.local(path, payload)

        self.agent.local_request = timeout
        self.agent.receive(envelope)
        self.assertEqual(self.journal.pending()[0]['result']['command_state'], 'UNKNOWN')
        self.agent.reconcile()
        self.assertEqual(self.journal.pending()[0]['result']['command_state'], 'SUCCEEDED')
        self.assertEqual(sum('schema' in item for item in self.calls), 1)

    def test_interrupted_agent_intent_is_not_replayed(self):
        envelope = self.harness.envelope()
        self.journal.reserve(envelope)
        self.journal.close()
        self.journal = AgentJournal(self.path)
        self.agent.journal = self.journal
        self.transport.command = envelope
        self.agent.tick()
        self.assertEqual(sum('schema' in item for item in self.calls), 0)
        self.assertIsNone(self.harness.learner.job_id)
        self.assertEqual(self.transport.sent[0]['results'][0]['result']['command_state'], 'UNKNOWN')

    def test_unknown_ack_still_allows_later_resolution(self):
        envelope = self.harness.envelope()
        self.journal.reserve(envelope)
        self.agent.tick()
        self.assertEqual(self.journal.pending(), [])
        self.harness.execute(envelope)
        self.agent.reconcile()
        self.assertEqual(self.journal.pending()[0]['result']['command_state'], 'SUCCEEDED')

    def test_unknown_reconciliation_is_not_starved_by_old_entries(self):
        envelopes = [self.harness.envelope() for _ in range(10)]
        for envelope in envelopes:
            self.journal.reserve(envelope)
        self.agent.reconcile()
        self.agent.reconcile()
        queried = {item['request_id'] for item in self.calls if item.get('view') == 'command'}
        self.assertEqual(queried, {item['request_id'] for item in envelopes})

    def test_agent_journal_full_fails_closed(self):
        for _ in range(1024):
            self.journal.reserve(self.harness.envelope())
        with self.assertRaisesRegex(ValueError, 'AGENT_JOURNAL_FULL'):
            self.agent.receive(self.harness.envelope())
        self.assertIsNone(self.harness.learner.job_id)

    def test_no_new_id_on_unknown(self):
        envelope = self.harness.envelope()
        self.journal.reserve(envelope)
        self.agent.reconcile()
        receipt = self.journal.pending()[0]
        self.assertEqual(receipt['request_id'], envelope['request_id'])
        self.assertEqual(receipt['result_hash'], digest(receipt['result']))

    def test_wrong_backend_device_rejected(self):
        self.transport.device_id = 'other-device'
        with self.assertRaisesRegex(ValueError, 'INVALID_EXCHANGE_RESPONSE'):
            self.agent.tick()
        self.assertIsNone(self.harness.learner.job_id)

    def test_wrong_command_device_rejected(self):
        envelope = self.harness.envelope()
        envelope['device_id'] = 'other-device'
        with self.assertRaisesRegex(ValueError, 'INVALID_DELIVERED_COMMAND'):
            self.agent.receive(envelope)

    def test_local_identity_mismatch_blocks_transport(self):
        self.agent.device_id = 'other-device'
        with self.assertRaisesRegex(ValueError, 'LOCAL_IDENTITY_OR_SESSION_MISMATCH'):
            self.agent.tick()
        self.assertEqual(self.transport.sent, [])

    def test_reboot_does_not_turn_historical_success_into_current_job(self):
        envelope = self.harness.envelope()
        self.agent.receive(envelope)
        self.harness.learner.finish('ABORTED', 'SERVICE_STOPPED')
        self.transport.command = envelope
        self.agent.tick()
        self.assertEqual(self.harness.learner.state, 'ABORTED')
        self.assertEqual(sum('schema' in item for item in self.calls), 1)

    def test_https_only_origin_and_private_credential(self):
        token = Path(self.directory.name) / 'token'
        token.write_text('private-device-token-value', encoding='ascii')
        token.chmod(0o600)
        for origin in ('http://example.com', 'https://user:pass@example.com',
                       'https://example.com/path', 'https://example.com?query=1', 'file:///tmp/test'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                HTTPSExchange(origin, 'test-device', token)
        self.assertTrue(HTTPSExchange('https://example.com', 'test-device', token).url.endswith('/learning/exchange'))
        self.assertIn('machine%3Aabc', HTTPSExchange('https://example.com', 'machine:abc', token).url)
        token.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'PRIVATE_TOKEN_FILE_REQUIRED'):
            HTTPSExchange('https://example.com', 'test-device', token)

    def test_redirect_does_not_forward_credentials(self):
        handler = NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_token_symlink_rejected(self):
        token = Path(self.directory.name) / 'token'
        token.write_text('private-device-token-value', encoding='ascii')
        token.chmod(0o600)
        link = Path(self.directory.name) / 'token-link'
        link.symlink_to(token)
        with self.assertRaises(OSError):
            HTTPSExchange('https://example.com', 'test-device', link)


if __name__ == '__main__':
    unittest.main()
