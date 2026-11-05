"""Boot ownership recovery without native calls, device writes or DMA."""
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from normal_npu import boot_recovery as recovery
from v4_runtime.native_lease import NativeLease

OLD = '0e674fcc-1256-4f2c-910c-f37afdb8a22d'
BOOT = '07867233-5099-4c6f-a566-15f86f5f36b0'


class BootRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'lease.json'
        self.previous = dict(schema='cabinet-native-lease-v1', state='ACTIVE',
                             boot_id=OLD, pid=7758, instance='old-owner')
        self.write(self.previous)
        self.boot_patch = patch.object(recovery, 'current_boot', return_value=BOOT)
        self.boot_patch.start()
        self.addCleanup(self.boot_patch.stop)
        self.proof_patch = patch.object(recovery, 'verified_fresh_driver',
                                       return_value=dict(boot_id=BOOT, irq={'HARD_NPU_IRQ': 0, 'SOFT_NPU_IRQ': 0}))
        self.proof = self.proof_patch.start()
        self.addCleanup(self.proof_patch.stop)

    def write(self, value):
        self.file.write_text(json.dumps(value))
        self.file.chmod(0o600)

    def test_previous_boot_recovered_in_place_with_durable_audit(self):
        raw = self.file.read_bytes()
        inode = self.file.stat().st_ino
        report = recovery.recover(self.file)
        self.assertEqual(report['status'], 'VERIFIED_PREVIOUS_BOOT_LEASE_RECOVERY')
        self.assertEqual(self.file.stat().st_ino, inode)
        current = json.loads(self.file.read_text())
        self.assertEqual((current['state'], current['boot_id']), ('CLEAN', BOOT))
        backup = Path(report['backup'])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        audit = json.loads(backup.read_text())
        self.assertEqual(audit['previous'], self.previous)
        self.assertEqual(audit['previous_sha256'], recovery.digest(raw))
        self.assertEqual(audit['proof']['boot_id'], BOOT)
        self.proof.assert_called_once()

    def test_same_boot_dirty_is_not_cleared_even_if_no_owner(self):
        self.previous['boot_id'] = BOOT
        self.write(self.previous)
        before = self.file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Same-boot'):
            recovery.recover(self.file)
        self.assertEqual(self.file.read_bytes(), before)
        self.proof.assert_not_called()

    def test_legacy_dirty_is_not_automatically_recovered(self):
        del self.previous['boot_id']
        self.write(self.previous)
        with self.assertRaisesRegex(ValueError, 'explicitly pinned'):
            recovery.recover(self.file)
        self.proof.assert_not_called()

    def test_known_legacy_migration_requires_exact_bytes_and_prior_boot(self):
        del self.previous['boot_id']
        self.write(self.previous)
        pin = recovery.digest(self.file.read_bytes())
        for digest, boot in [('0' * 64, OLD), (pin, BOOT), (pin, 'bad-boot')]:
            with self.assertRaises(ValueError):
                recovery.recover(self.file, digest, boot)
        self.assertEqual(json.loads(self.file.read_text())['state'], 'ACTIVE')
        self.assertEqual(recovery.recover(self.file, pin, OLD)['status'], 'VERIFIED_PREVIOUS_BOOT_LEASE_RECOVERY')

    def test_failed_hardware_audit_preserves_dirty_state(self):
        self.proof.side_effect = ValueError('NPU already executed on this boot')
        before = self.file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already executed'):
            recovery.recover(self.file)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse((self.file.parent / 'boot-recovery').exists())

    def test_boot_change_during_audit_is_rejected(self):
        self.proof.return_value = dict(boot_id=OLD)
        with self.assertRaisesRegex(ValueError, 'Boot changed'):
            recovery.recover(self.file)
        self.assertEqual(json.loads(self.file.read_text())['state'], 'ACTIVE')

    def test_existing_owner_lock_cannot_be_stolen(self):
        with self.file.open('r+') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                recovery.recover(self.file)
        self.proof.assert_not_called()

    def test_clean_state_does_not_require_fresh_zero_irq(self):
        self.previous['state'] = 'CLEAN'
        self.write(self.previous)
        self.assertEqual(recovery.recover(self.file)['status'], 'LEASE_ALREADY_CLEAN')
        self.proof.assert_not_called()

    def test_corrupt_oversize_and_unknown_states_never_clear(self):
        for raw in ('{broken', '[]', '{"schema":"cabinet-native-lease-v1","state":"OTHER"}', ' ' * 4097):
            self.file.write_text(raw)
            with self.assertRaises(ValueError):
                recovery.recover(self.file)
            self.assertEqual(self.file.read_text(), raw)

    def test_symlink_hardlink_and_nonprivate_files_are_rejected(self):
        alias = self.file.with_name('alias')
        os.link(str(self.file), str(alias))
        with self.assertRaises(ValueError):
            recovery.recover(self.file)
        alias.unlink()
        self.file.chmod(0o644)
        with self.assertRaises(ValueError):
            recovery.recover(self.file)
        self.file.chmod(0o600)
        self.file.rename(alias)
        self.file.symlink_to(alias)
        with self.assertRaises(OSError):
            recovery.recover(self.file)
        self.proof.assert_not_called()

    def test_history_symlink_cannot_redirect_audit(self):
        target = self.file.parent / 'elsewhere'
        target.mkdir(mode=0o700)
        (self.file.parent / 'boot-recovery').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'Private recovery history'):
            recovery.recover(self.file)
        self.assertEqual(json.loads(self.file.read_text())['state'], 'ACTIVE')

    def test_native_worker_records_current_boot_on_acquire_and_close(self):
        self.file.unlink()
        lease = NativeLease(self.file)
        try:
            active = json.loads(self.file.read_text())
            self.assertIn('boot_id', active)
            proc = Path('/proc/sys/kernel/random/boot_id')
            self.assertEqual(active['boot_id'], proc.read_text().strip() if proc.exists() else None)
        finally:
            lease.close(clean=True)
        self.assertEqual(json.loads(self.file.read_text())['boot_id'], active['boot_id'])


if __name__ == '__main__':
    unittest.main()
