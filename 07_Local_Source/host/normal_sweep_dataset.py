"""Load separately captured, measured PWM sweeps; never relabel fault captures."""
import hashlib
import json
from collections import Counter
import numpy as np
from normal_npu.core import FEATURES, validate_header
from cabinet.icm_display import display_fields
from cabinet.feature_display import verified_sensor_pair_deadline

SCHEMA = 'cabinet-user-normal-pwm-reference-v1'
DUTIES = list(range(0, 101, 10))


def load_split(name, expected, root, unused_filter=False):
    confirmation=json.loads((root/'normal_confirmation.json').read_text())
    assert confirmation.get('condition')=='normal'
    assert confirmation.get('source')=='USER_CONFIRMED_BLOCKAGE_REMOVED'
    assert confirmation.get('covers_recorded_sweeps') is True
    folder = root / name
    meta_path = folder / 'summary.json'
    meta = json.loads(meta_path.read_text())
    assert meta['os_boot_id']==confirmation['os_boot_id']
    frames = folder / 'observations.jsonl'
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if confirmation.get('confirmation_mode')=='RETROSPECTIVE_EXACT_CAPTURE':
        approved=confirmation['approved_captures'][name]
        assert approved==dict(session_id=meta['session_id'],summary_sha256=sha(meta_path),
                              observations_sha256=sha(frames))
    else:
        assert meta['started_at']>=confirmation['board_not_before_monotonic_s']
    assert meta['schema'] == 'cabinet-normal-pwm-sweep-v1'
    assert meta['state'] == 'COMPLETE' and not meta.get('restore_error')
    assert meta['label'] == 'normal'
    assert meta['label_source'] == 'USER_DECLARES_HEAT_SOURCE_OPERATING_NORMALLY'
    assert meta['raw_capture_qualification_changed'] is False
    assert meta['observations_sha256'] == sha(frames)
    assert sorted(t['duty_percent'] for t in meta['trials']) == DUTIES
    assert all(t['state'] == 'COMPLETED' for t in meta['trials'])
    valid_trials = {t['id']: t['duty_percent'] for t in meta['trials']}
    rows = [json.loads(line) for line in frames.read_text().splitlines()]
    values, ids, excluded = [], [], Counter()
    coverage = Counter()
    temperatures = []
    seen = set()
    for row in rows:
        o = row['observation']
        status, frame, bench = o['status'], o.get('frame', {}), o.get('bench', {})
        h = frame.get('header', [])
        trial = row.get('trial_id')
        if trial not in valid_trials or bench.get('id') != trial:
            excluded['OUTSIDE_REQUESTED_TRIAL'] += 1
            continue
        duty = valid_trials[trial]
        if (bench.get('state') != 'ACTIVE_BENCH_NOT_CLOSED_LOOP' or
                bench.get('controls_enabled') is not True or bench.get('elapsed_s', 0) < 4):
            excluded['SETTLING_OR_NOT_ACTIVE'] += 1
            continue
        if (row.get('duty_percent') != duty or bench.get('requested_pwm_counts') != duty * 40 or
                status.get('applied_pwm_counts') != duty * 40):
            excluded['ACTUAL_PWM_MISMATCH'] += 1
            continue
        if expected is None:
            expected = dict(device_id='machine:' + meta['machine_id'],
                configuration_words=o['feature_words'], frame_identity=[h[16], h[17], h[18]],
                controller_mode=status['mode'], controller_diagnostic_mode=bool(status['test_mode']),
                pwm_operating_reference=dict(schema=SCHEMA, duty_nodes_percent=DUTIES,
                    source='THREE_REAL_USER_DECLARED_NORMAL_PWM_SWEEPS', steady_only=True))
        try:
            assert o['link'] == 'ONLINE' and o['boot'].startswith(expected['device_id'] + '/')
            assert o['feature_words'] == expected['configuration_words']
            assert frame['state'] == 'RECEIVED_REAL'
            assert 0 <= row['read_at'] - o['received_at'] <= 1
            validate_header(h, status, expected)
            fields = display_fields(o.get('icm_diagnostics'), row['read_at'], o['received_at'], o['boot'])
            assert verified_sensor_pair_deadline(fields, row['read_at'])
            vector = [frame['values'][key] for key in FEATURES]
            assert all(type(v) in (int, float) and np.isfinite(v) for v in vector)
        except (ValueError, KeyError, AssertionError) as error:
            excluded['INVALID_REAL_INPUT:' + str(error)] += 1
            continue
        key = (o['boot'], h[3])
        assert key not in seen, 'Duplicate frame in sweep'
        seen.add(key)
        values.append(vector)
        ids.append(h[3])
        coverage[duty] += 1
        temperatures.append(status['temp_raw_1_16_C'] / 16.)
    assert len(values) >= 600, ('Insufficient stable sweep frames', len(values), excluded)
    assert all(coverage[duty] >= 40 for duty in DUTIES), ('Incomplete measured PWM coverage', coverage)
    assert all(a < b for a, b in zip(ids, ids[1:])), 'Frame order changed'
    return np.asarray(values, dtype=np.float32), ids, expected, dict(
        session_id=meta['session_id'], source='REAL_FRM1_USER_DECLARED_NORMAL_PWM_SWEEP',
        rows=len(values), boot_id=meta['os_boot_id'], raw_rows=len(rows),
        session_sha256=sha(meta_path), frames_sha256=sha(frames),
        first_frame=ids[0], last_frame=ids[-1], capture_formal_accepted=0,
        capture_label_declared='normal', advisory_label_source=confirmation['source'],
        normal_confirmation_sha256=sha(root/'normal_confirmation.json'),
        raw_capture_qualification_changed=False, excluded_reason_counts=dict(excluded),
        pwm_coverage={str(k): v for k, v in sorted(coverage.items())},
        settling_excluded_seconds=4, temperature_range_C=[min(temperatures), max(temperatures)])
