"""Finite, board-local BNC1 sweep with raw observations and temperature restore."""
import argparse
import hashlib
import json
import os
import signal
from pathlib import Path
import threading
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    def interrupted(signum, unused_frame):
        raise KeyboardInterrupt('Sweep interrupted by signal %d' % signum)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--seconds', type=int, default=5)
    p.add_argument('--descending', action='store_true')
    p.add_argument('--duties', type=int, nargs='+')
    a = p.parse_args()
    assert 5 <= a.seconds <= 20
    assert a.duties is None or (len(a.duties)==len(set(a.duties)) and
                               all(0<=d<=100 and d%10==0 for d in a.duties))
    a.output.mkdir(parents=True, exist_ok=False)
    env = dict(line.split('=', 1) for line in Path('/etc/cabinet/web.env').read_text().splitlines()
               if line and not line.startswith('#'))
    headers = {'Authorization': 'Bearer ' + env['CABINET_HMI_TOKEN'].strip('\"\''),
               'X-Cabinet-Control-Token': env['CABINET_CONTROL_TOKEN'].strip('\"\''),
               'Content-Type': 'application/json'}

    def api(name, body=None):
        request = Request('http://127.0.0.1:8766/api/commissioning/' + name,
                          data=None if body is None else json.dumps(body).encode(), headers=headers)
        with urlopen(request, timeout=8) as response:
            return json.load(response)

    before = api('status')
    save(a.output / 'before.json', before)
    assert before['live']['link'] == 'ONLINE'
    assert not before['bench'].get('controls_enabled')
    assert not before['control']['enabled']
    thermal = before['temperature_pwm']['settings']
    revision = before['revision']
    assert thermal['enabled'] is True
    stop = threading.Event()
    context = {'duty_percent': None, 'trial_id': None}
    sample_errors = []
    summary = {'schema': 'cabinet-normal-pwm-sweep-v1', 'session_id': uuid.uuid4().hex,
               'started_at': time.monotonic(),
               'label': 'normal', 'label_source': 'USER_DECLARES_HEAT_SOURCE_OPERATING_NORMALLY',
               'os_boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'machine_id': Path('/etc/machine-id').read_text().strip(),
               'seconds_per_duty': a.seconds, 'trials': [], 'trained': False,
               'raw_capture_qualification_changed': False}

    def collect():
        last = None
        with (a.output / 'observations.jsonl').open('w', encoding='utf-8') as stream:
            while not stop.wait(.04):
                try:
                    document = json.loads(Path('/run/cabinet-live/npu_input.json').read_text())
                    observation = document.get('observation') or {}
                    header = (observation.get('frame') or {}).get('header') or []
                    key = (observation.get('boot'), header[3]) if len(header) == 32 else None
                    if key is None or key == last:
                        continue
                    last = key
                    row = dict(context)
                    row.update(read_at=time.monotonic(), observation=observation)
                    stream.write(json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n')
                except Exception as error:
                    sample_errors.append(str(error))
            stream.flush()
            os.fsync(stream.fileno())

    collector = threading.Thread(target=collect)
    collector.start()
    changed = False
    try:
        changed = True
        api('temperature-pwm-save', dict(expected_revision=thermal['revision'], enabled=False,
                                        low_C=thermal['low_C'], high_C=thermal['high_C']))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            off = api('temperature-pwm-status')
            if off['state'] == 'DISABLED' and off['actual_pwm_percent'] == 0:
                break
            time.sleep(.2)
        else:
            raise RuntimeError('Temperature PWM did not release output')
        time.sleep(.5)
        duties = a.duties or list(range(0, 101, 10))
        if a.descending:
            duties.reverse()
        for duty in duties:
            # Do not repeatedly render the complete learning history between
            # steps. Its immutable calibration pin and optimistic revision
            # were captured above; input edits still detect concurrent changes.
            deadline = time.monotonic() + 3
            while api('temperature-pwm-status')['actual_pwm_percent'] != 0:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Previous trial output did not return to zero')
                time.sleep(.1)
            profile = dict(source='REAL_USER_MEASUREMENTS', operator='heisenberg-authorized-normal-sweep',
                           reference_evidence_sha256=before['calibration_csv_sha256'], wiring_verified=True,
                           zero_pwm_not_poweroff_confirmed=True, max_duty_percent=100,
                           current_zero_code=thermal['guards']['current_zero_code'],
                           current_trip_distance_code=thermal['guards']['peak_trip_code'],
                           temperature_trip_C=75, minimum_fg_period_clocks=454546,
                           duration_limit_s=min(30, a.seconds + 3))
            remaining = a.seconds
            steps = []
            while remaining:
                duration = min(10, remaining)
                steps.append(dict(duty_percent=duty, seconds=duration))
                remaining -= duration
            plan = dict(profile=profile, steps=steps)
            updated = api('inputs', dict(revision=revision, name='bench.json',
                                         content=json.dumps(plan)))
            revision = updated['revision']
            deadline = time.monotonic() + 8
            while True:
                preview = api('bench-preview', dict(revision=updated['revision']))
                if preview['live_start_available']:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Bench capability unavailable: ' + str(preview))
                time.sleep(.2)
            trial = api('bench-start', dict(preview_id=preview['preview_id'], start_controlled_trial=True,
                                           authorization=preview['authorization']))
            context.update(duty_percent=duty, trial_id=trial['id'])
            deadline = time.monotonic() + a.seconds + 8
            while time.monotonic() < deadline:
                current = api('bench-status')
                if current['state'] == 'ACTIVE_BENCH_NOT_CLOSED_LOOP':
                    try:
                        api('bench-heartbeat', dict(id=trial['id']))
                    except HTTPError as error:
                        # The final poll can finish the plan between status
                        # and heartbeat. Preserve its terminal measurement.
                        if error.code != 409:
                            raise
                        current = api('bench-status')
                        if current['state'] in ('ACTIVE_BENCH_NOT_CLOSED_LOOP', 'QUEUED_NOT_APPLIED'):
                            raise
                        break
                elif current['state'] not in ('QUEUED_NOT_APPLIED',):
                    break
                time.sleep(.12)
            else:
                raise RuntimeError('Bench trial deadline exceeded')
            save(a.output / ('duty_%03d.json' % duty), current)
            if current['state'] != 'COMPLETED':
                raise RuntimeError('Trial %d failed: %s / %s / %s' %
                    (duty, current['state'], current.get('reason'), current.get('error')))
            summary['trials'].append(dict(duty_percent=duty, id=trial['id'], state=current['state'],
                                           output_tracking=current.get('output_tracking')))
            print(json.dumps(summary['trials'][-1]), flush=True)
            context.update(duty_percent=None, trial_id=None)
            time.sleep(.4)
        summary['state'] = 'COMPLETE'
    except BaseException as error:
        summary.update(state='FAILED', error=str(error))
        raise
    finally:
        if changed:
            try:
                if api('bench-status')['state'] in ('ACTIVE_BENCH_NOT_CLOSED_LOOP', 'QUEUED_NOT_APPLIED'):
                    api('bench-stop', {})
                time.sleep(.5)
                current = api('temperature-pwm-status')
                api('temperature-pwm-save', dict(expected_revision=current['settings']['revision'],
                                                enabled=thermal['enabled'], low_C=thermal['low_C'],
                                                high_C=thermal['high_C']))
                api('inputs', dict(revision=revision, name='bench.json',
                                   content=before['documents']['bench.json']))
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    restored = api('temperature-pwm-status')
                    if restored['state'] == 'RUNNING' and restored['feedback_valid']:
                        break
                    time.sleep(.2)
                summary['restored_temperature_pwm'] = restored
                assert restored['state'] == 'RUNNING', restored
            except BaseException as error:
                summary['restore_error'] = str(error)
        stop.set()
        collector.join(timeout=4)
        summary['sample_errors'] = sample_errors
        summary['observations_sha256'] = hashlib.sha256((a.output / 'observations.jsonl').read_bytes()).hexdigest()
        save(a.output / 'summary.json', summary)
        print(json.dumps({'state': summary.get('state'), 'restore_error': summary.get('restore_error'),
                          'path': str(a.output)}), flush=True)


if __name__ == '__main__':
    main()
