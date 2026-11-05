"""Real local HTTP requests; no collector, MMIO or control actions."""
import http.client
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from cabinet.web import server


class BenchStatusHTTP(unittest.TestCase):
    def setUp(self):
        self.snapshot = dict(state='ACTIVE_BENCH_NOT_CLOSED_LOOP', id='a' * 32,
                             controls_enabled=True, records=[])
        self.bench = SimpleNamespace(snapshot=Mock(return_value=self.snapshot))
        self.work = SimpleNamespace(status=Mock(side_effect=AssertionError('full workspace read')))
        self.service = SimpleNamespace(workbench=self.work, bench=self.bench)
        self.http = server('127.0.0.1', 0, self.service, token='read-token',
                           control_token='control-' + 'x' * 32)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def request(self, path='/api/commissioning/bench-status', token='read-token'):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_address[1], timeout=1)
        headers = {} if token is None else {'Authorization': 'Bearer ' + token}
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        connection.close()
        return result

    def test_read_auth_required_and_only_snapshot_returned(self):
        for token in (None, 'wrong'):
            self.assertEqual(self.request(token=token)[0], 401)
        self.bench.snapshot.assert_not_called()
        status, value, headers = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(value, self.snapshot)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.bench.snapshot.assert_called_once_with()
        self.work.status.assert_not_called()

    def test_fast_get_finishes_while_full_status_is_still_blocked(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        errors = []

        def slow():
            entered.set()
            if not release.wait(3):
                raise OSError('test did not release workspace')
            return {'large_workspace': 'finished'}

        def request_slow():
            try:
                # Deliberately longer timeout for this single blocked fixture.
                connection = http.client.HTTPConnection('127.0.0.1', self.http.server_address[1], timeout=4)
                connection.request('GET', '/api/commissioning/status', headers={'Authorization': 'Bearer read-token'})
                self.assertEqual(connection.getresponse().read(), b'{"large_workspace": "finished"}')
                connection.close()
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()

        self.work.status.side_effect = slow
        worker = threading.Thread(target=request_slow)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.request()[1], self.snapshot)
            self.assertFalse(finished.is_set())
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(errors)
        self.assertTrue(finished.is_set())

    def test_snapshot_failure_does_not_fall_back_to_workspace(self):
        self.bench.snapshot.side_effect = OSError('collector unavailable')
        status, value, _ = self.request()
        self.assertEqual(status, 503)
        self.assertEqual(value['error'], 'bench_status_unavailable')
        self.work.status.assert_not_called()

    def test_local_workspace_and_missing_workbench_are_explicit(self):
        del self.service.bench
        status, value, _ = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(value, dict(state='LOCAL_ONLY', hardware_supported=False, controls_enabled=False))
        self.service.workbench = None
        self.assertEqual(self.request()[0], 404)
        self.work.status.assert_not_called()


if __name__ == '__main__':
    unittest.main()
