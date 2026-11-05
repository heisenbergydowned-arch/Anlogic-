"""Shared ENV1 auxiliary telemetry. Never substitutes any of the 39 PL features."""
import math
import struct
import time


ENVIRONMENT_CAPABILITY = 1 << 31
MAX_AGE_MS = 2500
HARDWARE_PROFILE = 'AHT20_ONLY_V1'
INSTALLED_ENVIRONMENT_SENSORS = ('AHT20',)


def _installed_state(value):
    """Product inventory; keep legacy ENV1 BMP diagnostics unchanged.

    The actual cabinet has AHT20 ambient sensing and SDP810 duct differential
    pressure. BMP280 is not installed. Raw PL status/faults and 39 features are
    never rewritten here; old firmware can still report its legacy AUX_LOSS.
    """
    result = dict(value)
    result['hardware_profile'] = HARDWARE_PROFILE
    result['installed_environment_sensors'] = list(INSTALLED_ENVIRONMENT_SENSORS)
    result['legacy_uninstalled_sensors'] = ['BMP280']
    result['raw_environment_state'] = value['state']
    if value['state'] in ('VALID', 'DEGRADED'):
        result['raw_environment_state'] = ('VALID' if value.get('aht_valid') is True and
                                           value.get('bmp_valid') is True else 'DEGRADED')
        result['state'] = 'VALID' if value.get('aht_valid') is True else 'DEGRADED'
    return result


def unavailable(reason):
    return _installed_state(dict(state=reason, aht_valid=False, bmp_valid=False, inlet_temperature_c=None,
                relative_humidity_pct=None, ambient_pressure_hpa=None, bmp_temperature_c=None,
                inlet_source='AHT20', core_source='DS18B20/S4b', pressure_source='BMP280'))


def compensate_bmp280(temperature, pressure, calibration):
    if len(calibration) != 24 or calibration in (bytes(24), bytes([255]) * 24):
        raise ValueError('BMP_CALIBRATION')
    if any(type(value) is not int or not 0 <= value < 1048576 or value == 0x80000
           for value in (temperature, pressure)):
        raise ValueError('BMP_RAW')
    t1, t2, t3, p1, p2, p3, p4, p5, p6, p7, p8, p9 = struct.unpack('<HhhHhhhhhhhh', calibration)
    if p1 in (0, 65535):
        raise ValueError('BMP_CALIBRATION')
    first = (temperature / 16384.0 - t1 / 1024.0) * t2
    second = (temperature / 131072.0 - t1 / 8192.0) ** 2 * t3
    fine = first + second
    temperature_c = fine / 5120.0
    first = fine / 2.0 - 64000.0
    second = first * first * p6 / 32768.0 + first * p5 * 2.0
    second = second / 4.0 + p4 * 65536.0
    first = (p3 * first * first / 524288.0 + p2 * first) / 524288.0
    first = (1.0 + first / 32768.0) * p1
    if first == 0:
        raise ValueError('BMP_DIVISOR')
    pressure_pa = ((1048576.0 - pressure) - second / 4096.0) * 6250.0 / first
    first = p9 * pressure_pa * pressure_pa / 2147483648.0
    second = pressure_pa * p8 / 32768.0
    pressure_pa += (first + second + p7) / 16.0
    if not math.isfinite(temperature_c) or not -40 <= temperature_c <= 85:
        raise ValueError('BMP_TEMPERATURE_RANGE')
    if not math.isfinite(pressure_pa) or not 30000 <= pressure_pa <= 110000:
        raise ValueError('BMP_PRESSURE_RANGE')
    return temperature_c, pressure_pa / 100.0


def decode_environment(words, now_ms):
    result = unavailable('INVALID_ENV1')
    if len(words) != 20 or any(type(value) is not int or not 0 <= value <= 0xffffffff for value in words):
        return result
    if words[0] != 0x454e5631 or words[1] != 0x10000 or words[19] != 2:
        return result
    snapshot_age = (now_ms - words[3]) & 0xffffffff
    if snapshot_age > MAX_AGE_MS:
        return unavailable('STALE_ENV1')
    flags = words[4]
    result.update(state='DEGRADED', snapshot_id=words[2], sampled_at_ms=words[3],
                  aht_age_ms=words[5], bmp_age_ms=words[6], aht_samples=words[17], bmp_samples=words[18])
    if flags & 0x1d == 0x05 and words[5] + snapshot_age <= MAX_AGE_MS and words[17] != 0:
        humidity, temperature = words[7:9]
        if 0 <= humidity < 1048576 and 0 <= temperature < 1048576:
            inlet = temperature * 200.0 / 1048576.0 - 50.0
            if -40 <= inlet <= 85:
                result.update(aht_valid=True, inlet_temperature_c=inlet,
                              relative_humidity_pct=humidity * 100.0 / 1048576.0)
    if flags & 0xe2 == 0x22 and words[6] + snapshot_age <= MAX_AGE_MS and words[18] != 0:
        try:
            temperature, pressure = compensate_bmp280(words[9], words[10], struct.pack('<6I', *words[11:17]))
            result.update(bmp_valid=True, bmp_temperature_c=temperature, ambient_pressure_hpa=pressure)
        except ValueError:
            pass
    return _installed_state(result)


def read_environment(registers, mailbox):
    if not mailbox.get('capabilities', 0) & ENVIRONMENT_CAPABILITY:
        return unavailable('FIRMWARE_UNAVAILABLE')
    started = time.monotonic()
    magic = registers.read(0x3000)
    words = [magic] + [registers.read(0x3000 + index * 4) for index in range(1, 20)]
    if registers.read(0x3008) != words[2]:
        return unavailable('INCOHERENT_ENV1')
    elapsed_ms = (time.monotonic() - started) * 1000
    if not 0 <= elapsed_ms <= 200:
        return unavailable('STALE_ENV1')
    result = age_environment(decode_environment(words, words[3]), elapsed_ms)
    result['read_latency_ms'] = round(elapsed_ms, 3)
    return result


def age_environment(value, elapsed_ms):
    if value is None:
        return unavailable('FIRMWARE_UNAVAILABLE')
    result = dict(value)
    if not math.isfinite(elapsed_ms) or elapsed_ms < 0:
        return unavailable('STALE_ENV1')
    for sensor, fields in [('aht', ('inlet_temperature_c', 'relative_humidity_pct')),
                           ('bmp', ('ambient_pressure_hpa', 'bmp_temperature_c'))]:
        age = value.get(sensor + '_age_ms', MAX_AGE_MS + 1) + math.ceil(elapsed_ms)
        result[sensor + '_age_ms'] = age
        if age > MAX_AGE_MS:
            result[sensor + '_valid'] = False
            for field in fields:
                result[field] = None
    return _installed_state(result)


def display_fields(value):
    value = _installed_state(value) if value else unavailable('FIRMWARE_UNAVAILABLE')
    result = dict(environment_state=value['state'], inlet_source='AHT20',
                  environment_hardware_profile=HARDWARE_PROFILE,
                  environment_installed_sensors='AHT20')
    published = int(time.clock_gettime(time.CLOCK_MONOTONIC) * 1000)
    for sensor in ('aht',):
        remaining = max(0, MAX_AGE_MS - value.get(sensor + '_age_ms', MAX_AGE_MS + 1))
        result['environment_' + sensor + '_deadline_ms'] = str(published + remaining if value.get(sensor + '_valid') else 0)
    for field, valid, precision in [('inlet_temperature_c', 'aht_valid', 1),
                                    ('relative_humidity_pct', 'aht_valid', 1)]:
        number = value.get(field)
        result[field] = ('%.*f' % (precision, number)
                         if value.get(valid) and isinstance(number, (int, float)) and math.isfinite(number) else '--')
    return result
