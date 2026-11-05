"""Explicit verified SQLite backup and selective pruning; never touches hardware."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def sync_directory(path):
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def archive_database(source, destination, prune=False, keep_latest=1000, encryption=None):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Existing regular event database required')
    if type(prune) is not bool or type(keep_latest) is not int or not 1 <= keep_latest <= 1000000:
        raise ValueError('Explicit prune flag and positive retention count required')
    if destination.exists():
        raise ValueError('Fresh archive directory required')
    source = source.resolve()
    origin = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        required = {'events', 'outbox', 'fifo_records', 'snapshots', 'diagnostics'}
        tables = {row[0] for row in origin.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= tables:
            raise ValueError('Not a cabinet event database; baseline/config databases are forbidden')
        destination.mkdir(mode=0o700, parents=False)
        backup = destination / 'events.sqlite3'
        descriptor = os.open(str(backup), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        target = sqlite3.connect(str(backup))
        try:
            origin.backup(target)
            if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Archive integrity check failed')
            counts = {table: target.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                      for table in sorted(required | ({'waveforms'} if 'waveforms' in tables else set()))}
        finally:
            target.close()
    finally:
        origin.close()
    with backup.open('rb') as stream:
        os.fsync(stream.fileno())
    manifest = dict(schema='cabinet-event-archive-v1', created_utc=datetime.now(timezone.utc).isoformat(),
                    source=str(source), database_sha256=file_sha(backup), rows=counts,
                    qualification_granted=False, automatic_deletion=False)
    receipt = destination / 'manifest.json'
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(str(receipt), 0o600)
    sync_directory(destination)
    sync_directory(destination.parent)
    removed = dict(events=0, fifo_records=0, waveforms=0)
    if prune:
        if file_sha(backup) != manifest['database_sha256']:
            raise RuntimeError('Archive changed before pruning')
        archived = sqlite3.connect(backup.resolve().as_uri() + '?mode=ro', uri=True)
        current = sqlite3.connect(source.as_uri() + '?mode=rw', uri=True, timeout=1)
        try:
            from .journal_crypto import configure
            cipher=configure(current,encryption,readonly=True)
            current.execute('PRAGMA synchronous=FULL')
            current.execute('BEGIN IMMEDIATE')
            rows = current.execute('SELECT event_id,revision,payload FROM events WHERE rowid NOT IN '
                                   '(SELECT rowid FROM events ORDER BY rowid DESC LIMIT ?)', (keep_latest,)).fetchall()
            for identity, revision, payload in rows:
                event = cipher.open(payload,'events',identity,revision) if cipher else json.loads(payload)
                if event.get('state') not in ('RECOVERED', 'RECORDED') or event.get('acknowledged') is not True:
                    continue
                if current.execute('SELECT 1 FROM outbox WHERE event_id=? LIMIT 1', (identity,)).fetchone():
                    continue
                if archived.execute('SELECT revision,payload FROM events WHERE event_id=?', (identity,)).fetchone() != (revision, payload):
                    continue
                if event.get('source') == 'PL_FIFO' and type(event.get('event_sequence')) is int:
                    record = str(event.get('boot_id')) + '/' + str(event['event_sequence'])
                    raw = current.execute('SELECT payload FROM fifo_records WHERE record_id=?', (record,)).fetchone()
                    if raw and archived.execute('SELECT payload FROM fifo_records WHERE record_id=?', (record,)).fetchone() == raw:
                        current.execute('DELETE FROM fifo_records WHERE record_id=?', (record,))
                        removed['fifo_records'] += 1
                current.execute('DELETE FROM events WHERE event_id=? AND revision=?', (identity, revision))
                removed['events'] += 1
            if 'waveforms' in tables:
                from .waveform import checksum, validate_record
                rows = current.execute('SELECT record_id,sha256,payload FROM waveforms WHERE rowid NOT IN '
                                       '(SELECT rowid FROM waveforms ORDER BY rowid DESC LIMIT ?)', (keep_latest,)).fetchall()
                for identity, digest, payload in rows:
                    if archived.execute('SELECT sha256,payload FROM waveforms WHERE record_id=?', (identity,)).fetchone() != (digest, payload):
                        continue
                    record=cipher.open(payload,'waveforms',identity) if cipher else json.loads(payload)
                    if checksum(validate_record(record)) != digest or identity != digest:
                        raise ValueError('Corrupt WAV1 record cannot be pruned')
                    current.execute('DELETE FROM waveforms WHERE record_id=?', (identity,))
                    removed['waveforms'] += 1
            current.commit()
        except BaseException:
            current.rollback()
            raise
        finally:
            current.close()
            archived.close()
    return dict(status='PASS_VERIFIED_EVENT_ARCHIVE', manifest=manifest, pruned=removed,
                archive=str(destination.resolve()), source_compacted=False)
