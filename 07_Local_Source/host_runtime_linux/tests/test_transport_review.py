import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cabinet.uplink import Uplink


class Outbox:
    def __init__(self):
        self.deliveries, self.retries = [], []

    def pending(self):
        return [dict(event_id='unit-event', revision=1, attempts=0,
                     payload=dict(event_id='unit-event', event_revision=1))]

    def delivered(self, identity, revision):
        self.deliveries.append((identity, revision))

    def retry(self, identity, revision, attempts):
        self.retries.append((identity, revision, attempts))


class EventTransportTests(unittest.TestCase):
    def server(self, handler):
        server = HTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(2)))
        return server

    def test_redirect_is_not_followed_and_never_forwards_device_token(self):
        received = []
        class Target(BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass

            def do_GET(self):
                received.append(self.headers.get('Authorization'))
                body = json.dumps(dict(accepted=True, event_id='unit-event', event_revision=1)).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        target = self.server(Target)
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1:%d/stolen' % target.server_address[1])
                self.send_header('Content-Length', '0')
                self.end_headers()
        redirect = self.server(Redirect)
        outbox = Outbox()
        with patch.dict('os.environ', UNIT_EVENT_TOKEN='UNIT_ONLY_NOT_A_REAL_SECRET'):
            uplink = Uplink(dict(url='http://127.0.0.1:%d/events' % redirect.server_address[1],
                loopback_test=True, token_env='UNIT_EVENT_TOKEN'), outbox)
            self.assertEqual(uplink.once(), 0)
        self.assertEqual(received, [])
        self.assertEqual(outbox.deliveries, [])
        self.assertEqual(len(outbox.retries), 1)

    def test_ambiguous_or_boolean_receipts_do_not_delete_durable_events(self):
        replies = [b'{"accepted":true,"event_id":"unit-event","event_revision":true}',
                   b'{"accepted":false,"accepted":true,"event_id":"unit-event","event_revision":1}',
                   b'{"accepted":true,"event_id":"unit-event","event_revision":1,"padding":"'+b'x'*65536+b'"}']
        for body in replies:
            class Reply(BaseHTTPRequestHandler):
                def log_message(self, *unused):
                    pass

                def do_POST(self):
                    self.rfile.read(int(self.headers['Content-Length']))
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            server = self.server(Reply)
            outbox = Outbox()
            uplink = Uplink(dict(url='http://127.0.0.1:%d/events' % server.server_address[1], loopback_test=True), outbox)
            self.assertEqual(uplink.once(), 0)
            self.assertEqual(outbox.deliveries, [])


if __name__ == '__main__':
    unittest.main()
