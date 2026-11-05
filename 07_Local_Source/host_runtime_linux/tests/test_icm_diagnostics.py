import copy
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cabinet.icm_diagnostics import ABI, BASE, MAGIC, IcmDiagnostics, age_diagnostics
from cabinet.web import server


class Registers:
    def __init__(self):
        self.cookie = 7
        self.reads = []
        self.ownership_change = False
        self.reset_after = False
        self.words = [0] * 36
        self.words[:4] = [MAGIC, ABI, 1, 4]
        self.words[4] = 100000000
        self.words[6:10] = [100000000, 8000, 3125000, 500000]
        self.words[10] = self.words[11] = 100 | (200 << 16)
        self.words[15] = 0x122e
        self.words[20:22] = [0x7fff8000, 0x1111ffff]
        self.words[24:26] = [0xfffe0002, 0x22220003]
        self.words[28] = self.words[30] = 99975000
        self.words[34] = 45
        self.words[35] = 1000000

    def read(self, address):
        self.reads.append(address)
        if address == 0x1050:
            return self.cookie + int(self.reset_after and len(self.reads) > 2)
        if address == BASE + 8 and self.ownership_change and self.reads.count(BASE + 8) > 1:
            return self.words[2] + 1
        if BASE <= address < BASE + 144:
            return self.words[(address - BASE) // 4]
        raise ValueError('Unknown read')

    def write(self, *unused):
        raise AssertionError('Diagnostic reader must never write MMIO')

    def advance(self, count_a=2000, count_b=2000, cycles=50000000):
        self.words[2] += 1
        self.words[4] += cycles
        self.words[11] = ((self.words[11] + count_a) & 0xffff) | (((self.words[11] >> 16) + count_b) & 0xffff) << 16
        self.words[28] = self.words[30] = self.words[4] - 25000


class IcmTests(unittest.TestCase):
    def reader(self):
        return IcmDiagnostics(dict(enabled=True, reviewed_abi=ABI))

    def test_default_disabled_never_touches_legacy_firmware(self):
        registers = Registers()
        self.assertEqual(IcmDiagnostics({}).poll(registers, 'boot', 7)['state'], 'DISABLED')
        self.assertEqual(registers.reads, [])

    def test_policy_requires_explicit_review(self):
        for policy in [None, [], dict(enabled=1), dict(enabled=True), dict(enabled=True, reviewed_abi=True),
                       dict(enabled=True, reviewed_abi=2), dict(enabled=False, extra=True)]:
            with self.assertRaises(ValueError):
                IcmDiagnostics(policy)

    def test_both_raw_channels_without_a_feature_frame(self):
        document = self.reader().poll(Registers(), 'boot', 7, now=10)
        self.assertEqual(document['state'], 'DIAGNOSTIC_ONLY')
        self.assertFalse(document['qualified'])
        self.assertEqual(document['sensors'][0]['raw'], [-32768, 32767, -1])
        self.assertEqual(document['sensors'][1]['raw'], [2, -2, 3])
        self.assertEqual([sensor['who'] for sensor in document['sensors']], [46, 18])
        self.assertTrue(all(sensor['fresh'] and sensor['config_verified'] for sensor in document['sensors']))
        self.assertTrue(all(sensor['observed_rate_hz'] is None for sensor in document['sensors']))

    def test_read_budget_and_refresh_interval(self):
        registers, reader = Registers(), self.reader()
        reader.poll(registers, 'boot', 7, now=10)
        self.assertEqual(len(registers.reads), 39)
        reader.poll(registers, 'boot', 7, now=10.4)
        self.assertEqual(len(registers.reads), 39)
        reader.poll(registers, 'boot', 7, now=10.5)
        self.assertEqual(len(registers.reads), 78)

    def test_4khz_observation_is_not_qualification(self):
        registers, reader = Registers(), self.reader()
        reader.poll(registers, 'boot', 7, now=10)
        registers.advance()
        document = reader.poll(registers, 'boot', 7, now=10.5)
        self.assertEqual([sensor['observed_rate_hz'] for sensor in document['sensors']], [4000, 4000])
        self.assertTrue(all(sensor['rate_matches_4khz'] for sensor in document['sensors']))
        self.assertFalse(document['qualified'])

    def test_1khz_still_displays_raw_but_fails_nominal_rate(self):
        registers, reader = Registers(), self.reader()
        reader.poll(registers, 'boot', 7, now=10)
        registers.advance(500, 2000)
        document = reader.poll(registers, 'boot', 7, now=10.5)
        self.assertEqual(document['sensors'][0]['observed_rate_hz'], 1000)
        self.assertFalse(document['sensors'][0]['rate_matches_4khz'])
        self.assertIsNotNone(document['sensors'][0]['raw'])
        self.assertFalse(document['qualified'])

    def test_modulo_count_wrap(self):
        registers, reader = Registers(), self.reader()
        registers.words[11] = 65500 | (65500 << 16)
        reader.poll(registers, 'boot', 7, now=10)
        registers.advance()
        document = reader.poll(registers, 'boot', 7, now=10.5)
        self.assertEqual([sensor['observed_rate_hz'] for sensor in document['sensors']], [4000, 4000])

    def test_long_elapsed_cannot_invent_a_rate_from_wrapped_counters(self):
        registers, reader = Registers(), self.reader()
        reader.poll(registers, 'boot', 7, now=10)
        registers.advance(cycles=300000000)
        document = reader.poll(registers, 'boot', 7, now=13)
        self.assertTrue(all(sensor['observed_rate_hz'] is None for sensor in document['sensors']))

    def test_new_boot_drops_previous_rate(self):
        registers, reader = Registers(), self.reader()
        reader.poll(registers, 'boot', 7, now=10)
        registers.advance()
        document = reader.poll(registers, 'other', 7, now=10.5)
        self.assertTrue(all(sensor['observed_rate_hz'] is None for sensor in document['sensors']))

    def test_concurrent_snapshot_and_reset_fail_closed(self):
        for field in ['ownership_change', 'reset_after']:
            registers = Registers()
            setattr(registers, field, True)
            document = self.reader().poll(registers, 'boot', 7, now=10)
            self.assertEqual(document['state'], 'UNAVAILABLE')
            self.assertEqual(document['sensors'], [])

    def test_bad_signature_abi_clock_and_reserved_fields(self):
        for index, value in [(0, 0), (1, 2), (6, 25000000), (8, 6250000), (9, 1),
                             (15, 0x1000000), (16, 0x400), (34, 42), (35, 1), (3, 16)]:
            registers = Registers()
            registers.words[index] = value
            self.assertEqual(self.reader().poll(registers, 'boot', 7)['state'], 'UNAVAILABLE')

    def test_no_sample_or_test_data_never_presented_as_live_raw(self):
        for test in [False, True]:
            registers = Registers()
            registers.words[3] |= 8 if test else 0
            if not test:
                registers.words[28:32] = [0, 0, 0, 0]
            document = self.reader().poll(registers, 'boot', 7)
            self.assertTrue(all(sensor['raw'] is None and not sensor['fresh'] for sensor in document['sensors']))

    def test_configuration_failure_is_channel_specific(self):
        registers = Registers()
        registers.words[3] |= 2
        registers.words[16] = 4 << 16
        registers.words[33] = 0x6c0700
        document = self.reader().poll(registers, 'boot', 7)
        self.assertTrue(document['sensors'][0]['config_verified'])
        self.assertFalse(document['sensors'][1]['config_verified'])
        self.assertFalse(document['sensors'][1]['fresh'])
        self.assertEqual(document['sensors'][1]['config_failure'], dict(address=0x6c, expected=7, actual=0))

    def test_expired_and_offline_snapshots_remove_raw_without_mutation(self):
        document = self.reader().poll(Registers(), 'boot', 7, now=10)
        before = copy.deepcopy(document)
        for now, offline in [(12, False), (10.1, True)]:
            expired = age_diagnostics(document, now, offline)
            self.assertTrue(all(sensor['raw'] is None and not sensor['fresh'] for sensor in expired['sensors']))
            self.assertNotIn('_monotonic', expired)
        self.assertEqual(document, before)

    def test_mmio_transport_exception_is_diagnostic_not_control_command(self):
        class Broken:
            def read(self, address):
                raise OSError('read unavailable')
        document = self.reader().poll(Broken(), 'boot', 7)
        self.assertEqual(document['state'], 'UNAVAILABLE')

    def test_authenticated_status_and_readonly_diagnostics_page(self):
        class Service:
            def public_state(self):
                return dict(icm_diagnostics=dict(state='DIAGNOSTIC_ONLY', qualified=False), link='ONLINE')
        http = server('127.0.0.1', 0, Service(), token='test-token')
        worker = threading.Thread(target=http.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(http.server_address[1])
        try:
            with urlopen(base + '/diagnostics', timeout=2) as response:
                page = response.read().decode()
            self.assertIn('/api/status', page)
            self.assertNotIn('method:', page)
            self.assertNotIn('localStorage', page)
            with self.assertRaises(HTTPError) as denied:
                urlopen(base + '/api/status', timeout=2)
            self.assertEqual(denied.exception.code, 401)
            request = Request(base + '/api/status', headers={'Authorization': 'Bearer test-token'})
            with urlopen(request, timeout=2) as response:
                document = json.load(response)
            self.assertFalse(document['icm_diagnostics']['qualified'])
        finally:
            http.shutdown()
            http.server_close()
            worker.join(3)
