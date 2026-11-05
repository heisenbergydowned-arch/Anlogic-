import math


def verified_sensor_pair_deadline(sensor_fields, now):
    """Both physical ICM channels must have independent, unexpired evidence."""
    if not isinstance(sensor_fields, dict):
        return 0
    deadlines = []
    for point in 'ab':
        value = sensor_fields.get('panel_icm_' + point + '_deadline_ms')
        if not isinstance(value, str) or not value.isdigit():
            return 0
        deadline = int(value)
        if not 0 < deadline - now * 1000 <= 1500:
            return 0
        deadlines.append(deadline)
    return min(deadlines)


def raw_feature_fields(frame, words, status, now, received_at,
                       sensor_fields=None, sensor_pair_since_ms=None):
    result = dict(panel_raw_features_valid='0', panel_raw_features_deadline_ms='0')
    pair_deadline = verified_sensor_pair_deadline(sensor_fields, now)
    if not pair_deadline or type(sensor_pair_since_ms) is not int:
        return result
    if not isinstance(frame, dict) or frame.get('state') != 'RECEIVED_REAL' or frame.get('test') is not False:
        return result
    header = frame.get('header')
    if not isinstance(header, list) or len(header) != 32 or any(type(value) is not int for value in header):
        return result
    quality = frame.get('quality')
    if type(quality) is not int or quality < 0 or quality & ~0x3f00 or header[15] != quality or header[27] != 0:
        return result
    if (len(words) != 17 or words[:2] != header[16:18] or header[18] not in (1, 2) or
            header[11:13] != [1024, 1024] or header[21] != 100000000):
        return result
    if type(status.get('uptime_ms')) is not int or not 0 <= now - received_at <= 1:
        return result
    age = ((status['uptime_ms'] - header[4]) & 0xffffffff) + (now - received_at) * 1000
    if age > 2000:
        return result
    for span in header[9:11]:
        if span <= 0 or not 3880 <= 1023 * header[21] / span <= 4120:
            return result
    # R45 can mirror the surviving channel into the missing one. Do not reuse
    # a cached/straddling frame when independent A/B evidence first recovers.
    pair_age_ms = (status['uptime_ms'] - sensor_pair_since_ms) & 0xffffffff
    frame_age_ms = (status['uptime_ms'] - header[4]) & 0xffffffff
    window_ms = math.ceil(max(header[9:11]) * 1000 / header[21])
    if pair_age_ms >= 0x80000000 or pair_age_ms < frame_age_ms + window_ms:
        return result
    bins = words[8:17]
    if any(type(value) is not int or not 1 <= value <= 513 for value in bins) or any(left >= right for left, right in zip(bins, bins[1:])):
        return result
    values = frame.get('values')
    if not isinstance(values, dict):
        return result
    staged = {}
    try:
        for point in 'ab':
            for axis in 'xyz':
                for kind, scale, maximum in [('rms', 4096, 32768.1), ('pp', 4096, 65535.1), ('kurt', 1, 1024.1)]:
                    name = kind + '_' + point + '_' + axis
                    number = values[name]
                    if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number * scale <= maximum:
                        return result
                    staged['raw_feature_' + name] = ('%.2f' if kind == 'kurt' else '%.1f') % (number * scale)
            total = 0
            for band in range(8):
                name = 'band' + point + str(band)
                number = values[name]
                if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1.001:
                    return result
                total += number
                staged['raw_feature_' + name] = '%.2f' % (number * 100)
            if not 0 < total <= 1.05:
                return result
        ratio = values['ratio_ab']
        if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= 65536:
            return result
    except (KeyError, TypeError, OverflowError):
        return result
    staged['raw_feature_ratio_ab'] = '%.3f' % ratio
    for band in range(8):
        staged['raw_feature_band' + str(band) + '_hz'] = '%.0f' % ((bins[band] + bins[band + 1]) * 4000 / 2048)
    staged.update(panel_raw_features_valid='1',
                  panel_raw_features_deadline_ms=str(min(pair_deadline, int(now * 1000 + 2000 - age))))
    return staged
