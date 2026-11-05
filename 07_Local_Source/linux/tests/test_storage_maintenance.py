import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cabinet.maintenance import archive_database, file_sha
from cabinet.store import Store


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'events.sqlite'
        self.store = Store(self.path)
        self.addCleanup(self.store.close)

    def add_event(self, identity, state='RECOVERED', acknowledged=True, pending=False):
        event = dict(event_id=identity, event_revision=1, state=state,
                     acknowledged=acknowledged, notify=pending)
        self.store.event(event)

    def test_backup_is_integrity_checked_private_and_does_not_prune_by_default(self):
        for index in range(10):
            self.add_event(str(index))
        result = archive_database(self.path, self.root / 'archive')
        self.assertEqual(result['pruned'], dict(events=0, fifo_records=0, waveforms=0))
        backup = self.root / 'archive/events.sqlite3'
        self.assertEqual(result['manifest']['database_sha256'], file_sha(backup))
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        connection = sqlite3.connect(str(backup))
        try:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(connection.execute('SELECT count(*) FROM events').fetchone()[0], 10)
        finally:
            connection.close()
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], 10)

    def test_prune_keeps_active_pending_unacknowledged_and_newest_rows(self):
        self.add_event('active', 'ACTIVE')
        self.add_event('unacknowledged', acknowledged=False)
        self.add_event('pending', pending=True)
        self.add_event('safe_old')
        self.add_event('newest')
        result = archive_database(self.path, self.root / 'archive', True, 1)
        self.assertEqual(result['pruned']['events'], 1)
        self.assertEqual({row[0] for row in self.store.db.execute('SELECT event_id FROM events')},
                         {'active', 'unacknowledged', 'pending', 'newest'})

    def test_new_or_revised_rows_after_export_are_never_pruned(self):
        self.add_event('changed')
        self.add_event('unchanged')
        self.add_event('newest')
        original = file_sha

        def mutate_after_export(file):
            result = original(file)
            if (self.root / 'archive/manifest.json').exists():
                self.store.event(dict(event_id='changed', event_revision=2, state='ACTIVE', acknowledged=True, notify=False))
                self.add_event('after_export')
            return result

        with patch('cabinet.maintenance.file_sha', side_effect=mutate_after_export):
            result = archive_database(self.path, self.root / 'archive', True, 1)
        self.assertEqual(result['pruned']['events'], 2)
        self.assertEqual({row[0] for row in self.store.db.execute('SELECT event_id FROM events')}, {'changed', 'after_export'})

    def test_corrupt_backup_aborts_before_pruning(self):
        self.add_event('old')
        self.add_event('newest')
        original = file_sha

        def corrupt(file):
            result = original(file)
            return '0' * 64 if (self.root / 'archive/manifest.json').exists() else result

        with patch('cabinet.maintenance.file_sha', side_effect=corrupt), self.assertRaises(RuntimeError):
            archive_database(self.path, self.root / 'archive', True, 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], 2)

    def test_fifo_raw_is_only_pruned_with_an_archived_acknowledged_historical_event(self):
        for sequence in (1, 2):
            event = dict(event_id=str(sequence), event_revision=1, state='RECORDED', acknowledged=sequence == 1,
                         source='PL_FIFO', boot_id='device/7', event_sequence=sequence, notify=False)
            self.store.fifo('device/7/' + str(sequence), [sequence] * 8, event)
        self.add_event('newest')
        result = archive_database(self.path, self.root / 'archive', True, 1)
        self.assertEqual(result['pruned']['fifo_records'], 1)
        self.assertEqual(self.store.db.execute('SELECT record_id FROM fifo_records').fetchall(), [('device/7/2',)])

    def test_baseline_database_missing_source_symlink_and_existing_archive_are_rejected(self):
        other = self.root / 'baseline.sqlite'
        connection = sqlite3.connect(str(other))
        connection.execute('CREATE TABLE profiles(id TEXT)')
        connection.close()
        with self.assertRaises(ValueError):
            archive_database(other, self.root / 'forbidden')
        self.assertFalse((self.root / 'forbidden').exists())
        alias = self.root / 'alias'
        alias.symlink_to(self.path)
        with self.assertRaises(ValueError):
            archive_database(alias, self.root / 'alias_archive')
        with self.assertRaises(ValueError):
            archive_database(self.root / 'missing', self.root / 'missing_archive')
        archive_database(self.path, self.root / 'archive')
        with self.assertRaises(ValueError):
            archive_database(self.path, self.root / 'archive')

    def test_failed_commit_cannot_delete_source_evidence(self):
        self.add_event('old')
        self.add_event('newest')
        self.store.db.execute("CREATE TRIGGER refuse_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'test rejection'); END")
        self.store.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            archive_database(self.path, self.root / 'archive', True, 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], 2)
        self.assertTrue((self.root / 'archive/manifest.json').is_file())

    def test_storage_diagnostics_do_not_delete_or_block_critical_event_writes(self):
        self.store.storage_policy['min_free_bytes'] = 2**62
        health = self.store.storage_health()
        self.assertEqual(health['state'], 'ARCHIVE_REQUIRED')
        self.assertIn('LOW_DISK_SPACE', health['reasons'])
        self.assertFalse(health['automatic_deletion'])
        self.add_event('critical', 'ACTIVE', pending=True)
        self.assertIsNotNone(self.store.get_event('critical'))
        self.assertEqual(len(self.store.pending()), 1)

    def test_maintenance_never_accepts_boolean_retention_or_zero(self):
        for retention in (True, 0, -1, 1000001):
            with self.assertRaises(ValueError):
                archive_database(self.path, self.root / 'bad', keep_latest=retention)
