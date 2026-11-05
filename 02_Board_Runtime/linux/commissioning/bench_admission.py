"""Admission before potentially unmapped BNC1 MMIO, bound to this OS/PL boot.

The installation procedure creates this receipt only after verifying the new
BOOT.bin and bitstream hashes and completing the corresponding reboot. This
is a trusted deployment attestation, not a capability probe or hardware trip.
This module never creates receipts and never touches BNC1 registers.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

ADMISSION_PATH=Path('/run/cabinet-bnc1-admission.json')
BOOT_ID_PATH=Path('/proc/sys/kernel/random/boot_id')
SCHEMA='cabinet-bnc1-boot-admission-v1'
VERIFICATION='VERIFIED_NEW_BOOT_ARTIFACTS_AND_CURRENT_BOOT'
ABI_VERSION=0x20000
AUTHORIZATION='REMOTE_BOUNDED_PWM'

def collector_identity(service):
    # Service.boot is device/cookie; observer.submit appends session UUID/epoch.
    # Bind the entire observer identity, so a collector restart/reconnect revokes it.
    base=getattr(service,'boot',None);session=getattr(service,'collector_session',None);epoch=getattr(service,'connection_epoch',None)
    if type(base) is not str or type(session) is not str or type(epoch) is not int or epoch<1:
        raise ValueError('BNC1_COLLECTOR_IDENTITY_REQUIRED')
    return base+'/'+session+'/'+str(epoch)

def collector_cookie(identity):
    if type(identity) is not str:raise ValueError('BNC1_COLLECTOR_IDENTITY_FORMAT')
    parts=identity.split('/')
    if (len(parts)!=4 or not re.fullmatch(r'[^/\s]{1,128}',parts[0]) or not re.fullmatch('[0-9a-f]{8}',parts[1])
            or str(uuid.UUID(parts[2]))!=parts[2] or not re.fullmatch('[1-9][0-9]*',parts[3])):
        raise ValueError('BNC1_COLLECTOR_IDENTITY_FORMAT')
    return int(parts[1],16)

def require_admission(collector_boot):
    try:
        fd=os.open(str(ADMISSION_PATH),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o600
                    or info.st_nlink!=1 or not 1<=info.st_size<=8192):
                raise ValueError('BNC1_BOOT_ADMISSION_UNSAFE')
            with os.fdopen(fd,'rb',closefd=False) as stream: raw=stream.read(8193)
        finally: os.close(fd)
        if len(raw)>8192: raise ValueError('BNC1_BOOT_ADMISSION_OVERSIZED')
        document=json.loads(raw.decode('utf-8'))
        fields={'schema','verification','abi_version','os_boot_id','collector_boot','pl_boot_cookie','boot_bin_sha256','bitstream_sha256'}
        if (type(document) is not dict or set(document)!=fields or document['schema']!=SCHEMA
                or document['verification']!=VERIFICATION or type(document['abi_version']) is not int
                or document['abi_version']!=ABI_VERSION):
            raise ValueError('BNC1_BOOT_ADMISSION_FORMAT')
        boot=BOOT_ID_PATH.read_text(encoding='utf-8').strip()
        if str(uuid.UUID(boot))!=boot or document['os_boot_id']!=boot: raise ValueError('BNC1_BOOT_ADMISSION_OLD_BOOT')
        cookie=collector_cookie(collector_boot)
        if (document['collector_boot']!=collector_boot or type(document['pl_boot_cookie']) is not int
                or document['pl_boot_cookie']!=cookie):
            raise ValueError('BNC1_BOOT_ADMISSION_OLD_COLLECTOR')
        if any(type(document[k]) is not str or not re.fullmatch('[0-9a-f]{64}',document[k])
               for k in ('boot_bin_sha256','bitstream_sha256')):
            raise ValueError('BNC1_BOOT_ADMISSION_ARTIFACT_HASH')
        return dict(document,receipt_sha256=hashlib.sha256(raw).hexdigest())
    except (OSError,UnicodeError,json.JSONDecodeError,KeyError,TypeError) as error:
        raise ValueError('BNC1_BOOT_ADMISSION_REQUIRED: '+str(error))
