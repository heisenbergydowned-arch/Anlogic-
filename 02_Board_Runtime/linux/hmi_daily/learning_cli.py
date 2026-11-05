"""Local healthy-baseline commands. Never opens UIO or sends actuator commands."""
import argparse
import json
from pathlib import Path
import sys
import uuid

from cabinet.learning_rpc import request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', type=Path, default=Path('/run/cabinet-live/learning.sock'))
    parser.add_argument('--request-id', default=None)
    sub = parser.add_subparsers(dest='operation')
    sub.add_parser('status')
    sub.add_parser('web-status')
    sub.add_parser('web-history')
    result_parser = sub.add_parser('web-result')
    result_parser.add_argument('--id', required=True)
    start = sub.add_parser('start')
    start.add_argument('--confirm-healthy', action='store_true', required=True)
    start.add_argument('--operator', default='local')
    cancel = sub.add_parser('cancel')
    cancel.add_argument('--job-id', required=True)
    commit = sub.add_parser('commit')
    commit.add_argument('--candidate-hash', required=True)
    rollback = sub.add_parser('rollback')
    rollback.add_argument('--baseline-id', required=True)
    args = parser.parse_args()
    if not args.operation:
        parser.error('Choose an operation')
    payload = {'operation': args.operation, 'request_id': args.request_id or str(uuid.uuid4())}
    if args.operation == 'start':
        payload.update(healthy_confirmed=args.confirm_healthy, operator=args.operator)
    for name in ('job_id', 'candidate_hash', 'baseline_id'):
        if hasattr(args, name):
            payload[name] = getattr(args, name)
    if args.operation.startswith('web-'):
        payload = {'operation': 'status', 'view': {'web-status': 'web', 'web-history': 'baselines', 'web-result': 'command'}[args.operation]}
        if args.operation == 'web-result':
            payload['request_id'] = args.id
    try:
        result = request(args.socket, payload)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0 if result.get('ok') else 2
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({'ok': False, 'reason': 'RPC_UNAVAILABLE', 'detail': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
