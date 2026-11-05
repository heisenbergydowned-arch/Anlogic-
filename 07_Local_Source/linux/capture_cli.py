#!/usr/bin/env python3
"""Local-owner session commands. No MMIO, fan commands, baseline updates or model training."""
import argparse
import json
from pathlib import Path
import sys
import uuid

from hmi_daily.cabinet.learning_rpc import request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', type=Path, default=Path('/run/cabinet-live/capture.sock'))
    sub = parser.add_subparsers(dest='operation')
    sub.add_parser('status')
    start = sub.add_parser('start')
    start.add_argument('--installation', required=True)
    start.add_argument('--operator', required=True)
    start.add_argument('--label', choices=('unlabelled', 'normal', 'imbalance', 'stall', 'clog', 'overheat'), default='unlabelled')
    start.add_argument('--seconds', type=int, default=60)
    start.add_argument('--diagnostic', action='store_true')
    start.add_argument('--bitstream-sha256')
    start.add_argument('--calibration-evidence-sha256')
    start.add_argument('--note', required=True)
    sub.add_parser('stop')
    args = parser.parse_args()
    if args.operation is None:
        parser.error('Choose status, start or stop')
    try:
        status = request(args.socket, {'operation': 'status'})
        if not status.get('ok'):
            raise RuntimeError(str(status))
        if args.operation == 'status':
            response = status
        else:
            payload = {'session_id': status['status']['session_id']}
            if args.operation == 'start':
                payload = dict(expected_boot=status['status']['boot'], installation_id=args.installation,
                    operator=args.operator, label=args.label, duration_s=args.seconds,
                    capture_mode='DIAGNOSTIC' if args.diagnostic else 'REAL',
                    bitstream_sha256=args.bitstream_sha256,
                    calibration_evidence_sha256=args.calibration_evidence_sha256, note=args.note)
            response = request(args.socket, dict(operation=args.operation, request_id=str(uuid.uuid4()), payload=payload))
        print(json.dumps(response, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if response.get('ok') else 1
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print('Capture command failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
