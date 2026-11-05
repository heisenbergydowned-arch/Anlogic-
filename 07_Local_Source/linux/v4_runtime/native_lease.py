"""Exclusive persistent native ownership; an unclean exit needs driver recovery."""
import json
import os
from pathlib import Path
import stat
import uuid

from .bundle import loads


NATIVE_LEASE_FILE = Path('/var/lib/cabinet/npu-lease/lease.json')


class NativeLease:
    def __init__(self, file=NATIVE_LEASE_FILE):
        import fcntl
        self.fd = None
        self.file = Path(file)
        self.file.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory = self.file.parent.lstat()
        if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid() or directory.st_mode & 0o077:
            raise ValueError('Native lease requires a private owned directory')
        descriptor = os.open(str(self.file), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Unsafe native lease file')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('NATIVE_OWNER_ACTIVE: another worker owns the native accelerator')
            data = os.read(descriptor, 4097)
            if len(data) > 4096:
                raise ValueError('Oversized native lease record')
            if data:
                previous = loads(data.decode('utf-8'))
                if type(previous) is not dict or previous.get('schema') != 'cabinet-native-lease-v1' or previous.get('state') != 'CLEAN':
                    raise RuntimeError('NATIVE_DIRTY_LATCHED: verify driver reset before manual lease recovery')
            self.fd = descriptor
            self.instance = uuid.uuid4().hex
            self.write('ACTIVE')
            parent = os.open(str(self.file.parent), os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        except BaseException:
            self.fd = None
            os.close(descriptor)
            raise

    def write(self, state):
        data = (json.dumps(dict(schema='cabinet-native-lease-v1', state=state,
            pid=os.getpid(), instance=self.instance,
            boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip() if Path('/proc/sys/kernel/random/boot_id').exists() else None))+'\n').encode()
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        offset = 0
        while offset < len(data):
            written = os.write(self.fd, data[offset:])
            if written <= 0:
                raise OSError('Native lease write failed')
            offset += written
        os.fsync(self.fd)

    def close(self, clean=False):
        if self.fd is not None:
            try:
                if clean:
                    self.write('CLEAN')
            finally:
                os.close(self.fd)
                self.fd = None
