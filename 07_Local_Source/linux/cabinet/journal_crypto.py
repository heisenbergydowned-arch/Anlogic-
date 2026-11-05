"""Authenticated journal payloads; keys are provisioned separately from SD data."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat


TABLE_KEYS = {
    'events': ('event_id', 'revision'), 'outbox': ('event_id', 'revision'),
    'receipts': ('event_id', 'revision'), 'snapshots': ('device_id', None),
    'fifo_records': ('record_id', None), 'waveforms': ('record_id', None),
    'history_samples': ('id', None), 'diagnostics': ('id', None),
}


def private_key(path):
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size != 32:
            raise ValueError('An owned, private 32-byte journal key is required')
        key = os.read(descriptor, 33)
        if len(key) != 32:
            raise ValueError('Journal key length changed')
        return key
    finally:
        os.close(descriptor)


def create_key(path):
    path = Path(path)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, 'wb', closefd=False) as stream:
            stream.write(secrets.token_bytes(32));stream.flush();os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


class JournalCipher:
    def __init__(self, config, metadata):
        if type(config) is not dict or not {'enabled','key_file'}<=set(config) or config['enabled'] is not True:
            raise ValueError('Explicit authenticated journal configuration required')
        from .openssl_aead import cipher_provider
        key = private_key(config['key_file'])
        self.key_id = hashlib.sha256(key).hexdigest()
        self.metadata = metadata or dict(schema='cabinet-journal-aesgcm-v1', key_id=self.key_id, scope=secrets.token_hex(16))
        if (set(self.metadata) != {'schema', 'key_id', 'scope'} or self.metadata['schema'] != 'cabinet-journal-aesgcm-v1'
                or self.metadata['key_id'] != self.key_id or type(self.metadata['scope']) is not str
                or len(self.metadata['scope']) != 32):
            raise ValueError('Journal key or encryption metadata mismatch')
        self.cipher = cipher_provider(key,config)

    def associated(self, table, identity, revision):
        if table not in TABLE_KEYS:
            raise ValueError('Unsupported encrypted journal table')
        return json.dumps([self.metadata['schema'], self.metadata['scope'], table, str(identity), revision], separators=(',', ':')).encode()

    def seal(self, document, table, identity, revision=None):
        nonce = secrets.token_bytes(12)
        raw = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        ciphertext = self.cipher.encrypt(nonce, raw, self.associated(table, identity, revision))
        return 'CJE1:' + base64.b64encode(nonce + ciphertext).decode('ascii')

    def open(self, payload, table, identity, revision=None):
        if type(payload) is not str or not payload.startswith('CJE1:'):
            raise ValueError('Plaintext is forbidden in an encrypted journal')
        try:
            raw = base64.b64decode(payload[5:], validate=True)
            document = self.cipher.decrypt(raw[:12], raw[12:], self.associated(table, identity, revision))
            return json.loads(document)
        except Exception as error:
            raise ValueError('Journal authentication failed; no plaintext fallback') from error


def configure(database, config=None, readonly=False):
    tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    metadata = None
    if 'journal_security' in tables:
        rows = database.execute('SELECT metadata FROM journal_security').fetchall()
        if len(rows) != 1:
            raise ValueError('Journal encryption metadata is corrupt')
        metadata = json.loads(rows[0][0])
    if not config:
        if metadata is not None:
            raise ValueError('Encrypted journal requires its key; plaintext fallback is forbidden')
        return None
    cipher = JournalCipher(config, metadata)
    if metadata is None:
        if readonly or any(database.execute('SELECT 1 FROM "' + table + '" LIMIT 1').fetchone() for table in TABLE_KEYS if table in tables):
            raise ValueError('Use explicit offline migration to a fresh encrypted journal')
        database.execute('CREATE TABLE journal_security(metadata TEXT NOT NULL)')
        database.execute('INSERT INTO journal_security VALUES(?)', (json.dumps(cipher.metadata),))
        database.commit()
    return cipher


def migrate(source, destination, config):
    import sqlite3
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Existing regular source required')
    origin = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
    descriptor = None
    target = None
    try:
        origin.execute('BEGIN')
        schemas = origin.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        if {name for name, unused in schemas} - set(TABLE_KEYS) - {'waveform_index'}:
            raise ValueError('Unexpected or already encrypted source database')
        if not {'events', 'outbox', 'snapshots'} <= {name for name, unused in schemas}:
            raise ValueError('Cabinet event journal required')
        descriptor = os.open(str(destination), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(descriptor);descriptor = None
        target = sqlite3.connect(str(destination))
        cipher = configure(target, config)
        with target:
            for table, schema in schemas:
                target.execute(schema)
                columns = [row[1] for row in origin.execute('PRAGMA table_info("' + table + '")')]
                for row in origin.execute('SELECT * FROM "' + table + '"'):
                    values = dict(zip(columns, row))
                    if table in TABLE_KEYS:
                        identity, revision = TABLE_KEYS[table]
                        document = json.loads(values['payload'])
                        if table == 'diagnostics':
                            document = dict(code=values['code'], payload=document);values['code'] = 'ENCRYPTED'
                        values['payload'] = cipher.seal(document, table, values[identity], values.get(revision))
                    target.execute('INSERT INTO "' + table + '" VALUES(' + ','.join('?' for unused in columns) + ')', [values[name] for name in columns])
            for statement, in origin.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
                target.execute(statement)
        if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Migrated journal integrity failed')
        return dict(status='PASS_OFFLINE_ENCRYPTED_COPY_SOURCE_UNCHANGED', key_id=cipher.key_id, destination=str(destination), source_deleted=False)
    finally:
        if target is not None:
            target.close()
        if descriptor is not None:
            os.close(descriptor)
        origin.close()
