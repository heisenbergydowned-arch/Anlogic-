import time


BASE = 0x3100
MAGIC = 0x49434d31
ABI = 0x00020000
WORDS = 36
MASK64 = (1 << 64) - 1


def signed16(value):
    value &= 0xffff
    return value - 0x10000 if value & 0x8000 else value


def age_diagnostics(document, now=None, offline=False):
    if not document:
        return dict(state='DISABLED', qualified=False, sensors=[])
    result = dict(document)
    stamp = result.pop('_monotonic', None)
    age = None if stamp is None else max(0, round(((time.monotonic() if now is None else now) - stamp) * 1000))
    result['snapshot_age_ms'] = age
    result['qualified'] = False
    result['sensors'] = [dict(sensor) for sensor in document.get('sensors', [])]
    if offline or age is None or age > 1500:
        if document.get('state') == 'DIAGNOSTIC_ONLY':
            result['state'] = 'OFFLINE' if offline else 'STALE'
        for sensor in result['sensors']:
            sensor.update(raw=None, fresh=False, observed_rate_hz=None, rate_matches_4khz=None)
    return result


class IcmDiagnostics:
    def __init__(self, policy):
        if type(policy) is not dict or set(policy) - {'enabled', 'reviewed_abi'}:
            raise ValueError('Unknown ICM1 policy')
        if type(policy.get('enabled', False)) is not bool:
            raise ValueError('ICM1 enabled must be boolean')
        self.enabled = policy.get('enabled', False)
        if self.enabled and (type(policy.get('reviewed_abi')) is not int or policy['reviewed_abi'] != ABI):
            raise ValueError('Explicit reviewed ICM1 ABI required')
        self.boot = None
        self.previous = None
        self.updated = None
        self.document = None

    def poll(self, registers, boot, cookie, now=None):
        now = time.monotonic() if now is None else now
        if not self.enabled:
            return dict(state='DISABLED', qualified=False, sensors=[])
        if boot != self.boot:
            self.boot = boot
            self.previous = self.updated = self.document = None
        if self.updated is not None and now - self.updated < 0.5:
            return self.document
        self.updated = now
        try:
            def read(address):
                value = registers.read(address)
                if type(value) is not int or not 0 <= value <= 0xffffffff:
                    raise ValueError('ICM1 response is not uint32')
                return value
            if read(0x1050) != cookie:
                raise ValueError('PL reset before ICM1 snapshot')
            words = [read(BASE)]
            if words[0] != MAGIC:
                raise ValueError('ICM1 signature unavailable')
            words.extend(read(BASE + index * 4) for index in range(1, WORDS))
            if read(BASE + 8) != words[2] or read(0x1050) != cookie:
                raise ValueError('ICM1 snapshot ownership or PL boot changed')
            if words[1] != ABI or words[6:10] != [100000000, 8000, 3125000, 500000] or words[34:] != [45, 1000000]:
                raise ValueError('ICM1 ABI, clocks or release mismatch')
            if words[3] & ~15 or words[15] & 0xffff0000 or words[16] & 0xfc00fc00:
                raise ValueError('ICM1 reserved bits are not zero')
            cycles = words[4] | (words[5] << 32)
            test = bool(words[3] & 8)
            elapsed = None if self.previous is None else (cycles - self.previous['cycles']) & MASK64
            if self.previous is not None and (elapsed == 0 or elapsed > 200000000):
                elapsed = None
            sensors = []
            for sensor in range(2):
                shift = sensor * 16
                count = (words[11] >> shift) & 0xffff
                last = words[28 + sensor * 2] | (words[29 + sensor * 2] << 32)
                sample_age = ((cycles - last) & MASK64) / 100000 if last else None
                error = bool(words[3] & (1 << sensor))
                mask = (words[16] >> shift) & 0x3ff
                who = (words[15] >> (sensor * 8)) & 0xff
                offset = 20 + sensor * 4
                raw = [signed16(words[offset]), signed16(words[offset] >> 16), signed16(words[offset + 1])]
                rate = None
                if elapsed is not None and sample_age is not None and not test:
                    delta = (count - self.previous['counts'][sensor]) & 0xffff
                    if delta <= elapsed * 8000 / 100000000 + 1:
                        rate = round(delta * 100000000 / elapsed, 2)
                failure = words[32 + sensor]
                sensors.append(dict(channel='AB'[sensor], who=who, error=error, config_bad_mask=mask,
                    config_verified=not error and mask == 0 and who in (0x12, 0x2e),
                    config_failure=dict(address=(failure >> 16) & 0xff, expected=(failure >> 8) & 0xff, actual=failure & 0xff),
                    sequence=(words[10] >> shift) & 0xffff, valid_count=count,
                    drdy_zero_count=(words[12] >> shift) & 0xffff,
                    watchdog_count=(words[13] >> (sensor * 8)) & 0xff,
                    duplicate_count=(words[14] >> shift) & 0xffff,
                    interrupt_status=(words[18] >> (sensor * 8)) & 0xff,
                    retry_count=(words[19] >> shift) & 0xffff,
                    raw=raw if last and not test else None, sample_age_ms=sample_age,
                    fresh=not test and not error and mask == 0 and sample_age is not None and sample_age <= 100,
                    observed_rate_hz=rate, rate_matches_4khz=None if rate is None else abs(rate - 4000) <= 120))
            self.previous = dict(cycles=cycles, counts=[sensor['valid_count'] for sensor in sensors])
            self.document = dict(state='DIAGNOSTIC_ONLY', qualified=False, boot_id=boot, snapshot_id=words[2],
                core_hz=words[6], poll_hz=words[7], burst_spi_hz=words[8], register_spi_hz=words[9],
                status_spi_hz=words[35],test=test, init_done=bool(words[3] & 4), driver_state=words[17], sensors=sensors,
                _monotonic=now)
        except Exception as error:
            self.previous = None
            self.document = dict(state='UNAVAILABLE', qualified=False, sensors=[], error=str(error), _monotonic=now)
        return self.document
