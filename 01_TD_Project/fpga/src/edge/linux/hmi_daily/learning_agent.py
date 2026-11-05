"""Opt-in outbound HTTPS agent. Does not open UIO or a listening network port."""
import argparse
import fcntl
import json
from pathlib import Path
import signal
import sqlite3
import sys
import time

from cabinet.learning_agent import AgentJournal, HTTPSExchange, LearningAgent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--origin', required=True)
    parser.add_argument('--device-id', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--ca-file')
    parser.add_argument('--socket', type=Path, default=Path('/run/cabinet-live/learning.sock'))
    parser.add_argument('--journal', type=Path, default=Path(__file__).resolve().parent / 'data/learning-agent.sqlite3')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live required; no network or local commands were executed')
    stopped = [False]

    def stop(number, frame):
        stopped[0] = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    journal = None
    try:
        args.journal.parent.mkdir(parents=True, exist_ok=True)
        args.journal.parent.chmod(0o700)
        with (args.journal.parent / 'learning-agent.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            transport = HTTPSExchange(args.origin, args.device_id, args.token_file, args.ca_file)
            journal = AgentJournal(args.journal)
            agent = LearningAgent(args.device_id, args.socket, journal, transport)
            failures = 0
            while not stopped[0]:
                try:
                    result = agent.tick()
                    failures = 0
                except (OSError, RuntimeError, ValueError, sqlite3.Error):
                    failures = min(failures + 1, 5)
                    result = {'ok': False, 'reason': 'EXCHANGE_FAILED_CHECK_LOCAL_SERVICE_AND_BACKEND'}
                print(json.dumps(result), flush=True)
                if args.once:
                    return 0 if result['ok'] else 1
                deadline = time.monotonic() + (1 if not failures else min(30, 2 ** failures))
                while not stopped[0] and time.monotonic() < deadline:
                    time.sleep(0.1)
        return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        print(json.dumps({'ok': False, 'reason': 'AGENT_START_FAILED_CHECK_CONFIG_LOCK_AND_TOKEN'}), file=sys.stderr)
        return 1
    finally:
        if journal is not None:
            journal.close()


if __name__ == '__main__':
    sys.exit(main())
