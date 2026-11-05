"""Outbound-only HTTPS learning transport. No UIO, display or actuator access."""
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import stat
import urllib.parse
import urllib.request

from .baseline import canonical, digest
from .learning_rpc import request
from .learning_web import COMMAND_SCHEMA, PAYLOADS, is_uuid, strict_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPSExchange:
    def __init__(self, origin, device_id, token_file, ca_file=None):
        parsed = urllib.parse.urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or
                parsed.password is not None or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('HTTPS_ORIGIN_REQUIRED')
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', device_id):
            raise ValueError('INVALID_DEVICE_ID')
        token_path = Path(token_file)
        descriptor = os.open(str(token_path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
                raise ValueError('PRIVATE_TOKEN_FILE_REQUIRED')
            raw_token = stream.read(4097)
            if len(raw_token) > 4096:
                raise ValueError('INVALID_DEVICE_TOKEN')
            token = raw_token.decode('ascii').strip()
        if not 16 <= len(token) <= 4096 or any(ord(char) <= 32 or ord(char) >= 127 for char in token):
            raise ValueError('INVALID_DEVICE_TOKEN')
        self.url = origin.rstrip('/') + '/api/v1/devices/' + urllib.parse.quote(device_id, safe='') + '/learning/exchange'
        self.token = token
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca_file)), NoRedirect())

    def exchange(self, payload):
        body = canonical(payload).encode('utf-8')
        if len(body) > 131072:
            raise ValueError('EXCHANGE_TOO_LARGE')
        outgoing = urllib.request.Request(self.url, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json',
            'Accept': 'application/json'})
        with self.opener.open(outgoing, timeout=5) as response:
            if response.status != 200 or response.headers.get_content_type() != 'application/json':
                raise ValueError('INVALID_EXCHANGE_RESPONSE')
            return strict_json(response.read(65537), limit=65536)


class AgentJournal:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        self.connection = sqlite3.connect(str(path))
        path.chmod(0o600)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.execute('''CREATE TABLE IF NOT EXISTS commands (
            id TEXT PRIMARY KEY, envelope TEXT NOT NULL, fingerprint TEXT NOT NULL,
            response TEXT, acknowledged_hash TEXT)''')

    def reserve(self, envelope):
        identity = envelope['request_id']
        previous = self.connection.execute('SELECT fingerprint FROM commands WHERE id=?', (identity,)).fetchone()
        if previous:
            if previous[0] != digest(envelope):
                raise ValueError('REQUEST_ID_REUSED')
            return False
        with self.connection:
            if self.connection.execute('SELECT count(*) FROM commands').fetchone()[0] >= 1024:
                raise ValueError('AGENT_JOURNAL_FULL')
            self.connection.execute('INSERT INTO commands VALUES(?,?,?,NULL,NULL)',
                                    (identity, canonical(envelope), digest(envelope)))
        return True

    def save(self, identity, response):
        with self.connection:
            self.connection.execute('UPDATE commands SET response=? WHERE id=?', (canonical(response), identity))

    def unresolved(self):
        results = []
        for identity, envelope, response in self.connection.execute('SELECT id,envelope,response FROM commands'):
            if response is None or json.loads(response)['command_state'] == 'UNKNOWN':
                results.append((identity, json.loads(envelope)))
        return results

    def pending(self):
        results = []
        for identity, response, acknowledged in self.connection.execute('SELECT id,response,acknowledged_hash FROM commands WHERE response IS NOT NULL'):
            value = json.loads(response)
            checksum = digest(value)
            if checksum != acknowledged:
                results.append({'request_id': identity, 'result_hash': checksum, 'result': value})
            if len(results) >= 8:
                break
        return results

    def acknowledge(self, receipts, sent):
        expected = {item['request_id']: item['result_hash'] for item in sent}
        if not isinstance(receipts, list) or len(receipts) > len(sent):
            raise ValueError('INVALID_RESULT_RECEIPTS')
        identities = set()
        for receipt in receipts:
            if (not isinstance(receipt, dict) or set(receipt) != {'request_id', 'result_hash'} or
                    not isinstance(receipt['request_id'], str) or receipt['request_id'] in identities or
                    expected.get(receipt['request_id']) != receipt['result_hash']):
                raise ValueError('INVALID_RESULT_RECEIPTS')
            identities.add(receipt['request_id'])
        with self.connection:
            for receipt in receipts:
                self.connection.execute('UPDATE commands SET acknowledged_hash=? WHERE id=?',
                                        (receipt['result_hash'], receipt['request_id']))

    def close(self):
        self.connection.close()


class LearningAgent:
    def __init__(self, device_id, socket_path, journal, transport, local_request=request):
        self.device_id = device_id
        self.socket_path = socket_path
        self.journal = journal
        self.transport = transport
        self.local_request = local_request
        self.reconcile_offset = 0

    def local(self, payload):
        result = self.local_request(self.socket_path, payload)
        if not isinstance(result, dict):
            raise ValueError('INVALID_LOCAL_RESPONSE')
        return result

    def matching(self, response, envelope):
        return (isinstance(response, dict) and response.get('schema') == 'cabinet-learning-result-v1' and
                all(response.get(key) == envelope[key] for key in ('device_id', 'request_id', 'session_id', 'operation')) and
                response.get('command_state') in ('SUCCEEDED', 'REJECTED', 'EXPIRED', 'UNKNOWN') and
                type(response.get('ok')) is bool and isinstance(response.get('reason'), str) and
                (response['command_state'] == 'SUCCEEDED') == response['ok'])

    def unknown(self, envelope):
        result = {key: envelope[key] for key in ('device_id', 'request_id', 'session_id', 'operation')}
        result.update(schema='cabinet-learning-result-v1', ok=False, reason='RESULT_UNKNOWN', command_state='UNKNOWN')
        return result

    def reconcile(self):
        unresolved = self.journal.unresolved()
        if not unresolved:
            self.reconcile_offset = 0
            return
        offset = self.reconcile_offset % len(unresolved)
        batch = (unresolved[offset:] + unresolved[:offset])[:8]
        self.reconcile_offset = offset + len(batch)
        for identity, envelope in batch:
            try:
                response = self.local({'operation': 'status', 'view': 'command', 'request_id': identity})
            except (OSError, RuntimeError, ValueError):
                response = None
            self.journal.save(identity, response if self.matching(response, envelope) else self.unknown(envelope))

    def receive(self, envelope):
        if (not isinstance(envelope, dict) or envelope.get('schema') != COMMAND_SCHEMA or
                envelope.get('device_id') != self.device_id or not is_uuid(envelope.get('request_id')) or
                not is_uuid(envelope.get('session_id')) or not isinstance(envelope.get('operation'), str) or
                envelope['operation'] not in PAYLOADS or len(canonical(envelope).encode('utf-8')) > 4096):
            raise ValueError('INVALID_DELIVERED_COMMAND')
        if not self.journal.reserve(envelope):
            return
        try:
            response = self.local(envelope)
        except (OSError, RuntimeError, ValueError):
            response = None
        self.journal.save(envelope['request_id'], response if self.matching(response, envelope) else self.unknown(envelope))

    def tick(self):
        self.reconcile()
        status = self.local({'operation': 'status', 'view': 'web'})
        history = self.local({'operation': 'status', 'view': 'baselines'})
        if (status.get('schema') != 'cabinet-learning-status-v1' or status.get('device_id') != self.device_id or
                status.get('ok') is not True or not is_uuid(status.get('session_id')) or
                history.get('ok') is not True or history.get('device_id') != self.device_id or
                history.get('session_id') != status['session_id']):
            raise ValueError('LOCAL_IDENTITY_OR_SESSION_MISMATCH')
        pending = self.journal.pending()
        reply = self.transport.exchange({'schema': 'cabinet-learning-exchange-v1', 'device_id': self.device_id,
                                         'status': status, 'baselines': history['baselines'], 'results': pending})
        if (not isinstance(reply, dict) or set(reply) != {'schema', 'device_id', 'acknowledged_results', 'command'} or
                reply['schema'] != 'cabinet-learning-exchange-reply-v1' or reply['device_id'] != self.device_id):
            raise ValueError('INVALID_EXCHANGE_RESPONSE')
        self.journal.acknowledge(reply['acknowledged_results'], pending)
        if reply['command'] is not None:
            self.receive(reply['command'])
        return {'ok': True, 'session_id': status['session_id'], 'pending_results': len(self.journal.pending())}
