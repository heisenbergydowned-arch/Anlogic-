"""Observe the sole collector's fresh real PL identity before loading Alnpu."""
import os
from pathlib import Path
import platform
import stat
import time

from .profiles import PL_BUILD_ID


def check_observation(document, now):
    sample = document.get('observation') if type(document) is dict else None
    if type(sample) is not dict or sample.get('link') != 'ONLINE':
        raise ValueError('A live observation from the sole collector is required')
    received = sample.get('received_at')
    if type(received) not in (float, int) or not 0 <= now - received <= 2:
        raise ValueError('Collector observation is stale')
    frame = sample.get('frame')
    header = frame.get('header') if type(frame) is dict else None
    if type(header) is not list or len(header) != 32 or any(type(value) is not int or not 0 <= value <= 0xffffffff for value in header):
        raise ValueError('Original PL frame header is required')
    if header[:3] != [0x46524d31, 0x10000, 284] or header[26] != PL_BUILD_ID:
        raise ValueError('Running PL is not the restricted R30 build')
    if header[27] or header[15] & 0x4000 or frame.get('state') != 'RECEIVED_REAL':
        raise ValueError('A TEST frame cannot establish real PL identity')
    uptime = sample.get('status', {}).get('uptime_ms')
    if type(uptime) is not int or not 0 <= uptime <= 0xffffffff or ((uptime - header[4]) & 0xffffffff) > 1000:
        raise ValueError('The observed PL frame is stale')
    return dict(pl_build_id=PL_BUILD_ID, frame_id=header[3], collector_boot=sample.get('boot'))


def verify_platform_state(path):
    if platform.system() != 'Linux' or platform.machine().lower() not in ('aarch64', 'arm64'):
        raise ValueError('Actual ARM64 Linux is required for Alnpu loading')
    from .bundle import loads
    descriptor = os.open(str(Path(path)), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022 or not 0 < info.st_size <= 1048576:
            raise ValueError('Collector state requires a private owned regular file')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            document = loads(stream.read(1048577).decode('utf-8'))
    finally:
        os.close(descriptor)
    return check_observation(document, time.monotonic())
