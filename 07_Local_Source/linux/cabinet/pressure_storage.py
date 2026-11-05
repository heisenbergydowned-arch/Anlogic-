"""Private, verified filesystem generations for an explicitly configured SD directory."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from hmi_daily.cabinet.learning_web import strict_json


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


class PressureStorage:
    def __init__(self, directory):
        self.root = Path(directory)
        if not self.root.is_absolute() or '..' in self.root.parts:
            raise ValueError('Absolute private SD directory required')
        for component in [*reversed(self.root.parents), self.root]:
            if component.is_symlink():
                raise ValueError('Symlink storage path forbidden')
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('SD directory must be owned by service uid and mode 0700')
        self.lock_fd = os.open(str(self.root / '.owner'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            import fcntl
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.lock_fd)
            raise

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    def read(self, name):
        descriptor = os.open(str(self.root / name), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError('Unsafe SD record permissions/type')
            return strict_json(stream.read(262145), limit=262144)

    def sync(self):
        descriptor = os.open(str(self.root), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def atomic(self, name, document):
        temporary = '.pending-' + uuid.uuid4().hex
        descriptor = os.open(str(self.root / temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encode(document))
                stream.flush()
                os.fsync(stream.fileno())
            if self.read(temporary) != document:
                raise OSError('SD readback mismatch')
            os.replace(str(self.root / temporary), str(self.root / name))
            self.sync()
        finally:
            try:
                (self.root / temporary).unlink()
            except FileNotFoundError:
                pass

    def load(self, kind):
        if kind not in ('config', 'baseline'):
            raise ValueError('Unknown record kind')
        try:
            pointer = self.read(kind + '.active.json')
        except FileNotFoundError:
            return None
        if (type(pointer) is not dict or set(pointer) != {'schema', 'file', 'sha256'}
                or type(pointer['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', pointer['sha256']) or pointer['schema'] != 1
                or pointer['file'] != kind + '-' + pointer['sha256'] + '.json'):
            raise ValueError('Invalid SD active pointer')
        record = self.read(pointer['file'])
        if set(record) != {'schema', 'kind', 'payload', 'sha256'} or record['schema'] != 1 or record['kind'] != kind:
            raise ValueError('Invalid SD record')
        if digest(record['payload']) != record['sha256'] or record['sha256'] != pointer['sha256']:
            raise ValueError('Corrupt SD generation')
        return record['payload']

    def save(self, kind, payload, before_activate):
        if kind not in ('config', 'baseline'):
            raise ValueError('Unknown record kind')
        checksum = digest(payload)
        name = kind + '-' + checksum + '.json'
        record = dict(schema=1, kind=kind, payload=payload, sha256=checksum)
        self.atomic(name, record)
        if self.read(name) != record:
            raise OSError('SD generation verification failed')
        before_activate()
        self.atomic(kind + '.active.json', dict(schema=1, file=name, sha256=checksum))
        if self.load(kind) != payload:
            raise OSError('SD active verification failed; re-read state before retry')
        return checksum
