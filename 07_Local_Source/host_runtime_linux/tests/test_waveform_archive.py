import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cabinet.service import Service
from cabinet.store import Store
from cabinet.waveform import WaveformReader, checksum, validate_record


class WaveRegisters:
    def __init__(self, before=2, after=2, event=1, test=False):
        self.cookie = 7
        self.header = [0] * 43
        self.header[:8] = [0x57415631, 0x10000, 4 | (32 if test else 0), event, 0, 4000, before, after]
        self.header[18:24] = [before + after, before + after, before, before, after, after]
        self.header[38] = 100000000
        self.header[42] = int(test)
        self.index = 0
        self.transactions = []
        self.released = []
        self.uncertain = False

    def read(self, address):
        self.transactions.append(('read', address))
        if address == 0x1050:
            return self.cookie
        if address == 0x20c4:
            sensor, point, word = self.index >> 31, (self.index >> 3) & 1023, self.index & 7
            return self.sample(sensor, point)[word]
        if 0x2000 <= address <= 0x20a8:
            return self.header[(address - 0x2000) // 4]
        raise ValueError('Unexpected access: ' + hex(address))

    def sample(self, sensor, point):
        return [0xffff8000 + sensor, 0xffff8000 + point, point * 25000, sensor, point & 15]

    def write(self, address, value):
        self.transactions.append(('write', address, value))
        if address == 0x20c0:
            self.index = value
        elif address == 0x20b8:
            if not self.header[2] & 4 or value != self.header[3]:
                raise ValueError('Wrong release')
            self.released.append(value)
            self.header[2] &= ~4
            if self.uncertain:
                raise OSError('Transport acknowledgement lost after applying release')
        else:
            raise ValueError('Forbidden WAV1 command')


def capture(registers, reader=None):
    reader = reader or WaveformReader()
    records = []
    for unused in range(10000):
        reader.poll(registers, 'device/7', registers.cookie, lambda token, record: records.append((token, copy.deepcopy(record))) or True)
        if records or reader.phase == 'FAULT':
            return reader, records
    raise AssertionError('Reader did not reach persistence')


class WaveformTests(unittest.TestCase):
    def test_default_maximum_zero_sided_and_test_records_preserve_every_word(self):
        for before, after in ((2, 3), (128, 128), (512, 512), (0, 1), (1, 0), (1024, 0)):
            for test in (False, True):
                registers = WaveRegisters(before, after, test=test)
                reader, records = capture(registers)
                self.assertEqual(reader.phase, 'PERSISTING')
                self.assertEqual(len(records), 1)
                token, record = records[0]
                self.assertEqual(token, ('device/7', 1, checksum(record)))
                self.assertEqual(record['test'], test)
                self.assertFalse(record['qualified'])
                for sensor in range(2):
                    self.assertEqual(record['samples'][sensor], [registers.sample(sensor, point) for point in range(before + after)])
                self.assertEqual(registers.released, [])

    def test_each_poll_has_a_hard_transaction_limit(self):
        for budget in (5, 17, 64, 256):
            registers = WaveRegisters()
            reader = WaveformReader(budget, 10)
            for unused in range(500):
                before = len(registers.transactions)
                reader.poll(registers, 'device/7', 7, lambda *unused: True)
                self.assertLessEqual(len(registers.transactions) - before, budget)
                if reader.phase == 'PERSISTING':
                    break
            self.assertEqual(reader.phase, 'PERSISTING')

    def test_queue_backpressure_and_slow_persistence_never_release(self):
        registers = WaveRegisters()
        reader, records = capture(registers)
        for unused in range(100):
            reader.poll(registers, 'device/7', 7, lambda *unused: self.fail('Double enqueue'))
        self.assertEqual(registers.released, [])
        reader.result(records[0][0], 'disk full')
        reader.retry_at = 0
        reader.poll(registers, 'device/7', 7, lambda *unused: False)
        self.assertFalse(reader.queued)
        reader.poll(registers, 'device/7', 7, lambda *unused: True)
        self.assertTrue(reader.queued)
        self.assertEqual(registers.released, [])

    def test_only_exact_durable_receipt_releases_and_uncertain_write_is_not_repeated(self):
        registers = WaveRegisters(event=0xffffffff)
        reader, records = capture(registers)
        token = records[0][0]
        reader.result(('other_boot', token[1], token[2]))
        reader.poll(registers, 'device/7', 7, lambda *unused: True)
        self.assertEqual(registers.released, [])
        reader.result(token)
        registers.uncertain = True
        reader.poll(registers, 'device/7', 7, lambda *unused: True)
        reader.poll(registers, 'device/7', 7, lambda *unused: True)
        self.assertEqual(registers.released, [0xffffffff])
        self.assertEqual(reader.phase, 'IDLE')
        self.assertEqual(reader.completed, 1)

    def test_minimum_transaction_budget_can_complete_release(self):
        registers = WaveRegisters()
        reader, records = capture(registers, WaveformReader(5, 10))
        reader.result(records[0][0])
        reader.poll(registers, 'device/7', 7, lambda *unused: False)
        reader.poll(registers, 'device/7', 7, lambda *unused: False)
        self.assertEqual(registers.released, [1])
        self.assertEqual(reader.phase, 'IDLE')

    def test_next_event_is_read_without_releasing_it_with_an_old_receipt(self):
        registers = WaveRegisters()
        reader, records = capture(registers)
        reader.result(records[0][0])
        reader.poll(registers, 'device/7', 7, lambda *unused: True)
        registers.header[3] = 2
        registers.header[2] |= 4
        reader.poll(registers, 'device/7', 7, lambda *unused: True)
        reader.result(records[0][0])
        self.assertEqual(registers.released, [1])
        self.assertNotEqual(reader.phase, 'RELEASE')

    def test_observed_pl_reset_and_changed_event_prevent_release(self):
        for change in ('cookie', 'event'):
            registers = WaveRegisters()
            reader, records = capture(registers)
            reader.result(records[0][0])
            if change == 'cookie':
                registers.cookie = 8
            else:
                registers.header[3] = 2
            reader.poll(registers, 'device/7', 7, lambda *unused: True)
            self.assertEqual(reader.phase, 'FAULT')
            self.assertEqual(registers.released, [])

    def test_reconnect_rejects_a_late_receipt_from_the_previous_boot(self):
        registers = WaveRegisters()
        reader, records = capture(registers)
        registers.cookie = 8
        reader.poll(registers, 'device/8', 8, lambda *unused: True)
        reader.result(records[0][0])
        self.assertEqual(registers.released, [])
        self.assertNotEqual(reader.phase, 'RELEASE')

    def test_malformed_headers_and_unknown_sample_bits_hold_ready(self):
        for index, value in ((0, 0), (1, 2), (18, 1025), (20, 999), (42, 1), (8, 1 << 16), (38, 0)):
            registers = WaveRegisters()
            registers.header[index] = value
            reader, records = capture(registers)
            self.assertEqual(reader.phase, 'FAULT', (index, reader.snapshot()))
            self.assertEqual(records, [])
            self.assertEqual(registers.released, [])
        registers = WaveRegisters()
        registers.sample = lambda *unused: [1, 2, 3, 4, 16]
        reader, records = capture(registers)
        self.assertEqual(reader.phase, 'FAULT')
        self.assertEqual(records, [])

    def test_changed_frozen_header_is_rejected_but_dropped_counter_can_advance(self):
        for index in (4, 9):
            registers = WaveRegisters()
            reader = WaveformReader()
            records = []
            for unused in range(100):
                if reader.phase == 'DATA':
                    registers.header[index] += 1
                    break
                reader.poll(registers, 'device/7', 7, lambda *unused: True)
            for unused in range(100):
                reader.poll(registers, 'device/7', 7, lambda token, record: records.append(record) or True)
                if reader.phase in ('FAULT', 'PERSISTING'):
                    break
            self.assertEqual(reader.phase, 'PERSISTING' if index == 4 else 'FAULT')

    def test_committed_record_is_idempotent_after_service_restart(self):
        registers = WaveRegisters()
        reader, records = capture(registers)
        token, record = records[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.sqlite'
            store = Store(path)
            self.assertEqual(store.waveform(token[2], record), token[2])
            store.close()
            store = Store(path)
            try:
                self.assertEqual(store.waveform(token[2], record), token[2])
                self.assertEqual(store.db.execute('SELECT count(*) FROM waveforms').fetchone()[0], 1)
                stored = store.db.execute('SELECT payload FROM waveforms').fetchone()[0]
                self.assertEqual(json.loads(stored), record)
            finally:
                store.close()

    def test_disk_failure_capacity_and_corruption_do_not_issue_durable_receipts(self):
        unused, records = capture(WaveRegisters())
        token, record = records[0]
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / 'events.sqlite', dict(min_free_bytes=2**62))
            try:
                with self.assertRaises(OSError):
                    store.waveform(token[2], record)
                self.assertEqual(store.db.execute('SELECT count(*) FROM waveforms').fetchone()[0], 0)
                store.storage_policy['min_free_bytes'] = 1
                store.storage_policy['max_waveforms'] = 1
                store.waveform(token[2], record)
                store.waveform(token[2], record)
                another = copy.deepcopy(record)
                another['event_id'] = another['header'][3] = 2
                with self.assertRaises(OSError):
                    store.waveform(checksum(another), another)
                store.db.execute('UPDATE waveforms SET payload=?', ('{}',))
                store.db.commit()
                with self.assertRaises(ValueError):
                    store.waveform(token[2], record)
            finally:
                store.close()

    def test_service_journal_receipt_precedes_the_hardware_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = json.loads((Path(__file__).resolve().parents[1] / 'config.example.json').read_text())
            config.update(database=str(Path(temporary) / 'events.sqlite'),
                          waveform=dict(enabled=True, reviewed_abi=0x10000))
            registers = WaveRegisters()
            controller = type('Controller', (), dict(io=registers, boot_cookie=7, close=lambda self: None))()
            service = Service(config, mock=True, controller=controller)
            service.boot = 'device/7'
            try:
                for unused in range(100):
                    service.poll_waveform()
                    if not service.journal.empty():
                        break
                self.assertEqual(registers.released, [])
                worker = threading.Thread(target=service.journal_loop)
                worker.start()
                for unused in range(100):
                    service.poll_waveform()
                    if registers.released:
                        break
                    time.sleep(0.005)
                self.assertEqual(registers.released, [1])
                self.assertEqual(service.store.db.execute('SELECT count(*) FROM waveforms').fetchone()[0], 1)
            finally:
                service.stop.set()
                if 'worker' in locals():
                    worker.join(2)
                service.store.close()

    def test_optional_page_is_never_probed_without_explicit_enable(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = json.loads((Path(__file__).resolve().parents[1] / 'config.example.json').read_text())
            config['database'] = str(Path(temporary) / 'events.sqlite')
            registers = WaveRegisters()
            controller = type('Controller', (), dict(io=registers))()
            service = Service(config, mock=True, controller=controller)
            try:
                service.poll_waveform()
                self.assertEqual(registers.transactions, [])
            finally:
                service.store.close()

    def test_service_disk_failure_retries_without_premature_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = json.loads((Path(__file__).resolve().parents[1] / 'config.example.json').read_text())
            config.update(database=str(Path(temporary) / 'events.sqlite'),
                          waveform=dict(enabled=True, reviewed_abi=0x10000))
            registers = WaveRegisters()
            controller = type('Controller', (), dict(io=registers, boot_cookie=7))()
            service = Service(config, mock=True, controller=controller)
            service.boot = 'device/7'
            original = service.store.waveform
            calls = []

            def fail_once(identity, record):
                calls.append(identity)
                if len(calls) == 1:
                    raise OSError('Injected disk full')
                return original(identity, record)

            worker = threading.Thread(target=service.journal_loop)
            try:
                with patch.object(service.store, 'waveform', side_effect=fail_once):
                    worker.start()
                    for unused in range(300):
                        service.poll_waveform()
                        if service.wave_reader.error:
                            break
                        time.sleep(0.002)
                    self.assertIn('persistence pending', service.wave_reader.error)
                    self.assertEqual(registers.released, [])
                    service.wave_reader.retry_at = 0
                    for unused in range(300):
                        service.poll_waveform()
                        if registers.released:
                            break
                        time.sleep(0.002)
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(registers.released, [1])
            finally:
                service.stop.set()
                worker.join(2)
                service.store.close()

    def test_snapshot_coalescing_keeps_alarm_transitions_immediate(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = json.loads((Path(__file__).resolve().parents[1] / 'config.example.json').read_text())
            config['database'] = str(Path(temporary) / 'events.sqlite')
            service = Service(config, mock=True)
            try:
                state = dict(link='ONLINE', status=dict(active=[], latched=[], alarm_level=0))
                with patch.object(service.store, 'snapshot', wraps=service.store.snapshot) as write:
                    for tick in range(100):
                        with patch('cabinet.service.time.monotonic', return_value=tick * 0.128):
                            service.persist_status(state)
                    self.assertEqual(write.call_count, 13)
                    state['status']['active'] = ['OC_HARD']
                    with patch('cabinet.service.time.monotonic', return_value=12.673):
                        service.persist_status(state)
                    self.assertEqual(write.call_count, 14)
                self.assertEqual(service.store.get_snapshot(config['device_id'])['status']['active'], ['OC_HARD'])
            finally:
                service.store.close()

    def test_invalid_policy_and_forged_record_are_rejected(self):
        for transactions, milliseconds in ((True, 2), (4, 2), (257, 2), (64, float('nan')), (64, True)):
            with self.assertRaises(ValueError):
                WaveformReader(transactions, milliseconds)
        unused, records = capture(WaveRegisters())
        record = copy.deepcopy(records[0][1])
        record['qualified'] = True
        with self.assertRaises(ValueError):
            validate_record(record)
