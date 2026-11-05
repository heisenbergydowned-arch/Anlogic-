"""Standalone authenticated maintenance receiver; no hardware or actuator access."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import sqlite3
import threading
from urllib.parse import urlsplit, parse_qs
from cabinet.web import ThreadingHTTPServer
from hmi_daily.cabinet.learning_web import strict_json


class CloudStore:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=1)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS received(id INTEGER PRIMARY KEY,device TEXT,event TEXT,revision INTEGER,body TEXT,UNIQUE(device,event))')
        self.db.commit()

    def receive(self, event):
        device, identity, revision = event.get('device_id'), event.get('event_id'), event.get('event_revision')
        if any(type(value) is not str or not 1 <= len(value) <= 200 for value in (device, identity)) or type(revision) is not int or not 1 <= revision < 2 ** 63:
            raise ValueError('Invalid event identity')
        body = json.dumps(event, sort_keys=True, allow_nan=False)
        with self.lock, self.db:
            old = self.db.execute('SELECT revision,body FROM received WHERE device=? AND event=?', (device, identity)).fetchone()
            if old and old[0] == revision and old[1] != body:
                raise ValueError('Conflicting idempotency identity')
            if old is None:
                self.db.execute('INSERT INTO received(device,event,revision,body) VALUES(?,?,?,?)', (device, identity, revision, body))
            elif revision > old[0]:
                self.db.execute('UPDATE received SET revision=?,body=? WHERE device=? AND event=?', (revision, body, device, identity))
        return dict(accepted=True, event_id=identity, event_revision=revision)

    def list(self, device=None, after=0, limit=100):
        if type(after) is not int or not 0 <= after < 2 ** 63 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Invalid cloud pagination')
        with self.lock:
            rows = self.db.execute('SELECT id,body FROM received WHERE id>? AND (? IS NULL OR device=?) ORDER BY id LIMIT ?',
                                   (after, device, device, limit + 1)).fetchall()
        return dict(items=[dict(json.loads(body), archive_id=identity) for identity, body in rows[:limit]],
                    next_after=rows[limit - 1][0] if len(rows) > limit else None)

    def close(self):
        self.db.close()


def receiver(address, store, device_tokens, admin_token):
    if not admin_token or any(not token for token in device_tokens.values()):
        raise ValueError('Explicit device and administrator credentials required')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, document):
            data = json.dumps(document, allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store');self.send_header('Content-Length', str(len(data)))
            self.end_headers();self.wfile.write(data)

        def authorized(self, token):
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def do_POST(self):
            if self.path != '/v1/devices/events':
                return self.reply(404, dict(error='not_found'))
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536 or len(self.headers.get_all('Content-Length', [])) != 1 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Invalid request framing')
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('JSON required')
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('Truncated event')
                event = strict_json(body, limit=65536)
                token = device_tokens.get(event.get('device_id')) if type(event) is dict else None
                if token is None or not self.authorized(token):
                    return self.reply(401, dict(error='unauthorized'))
                expected = str(event.get('event_id')) + ':' + str(event.get('event_revision'))
                if self.headers.get('Idempotency-Key') != expected:
                    raise ValueError('Idempotency identity mismatch')
                return self.reply(200, store.receive(event))
            except (ValueError, KeyError, TypeError, OverflowError):
                return self.reply(400, dict(error='invalid_event'))

        def do_GET(self):
            if not self.authorized(admin_token):
                return self.reply(401, dict(error='unauthorized'))
            route = urlsplit(self.path)
            if route.path != '/api/workorders':
                return self.reply(404, dict(error='not_found'))
            try:
                params = parse_qs(route.query, keep_blank_values=True)
                if set(params) - {'device', 'after', 'limit'} or any(len(values) != 1 for values in params.values()):
                    raise ValueError('Invalid query')
                return self.reply(200, store.list(params.get('device', [None])[0], int(params.get('after', ['0'])[0]), int(params.get('limit', ['100'])[0])))
            except (ValueError, TypeError, OverflowError):
                return self.reply(400, dict(error='invalid_query'))
    return ThreadingHTTPServer(address, Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    config = strict_json(args.config.read_bytes(), limit=65536)
    store = CloudStore(config['database'])
    listener = receiver(('127.0.0.1', config.get('port', 8767)), store,
        {device: os.environ[variable] for device, variable in config['device_token_env'].items()}, os.environ[config['admin_token_env']])
    try:
        listener.serve_forever()
    finally:
        listener.server_close();store.close()
