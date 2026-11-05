"""Explicit administrator-operated model activation, revocation and rollback."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from v4_runtime.bundle import Bundle
from v4_runtime.qualification import pinned_json, validate_evidence


def atomic_bytes(path, data):
    descriptor, name = tempfile.mkstemp(prefix='.pending-', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic(path, document):
    atomic_bytes(path,json.dumps(document,sort_keys=True,allow_nan=False).encode())


def transition(registry, action, expected_generation, release=None):
    registry = Path(registry)
    registry.mkdir(mode=0o700, parents=True, exist_ok=True)
    if registry.is_symlink() or registry.stat().st_mode & 0o022 or registry.stat().st_uid != os.geteuid():
        raise ValueError('Private administrator-owned registry required')
    with (registry / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = registry / 'active.json'
        old = pinned_json(path) if path.exists() else dict(generation=0, state='REVOKED')
        if old['generation'] != expected_generation:
            raise ValueError('Concurrent deployment change')
        if action not in ('activate', 'rollback', 'revoke'):
            raise ValueError('Unknown release transition')
        if action == 'revoke':
            new = dict(generation=expected_generation + 1, state='REVOKED')
        else:
            if type(release) is not dict or set(release) != {'bundle', 'manifest_sha256', 'directory', 'sha256'}:
                raise ValueError('Explicit pinned release required')
            if action == 'rollback' and not any(pinned_json(record).get('next',{}).get('receipt_sha256') == release['sha256']
                                                for record in registry.glob('transition-*.json')):
                raise ValueError('Rollback target has never been activated')
            bundle = Bundle(release['bundle'], release['manifest_sha256'], reviewed_admission=release)
            validate_evidence(release['directory'], release['sha256'],
                              dict(bundle.manifest, _pin=bundle.manifest_sha256), bundle.contract)
            new = dict(release, generation=expected_generation + 1, state='ACTIVE', receipt_sha256=release['sha256'])
        record = json.dumps(dict(previous=old, next=new, action=action), sort_keys=True).encode()
        identity = hashlib.sha256(record).hexdigest()
        atomic(registry / ('transition-' + identity + '.json'), json.loads(record))
        atomic(path, new)
        return new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['activate', 'rollback', 'revoke'])
    parser.add_argument('--registry', required=True)
    parser.add_argument('--expected-generation', type=int, required=True)
    parser.add_argument('--release', help='JSON file: bundle, manifest_sha256, directory, sha256')
    args = parser.parse_args()
    print(json.dumps(transition(args.registry, args.action, args.expected_generation,
                                pinned_json(args.release) if args.release else None), indent=2))


if __name__ == '__main__':
    main()
