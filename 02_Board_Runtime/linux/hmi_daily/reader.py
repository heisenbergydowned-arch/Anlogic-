"""Actual UIO observer for the display. No actuator, lease or configuration commands."""
import argparse
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time

from cabinet.io import Controller, MMIO
from cabinet.protocol import FEATURES, Frame
if __package__:
    from .cabinet.baseline import BaselineStore, Learner, BUSY, DEFAULTS
    from .cabinet.learning_rpc import LearningRPC
    from .cabinet.learning_web import ClockTrust, WebLearningControl
    from .read_real import find_uio, read_identity, read_sample
    from .presentation import build_presentation
    from .daily import build_daily
else:
    from cabinet.baseline import BaselineStore, Learner, BUSY, DEFAULTS
    from cabinet.learning_rpc import LearningRPC
    from cabinet.learning_web import ClockTrust, WebLearningControl
    from read_real import find_uio, read_identity, read_sample
    from presentation import build_presentation
    from daily import build_daily


def view_state(sample, last_frame, last_received, now, sequence):
    status = sample['status']
    incoming = sample['frame']
    if incoming['state'] == 'RECEIVED_REAL':
        last_frame, last_received = incoming, now
    age = None if last_received is None else max(0, int((now - last_received) * 1000))
    if last_frame is not None:
        pl_age = (status['uptime_ms'] - last_frame['end_ms']) & 0xffffffff
        if pl_age >= 0xffffffff - 99:
            pl_age = 0
        age = max(age, pl_age)
    fresh = age is not None and age <= 1000
    if incoming['state'] == 'REJECTED_TEST':
        message = 'TEST source detected - not real sensor evidence'
        fresh = False
    elif not fresh:
        message = 'WAITING FOR SAMPLES' if last_frame is None else 'STALE FRAME - values hidden'
    elif last_frame['quality']:
        message = 'REAL FRAME / QUALITY FLAGS - not model-qualified'
    else:
        message = 'REAL FRAME RECEIVED - display test only'
    validity = status.get('input_validity', {})
    output = {
        'sequence': sequence, 'link': 'FCB1 + EDG1 ABI OK', 'message': message,
        'uptime': '%s ms' % status.get('uptime_ms', '?'),
        'mode': str(status.get('mode', '?')), 'alarm': str(status.get('alarm_level', '?')),
        'action': str(status.get('fan_action', '?')),
        'inhibit': 'YES' if status.get('hard_inhibit') else 'NO',
        'configured': 'YES' if status.get('configured') else 'NO',
        'control_test_flag': 'UNQUALIFIED / LOCAL' if status.get('test_mode') else 'NORMAL',
        'rpm': '%s rpm' % status['measured_rpm'] if validity.get('rpm') else 'INVALID / --',
        'temp': '%.2f C' % (status['temp_raw_1_16_C'] / 16.0) if validity.get('temperature') else 'INVALID / --',
        'current': '%s raw code' % status['current_distance_raw_code'] if validity.get('adc') else 'INVALID / --',
        'pressure': 'VALID (frame only)' if validity.get('pressure') else 'INVALID / --',
        'validity': 'RPM:%d ADC:%d TEMP:%d PRESS:%d' % tuple(bool(validity.get(name)) for name in ('rpm', 'adc', 'temperature', 'pressure')),
        'faults': ', '.join(status.get('active', [])) or 'NONE',
        'latched': ', '.join(status.get('latched', [])) or 'NONE',
        'queue': str(sample['mailbox_before_read']['queued_frames']),
        'drops': str(sample['mailbox_before_read']['dropped_frames']),
        'frame_id': str(last_frame['frame_id']) if last_frame else '--',
        'frame_age': '%d ms' % age if age is not None else '--',
        'quality': '0x%08x' % last_frame['quality'] if last_frame else '--',
        'quality_reasons': ', '.join(last_frame['quality_reasons']) if last_frame else 'no frame',
        'frame_state': incoming['state'],
        'frame_calibrated': '1' if fresh and type(last_frame.get('calibration_id')) is int and
                            last_frame['calibration_id'] > 0 and not (last_frame['quality'] & 0x1000) else '0',
        'frame_contract_current': '1' if fresh and sample.get('feature_words', [])[:3] ==
                                  [last_frame.get('feature_config_id'), last_frame.get('calibration_id'), 1] else '0',
        'frame_sample_mode': str(last_frame.get('sample_mode_id', '--')) if fresh else '--',
        'frame_clock_hz': str(last_frame.get('header', [0] * 32)[21]) if fresh else '--',
        'frame_rate_a': str(last_frame.get('sample_rate_a', '--')) if fresh else '--',
        'frame_rate_b': str(last_frame.get('sample_rate_b', '--')) if fresh else '--',
    }
    for name in FEATURES:
        output['feature_' + name] = '%.6g' % last_frame['values'][name] if fresh else '--'
    output['frame_fresh'] = '1' if fresh else '0'
    output.update(build_presentation(output, sample))
    return output, last_frame, last_received


def publish_inference(directory, sample, offline_reason=None):
    """Publish the immutable measurement before slower display/learning work."""
    directory.mkdir(parents=True, exist_ok=True)
    document = {'observation': sample}
    if sample is None:
        document['display'] = {'link': 'ERROR', 'message': offline_reason}
    temporary = directory / 'npu_input.json.new'
    temporary.write_text(json.dumps(document, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    os.replace(str(temporary), str(directory / 'npu_input.json'))


def publish(directory, state, sample):
    directory.mkdir(parents=True, exist_ok=True)
    payloads = {'state.txt': ''.join('%s=%s\n' % (key, str(value).replace('\n', ' ').encode('utf-8')[:500].decode('utf-8', 'ignore')) for key, value in state.items()),
                # Compact JSON uses the C encoder and avoids a large Python/GIL
                # cost on the board. The parsed contract and timestamps match.
                'state.json': json.dumps({'display': state, 'observation': sample}, allow_nan=False, separators=(',', ':')) + '\n'}
    for name, data in payloads.items():
        temporary = directory / (name + '.new')
        temporary.write_text(data, encoding='utf-8')
        os.replace(str(temporary), str(directory / name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--standalone-diagnostic', action='store_true')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('/run/cabinet-live'))
    parser.add_argument('--learning-config', type=Path, default=Path(__file__).resolve().parent / 'learning_config.json')
    parser.add_argument('--learning-db', type=Path, default=Path(__file__).resolve().parent / 'data/baselines.sqlite3')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live required; no mock backend exists')
    if not args.standalone_diagnostic:
        parser.error('Use the integrated collector; standalone hardware access requires --standalone-diagnostic')
    registers = None
    store = learner = rpc = clock = web_control = None
    learning_error = None
    sequence = 0
    stopping = [False]

    def stop(number, frame):
        stopping[0] = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        registers = MMIO(find_uio(), str(Path(__file__).resolve().parent / 'native/libedge_mmio.so'))
        identity = read_identity(registers)
        print(json.dumps({'identity': identity}), flush=True)
        controller = Controller(registers)
        controller.identify()
        try:
            config = json.loads(args.learning_config.read_text(encoding='utf-8'))
            store = BaselineStore(args.learning_db)
            learner = Learner(store, config)
            clock = ClockTrust()
            web_control = WebLearningControl(learner, clock)
            rpc = LearningRPC(args.output / 'learning.sock')
        except (OSError, ValueError, sqlite3.Error) as error:
            learning_error = str(error)
            print('Learning unavailable: ' + learning_error, file=sys.stderr, flush=True)
        previous_uptime = None
        previous_progress = time.monotonic()
        last_frame = last_received = None
        test_source_seen = False
        while not stopping[0]:
            started = time.monotonic()
            read_identity(registers)
            if registers.read(0x1050) != controller.boot_cookie:
                raise RuntimeError('PL boot cookie changed; restart this observer')
            sample = read_sample(controller)
            test_source_seen = test_source_seen or sample['frame']['state'] == 'REJECTED_TEST'
            if test_source_seen:
                sample['frame']['state'] = 'REJECTED_TEST'
            sequence += 1
            now = time.monotonic()
            uptime = sample['status'].get('uptime_ms')
            if previous_uptime is not None and uptime < previous_uptime and previous_uptime - uptime < 0x80000000:
                raise RuntimeError('PL uptime restarted; reacquire the link before displaying data')
            if uptime != previous_uptime:
                previous_progress = now
            elif now - previous_progress > 2:
                raise RuntimeError('PL status clock stopped')
            previous_uptime = uptime
            state, last_frame, last_received = view_state(sample, last_frame, last_received, now, sequence)
            baseline = {'state': 'ERROR', 'reason': 'SERVICE_UNAVAILABLE', 'can_start': False,
                        'evidence': {'state': 'INVALID_INPUT', 'score': None, 'level': 0},
                        'detail': learning_error}
            if learner is not None and learning_error is None:
                try:
                    record = sample['frame']
                    frame = Frame(tuple(record['header']), tuple(record['values'][name] for name in FEATURES)) if record.get('header') else None
                    learner.observe(frame, sample['status'], sample['feature_words'], controller.boot_cookie, now)
                    if test_source_seen:
                        learner.invalidate('TEST_SOURCE')
                    web_control.update(sample['status'], controller.boot_cookie, now)
                    rpc.poll(learner, now, web_control)
                    baseline = learner.snapshot()
                    sample['learning_web'] = web_control.snapshot(now)
                except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                    learning_error = str(error)
                    try:
                        learner.invalidate('SERVICE_UNAVAILABLE')
                    except sqlite3.Error:
                        pass
                    rpc.close()
                    rpc = None
                    print('Learning stopped: ' + learning_error, file=sys.stderr, flush=True)
            sample['baseline'] = baseline
            state.update(build_daily(state, sample, baseline))
            publish(args.output, state, sample)
            if args.once:
                print(json.dumps({'display': state, 'observation': sample}), flush=True)
                return 0
            time.sleep(max(0.01, 0.1 - (time.monotonic() - started)))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        publish(args.output, {'sequence': sequence + 1, 'link': 'ERROR', 'message': str(error)}, None)
        print('ERROR: ' + str(error), file=sys.stderr, flush=True)
        return 1
    finally:
        if clock is not None:
            clock.close()
        if rpc is not None:
            rpc.close()
        if learner is not None and learner.state in BUSY:
            try:
                learner.finish('ABORTED', 'SERVICE_STOPPED')
            except (OSError, sqlite3.Error):
                pass
        if store is not None:
            store.close()
        if registers is not None:
            registers.close()


if __name__ == '__main__':
    sys.exit(main())
