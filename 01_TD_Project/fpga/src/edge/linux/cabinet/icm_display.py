import math


def display_fields(document, now, received_at, boot, reject_test=False):
    result = dict(panel_icm_schema='ICM1_RAW_V1', panel_icm_a_deadline_ms='0',
                  panel_icm_b_deadline_ms='0', panel_icm_a_raw='A XYZ: --  --  --',
                  panel_icm_b_raw='B XYZ: --  --  --', panel_icm_a_info='A: unavailable',
                  panel_icm_b_info='B: unavailable', panel_icm_note='RAW COUNTS / UNCALIBRATED / NOT FFT OR g')
    if not isinstance(document, dict) or document.get('state') != 'DIAGNOSTIC_ONLY' or document.get('test') is not False or reject_test:
        return result
    source = document.get('boot_id')
    if not isinstance(source, str) or not boot.startswith(source + '/'):
        return result
    age = document.get('snapshot_age_ms')
    if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 1500:
        return result
    delay = (now - received_at) * 1000
    if not 0 <= delay <= 1000 or age + delay > 1500:
        return result
    sensors = document.get('sensors')
    if not isinstance(sensors, list) or len(sensors) != 2 or [sensor.get('channel') for sensor in sensors if isinstance(sensor, dict)] != ['A', 'B']:
        return result
    for sensor in sensors:
        channel = sensor['channel']
        prefix = 'panel_icm_' + channel.lower()
        who = sensor.get('who')
        if type(who) is not int or not 0 <= who <= 255:
            continue
        result[prefix + '_info'] = '%s WHO=%02X / NO FRESH VALID SAMPLE' % (channel, who)
        raw = sensor.get('raw')
        sample_age = sensor.get('sample_age_ms')
        if (sensor.get('fresh') is not True or sensor.get('error') is not False or sensor.get('config_verified') is not True or
                sensor.get('config_bad_mask') != 0 or who not in (0x12, 0x2e) or
                type(sample_age) not in (int, float) or not math.isfinite(sample_age) or not 0 <= sample_age <= 100 or
                not isinstance(raw, list) or len(raw) != 3 or any(type(value) is not int or not -32768 <= value <= 32767 for value in raw)):
            continue
        result[prefix + '_raw'] = '%s XYZ: %+6d %+6d %+6d' % (channel, raw[0], raw[1], raw[2])
        result[prefix + '_deadline_ms'] = str(int((now * 1000) + 1500 - age - delay))
        rate = sensor.get('observed_rate_hz')
        rate_text = 'rate --' if type(rate) not in (int, float) or not math.isfinite(rate) or not 0 <= rate <= 8000 else 'observed %.0fHz' % rate
        result[prefix + '_info'] = '%s WHO=%02X / CONFIG OK / %s' % (channel, who, rate_text)
    return result
