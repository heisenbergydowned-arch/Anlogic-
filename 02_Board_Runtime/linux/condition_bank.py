"""Explicitly publish or restore a pinned, reviewed multi-condition bank."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from model_release import atomic, atomic_bytes
from cabinet.predictive import ConditionBank
from v4_runtime.qualification import pinned_json


def publish(path, document, expected_sha256):
    import fcntl
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink() or path.parent.stat().st_mode & 0o022:
        raise ValueError('Private condition bank directory required')
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if current != expected_sha256:
            raise ValueError('Concurrent condition-bank change')
        data = json.dumps(document, sort_keys=True, allow_nan=False).encode()
        pin = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / 'bank.json';candidate.write_bytes(data)
            ConditionBank(candidate, pin)
        if path.exists():
            atomic_bytes(path.with_name(path.name + '.' + current + '.archived'),path.read_bytes())
        atomic(path, document)
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    print(publish(args.bank, pinned_json(args.candidate, args.candidate_sha256), args.expected_sha256))
