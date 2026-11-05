"""Read actual FCB1 status and FRM1 frames. No generated samples or actuator commands."""
import argparse
import json
from pathlib import Path
import sys
import time

from cabinet.io import Controller, MMIO
from cabinet.environment import read_environment


def find_uio(root=Path('/sys/class/uio')):
    matches = []
    for entry in sorted(root.glob('uio*')):
        try:
            address = int((entry / 'maps/map0/addr').read_text().strip(), 0)
            size = int((entry / 'maps/map0/size').read_text().strip(), 0)
        except (OSError, ValueError):
            continue
        if address == 0x80400000 and size >= 65536:
            matches.append('/dev/' + entry.name)
    if len(matches) != 1:
        raise RuntimeError('Expected one UIO map at 0x80400000, found %d. Check the loaded DTB, bootargs and uio_pdrv_genirq.' % len(matches))
    return matches[0]


def read_identity(registers):
    values = {
        'fcb1': registers.read(0),
        'fcb1_abi': registers.read(4),
        'edg1': registers.read(0x1000),
        'edg1_abi': registers.read(0x1004),
    }
    if tuple(values.values()) != (0x46434231, 0x10000, 0x45444731, 0x10000):
        raise RuntimeError('FCB1/EDG1 identity or ABI mismatch: ' + repr(values))
    return {name: '0x%08x' % value for name, value in values.items()}


def read_mailbox(registers):
    status = registers.read(0x1008)
    return {
        'queued_frames': status & 3,
        'building_frame': bool(status & 8),
        'engine_busy': bool(status & 16),
        'dropped_frames': registers.read(0x100c),
        'feature_config_id': registers.read(0x1020),
        'calibration_id': registers.read(0x1024),
        'capabilities': registers.read(0x1040) & 0xfffe0000,
    }


def read_feature_configuration(registers):
    first = (registers.read(0x1020), registers.read(0x1024))
    words = [registers.read(0x1380 + 4 * index) for index in range(17)]
    last = (registers.read(0x1020), registers.read(0x1024))
    if first != last or tuple(words[:2]) != last:
        return []
    return words


def normalize_status(status, keep_raw=False):
    status = dict(status)
    words = status.get('raw_words') if keep_raw else status.pop('raw_words', None)
    if words is not None and len(words) == 32:
        flags = words[0]
        status['input_validity'] = {
            'rpm': bool(flags & (1 << 10)),
            'adc': bool(flags & (1 << 11)),
            'temperature': bool(flags & (1 << 12)),
            'pressure': bool(flags & (1 << 13)),
        }
        status['configured'] = bool(flags & (1 << 14))
        status['hard_inhibit'] = bool(flags & (1 << 4))
        pressure_code = (words[22] >> 16) & 0xffff
        status['pressure_raw_code'] = pressure_code - 65536 if pressure_code & 0x8000 else pressure_code
    return status


def sample_record(frame, status, mailbox, feature_words):
    if frame is None:
        result = {
            'state': 'EMPTY',
            'reason': 'No complete 39D frame queued. With REAL and no fresh A/B vibration samples, this is expected.',
        }
    else:
        result = frame.as_dict()
        result['header'] = list(frame.header)
        result['state'] = 'REJECTED_TEST' if frame.test else 'RECEIVED_REAL'
        result['model_qualified_by_this_reader'] = False
    return {'status': status, 'mailbox_before_read': mailbox, 'frame': result,
            'feature_words': list(feature_words)}


def read_sample(controller):
    mailbox = read_mailbox(controller.io)
    frame = controller.frame()
    status = normalize_status(controller.status())
    sample = sample_record(frame, status, mailbox, read_feature_configuration(controller.io))
    sample['environment'] = read_environment(controller.io, mailbox)
    return sample


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Required to access actual hardware')
    parser.add_argument('--device', help='Default: locate cabinet UIO automatically; /dev/mem is an explicit board-admin fallback')
    parser.add_argument('--library', type=Path, default=Path(__file__).resolve().parent / 'native/libedge_mmio.so')
    parser.add_argument('--once', action='store_true', help='Print one status/frame observation and exit')
    parser.add_argument('--identity-only', action='store_true', help='Only read identity/mailbox; no writes, cookie, snapshot or ACK')
    parser.add_argument('--interval', type=float, default=0.128)
    parser.add_argument('--duration', type=float, default=0, help='Zero: until Ctrl+C')
    args = parser.parse_args(argv)
    if not args.live:
        parser.error('--live is required; this program never substitutes simulated data')
    if not 0.05 <= args.interval <= 10 or not 0 <= args.duration < float('inf'):
        parser.error('interval must be 0.05..10 seconds and duration finite/nonnegative')
    if not args.library.is_file():
        parser.error('Build the board library first: make -C native')
    registers = None
    try:
        device = args.device or find_uio()
        if device != '/dev/mem' and not (device.startswith('/dev/uio') and device[8:].isdigit()):
            raise ValueError('Only /dev/uioN or explicit /dev/mem is supported')
        registers = MMIO(device, str(args.library.resolve()))
        identity = read_identity(registers)
        print(json.dumps({'device': device, 'identity': identity, 'mailbox': read_mailbox(registers)}, ensure_ascii=False), flush=True)
        if args.identity_only:
            return 0
        controller = Controller(registers)
        controller.identify()
        started = time.monotonic()
        while True:
            sample = read_sample(controller)
            print(json.dumps(sample, ensure_ascii=False), flush=True)
            if sample['frame']['state'] == 'REJECTED_TEST':
                raise RuntimeError('Received TEST frame; expected the REAL boot package')
            if args.once or (args.duration and time.monotonic() - started >= args.duration):
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1
    finally:
        if registers is not None:
            registers.close()


if __name__ == '__main__':
    sys.exit(main())
