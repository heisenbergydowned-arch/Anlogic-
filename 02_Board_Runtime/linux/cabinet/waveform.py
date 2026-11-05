"""Bounded WAV1 ownership; only the hardware thread may touch INDEX/DATA/RELEASE."""
import hashlib
import json
import time


MAGIC = 0x57415631
ABI = 0x10000
BASE = 0x2000
HEADER_WORDS = 43


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def checksum(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def frozen_header(header):
    return tuple(value for index, value in enumerate(header) if index not in (2, 4))


def validate_header(header):
    if len(header) != HEADER_WORDS or any(type(value) is not int or not 0 <= value <= 0xffffffff for value in header):
        raise ValueError('WAV1 requires 43 uint32 header words')
    if header[:2] != [MAGIC, ABI] or not header[2] & 4 or header[2] & ~0x3f:
        raise ValueError('WAV1 identity or READY state mismatch')
    if header[42] not in (0, 1) or bool(header[2] & 32) != bool(header[42]):
        raise ValueError('WAV1 TEST identity mismatch')
    depth = header[6] + header[7]
    if not 1 <= depth <= 1024 or not 1 <= header[5] <= header[38] or header[8] & ~0xffff:
        raise ValueError('WAV1 capacity, clock or quality mismatch')
    for count, before, after in ((header[18], header[20], header[22]), (header[19], header[21], header[23])):
        if count != before + after or before > header[6] or after > header[7] or count > depth:
            raise ValueError('WAV1 sample counts mismatch')
    return header


def validate_record(record):
    if type(record) is not dict or set(record) != {'schema', 'boot_id', 'event_id', 'header', 'samples', 'test', 'qualified'}:
        raise ValueError('Invalid WAV1 archive schema')
    if record['schema'] != 'cabinet-waveform-v1' or type(record['boot_id']) is not str or not 1 <= len(record['boot_id']) <= 256:
        raise ValueError('Invalid WAV1 archive identity')
    header = validate_header(record['header'])
    if type(record['event_id']) is not int or record['event_id'] != header[3] or record['qualified'] is not False:
        raise ValueError('Invalid WAV1 event or qualification')
    if type(record['test']) is not bool or record['test'] != bool(header[42]):
        raise ValueError('WAV1 archive TEST mismatch')
    if type(record['samples']) is not list or len(record['samples']) != 2:
        raise ValueError('WAV1 needs independent A/B arrays')
    for sensor, rows in enumerate(record['samples']):
        if type(rows) is not list or len(rows) != header[18 + sensor]:
            raise ValueError('WAV1 archive count mismatch')
        for row in rows:
            if type(row) is not list or len(row) != 5 or any(type(value) is not int or not 0 <= value <= 0xffffffff for value in row):
                raise ValueError('WAV1 raw record must contain five uint32 words')
            if row[4] & ~15:
                raise ValueError('Unknown WAV1 sample quality/reserved bits')
    return record


class WaveformReader:
    def __init__(self, transactions=64, budget_ms=2):
        if type(transactions) is not int or not 5 <= transactions <= 256:
            raise ValueError('WAV1 transaction budget must be 5..256')
        if type(budget_ms) not in (int, float) or not 0.1 <= budget_ms <= 10:
            raise ValueError('WAV1 wall budget must be 0.1..10ms')
        self.transactions, self.budget_s = transactions, budget_ms / 1000
        self.reset(None)

    def reset(self, boot):
        self.boot = boot
        self.phase = 'IDLE'
        self.header = []
        self.samples = [[], []]
        self.sensor = self.point = self.word = 0
        self.index_written = False
        self.record = self.token = None
        self.queued = False
        self.retry_at = 0
        self.error = None
        self.completed = 0

    def result(self, token, error=None):
        if token != self.token or self.phase != 'PERSISTING':
            return
        if error is None:
            self.phase = 'RELEASE'
            self.error = None
        else:
            self.queued = False
            self.retry_at = time.monotonic() + 1
            self.error = 'WAV1 persistence pending: ' + str(error)

    def snapshot(self):
        return dict(state=self.phase, event_id=self.header[3] if len(self.header) > 3 else None,
                    error=self.error, completed=self.completed, qualified=False)

    def poll(self, registers, boot, cookie, submit):
        if boot != self.boot:
            self.reset(boot)
        if self.phase == 'FAULT':
            return self.snapshot()
        try:
            self._poll(registers, cookie, submit)
        except Exception as error:
            self.phase = 'FAULT'
            self.error = type(error).__name__ + ': ' + str(error)
        return self.snapshot()

    def _poll(self, registers, cookie, submit):
        started = time.monotonic()
        remaining = self.transactions

        def read(address):
            nonlocal remaining
            remaining -= 1
            value = registers.read(address)
            if type(value) is not int or not 0 <= value <= 0xffffffff:
                raise ValueError('WAV1 MMIO returned a non-uint32 value')
            return value

        def write(address, value):
            nonlocal remaining
            remaining -= 1
            registers.write(address, value)

        def available(cost=1):
            return remaining >= cost and time.monotonic() - started < self.budget_s

        if read(0x1050) != cookie:
            raise RuntimeError('PL boot changed during WAV1 transfer')
        status = read(BASE + 8)
        if not status & 4:
            if self.phase == 'VERIFY_RELEASE':
                self.completed += 1
                self.phase = 'IDLE'
                self.header = []
                self.record = self.token = None
                self.error = None
            elif self.phase != 'IDLE':
                raise RuntimeError('WAV1 READY disappeared before durable release')
            return
        event = read(BASE + 12)
        if self.phase == 'VERIFY_RELEASE':
            if event != self.header[3]:
                self.completed += 1
                self.phase = 'IDLE'
                self.header = []
                self.record = self.token = None
            else:
                self.phase = 'RELEASE'
        if self.phase == 'IDLE':
            self.header = []
            self.samples = [[], []]
            self.sensor = self.point = self.word = 0
            self.index_written = False
            self.phase = 'HEADER'
        elif len(self.header) > 3 and event != self.header[3]:
            raise RuntimeError('WAV1 event ownership changed')
        if self.phase == 'HEADER':
            while len(self.header) < HEADER_WORDS and available():
                self.header.append(read(BASE + len(self.header) * 4))
            if len(self.header) < HEADER_WORDS:
                return
            validate_header(self.header)
            self.phase = 'DATA'
        if self.phase == 'DATA':
            while self.sensor < 2 and available():
                if self.point >= self.header[18 + self.sensor]:
                    self.sensor += 1
                    self.point = self.word = 0
                    self.index_written = False
                    continue
                if not self.index_written:
                    write(BASE + 0xc0, (self.sensor << 31) | (self.point << 3) | self.word)
                    self.index_written = True
                elif available():
                    value = read(BASE + 0xc4)
                    if self.word == 0:
                        self.samples[self.sensor].append([])
                    self.samples[self.sensor][-1].append(value)
                    self.word += 1
                    self.index_written = False
                    if self.word == 5:
                        self.point += 1
                        self.word = 0
            if self.sensor < 2:
                return
            self.final_header = []
            self.phase = 'CHECK'
        if self.phase == 'CHECK':
            while len(self.final_header) < HEADER_WORDS and available():
                self.final_header.append(read(BASE + len(self.final_header) * 4))
            if len(self.final_header) < HEADER_WORDS:
                return
            validate_header(self.final_header)
            if frozen_header(self.final_header) != frozen_header(self.header):
                raise RuntimeError('WAV1 frozen header changed while reading')
            self.record = validate_record(dict(schema='cabinet-waveform-v1', boot_id=self.boot,
                event_id=self.header[3], header=self.header, samples=self.samples,
                test=bool(self.header[42]), qualified=False))
            self.token = (self.boot, self.header[3], checksum(self.record))
            self.queued = False
            self.phase = 'PERSISTING'
        if self.phase == 'PERSISTING':
            if not self.queued and time.monotonic() >= self.retry_at:
                self.queued = bool(submit(self.token, self.record))
            return
        if self.phase == 'RELEASE' and available(2):
            if read(0x1050) != cookie:
                raise RuntimeError('PL boot changed before WAV1 release')
            self.phase = 'VERIFY_RELEASE'
            try:
                write(BASE + 0xb8, self.header[3])
            except Exception as error:
                self.error = 'WAV1 release acknowledgement uncertain: ' + str(error)
