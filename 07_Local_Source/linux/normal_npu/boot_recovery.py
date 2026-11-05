"""Recover a previous-boot lease only before any NPU use on a verified kernel.
Same-boot dirty leases are never cleared automatically. Preserve the old inode,
record and all rejection conditions; this is not a driver reset or a force kill.
"""
import argparse,fcntl,hashlib,json,os,stat,struct,subprocess,uuid
from pathlib import Path
from v4_runtime.native_lease import NATIVE_LEASE_FILE
from v4_runtime.bundle import loads

KERNEL='6.1.111-rt42-r46npu-candidate4+'
MODULES={'hard_npu':'d1aba09d62f40416a2295bcbaeb3d9e497477b11c34cb6c4121aca91d3f4dffc',
 'soft_npu':'a542040f37fef34cc890c7d4cdc1cc8a3badbb39aa08331c176239e5139145e1',
 'cma_mem':'6200a5652326af347461c8899db83c0d1a2b51700269e4fb133e2614fbc93af3'}

def digest(b):return hashlib.sha256(b).hexdigest()
def current_boot():return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def build_note(data):
    if data[:6]!=b'\x7fELF\x02\x01':raise ValueError('Expected ELF64 little endian kernel module')
    offset=struct.unpack_from('<Q',data,40)[0];size,count,names=struct.unpack_from('<HHH',data,58)
    if size!=64 or not 0<names<count:raise ValueError('Module section layout')
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,offset+i*size) for i in range(count)]
    table=sections[names];strings=data[table[4]:table[4]+table[5]]
    for s in sections:
        name=strings[s[0]:].split(b'\0',1)[0]
        if name==b'.note.gnu.build-id':return data[s[4]:s[4]+s[5]]
    raise ValueError('Module build identity missing')

def verified_fresh_driver():
    if os.geteuid()!=0 or os.uname().release!=KERNEL:raise ValueError('Reviewed board kernel and root required')
    modules={}
    for name,pin in MODULES.items():
        path=Path(subprocess.check_output(['modinfo','-n',name]).decode().strip())
        data=path.read_bytes();root=Path('/sys/module')/name
        if digest(data)!=pin or (root/'initstate').read_text().strip()!='live' or (root/'refcnt').read_text().strip()!='0':
            raise ValueError('Module changed or is in use: '+name)
        if build_note(data)!=(root/'notes/.note.gnu.build-id').read_bytes():raise ValueError('Loaded module differs: '+name)
        modules[name]=dict(path=str(path),sha256=pin,loaded_build_id_verified=True)
    irq={}
    for line in Path('/proc/interrupts').read_text().splitlines():
        if line.split() and line.split()[-1] in ('HARD_NPU_IRQ','SOFT_NPU_IRQ'):
            fields=line.split()[1:];counts=[]
            for x in fields:
                if not x.isdigit():break
                counts.append(int(x))
            irq[fields[-1]]=sum(counts)
    if irq!={'HARD_NPU_IRQ':0,'SOFT_NPU_IRQ':0}:raise ValueError('NPU already executed on this boot; manual recovery required')
    devices={'/dev/'+name for name in MODULES}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            for fd in (p/'fd').iterdir():
                try:target=os.readlink(str(fd))
                except FileNotFoundError:continue
                if target in devices:raise ValueError('NPU device held by PID '+p.name)
        except FileNotFoundError:continue
    if subprocess.run(['systemctl','is-active','--quiet','r46-npu-drivers']).returncode:
        raise ValueError('Reviewed driver startup has not completed')
    return dict(boot_id=current_boot(),kernel_release=KERNEL,module_pins=modules,irq=irq,device_owners=[])

def recovery_allowed(previous,boot,legacy_pin=None,legacy_boot=None,raw=None):
    uuid.UUID(boot)
    if type(previous) is not dict or previous.get('schema')!='cabinet-native-lease-v1' or previous.get('state') not in ('ACTIVE','CLEAN'):raise ValueError('Invalid native lease')
    if previous['state']=='CLEAN':return False
    previous_boot=previous.get('boot_id')
    if previous_boot is None:
        if not legacy_pin or not legacy_boot or raw is None or digest(raw)!=legacy_pin:raise ValueError('Legacy dirty lease needs an explicitly pinned migration')
        uuid.UUID(legacy_boot);previous_boot=legacy_boot
    else:uuid.UUID(previous_boot)
    if previous_boot==boot:raise ValueError('Same-boot dirty lease requires manual driver recovery')
    return True

def recover(file=NATIVE_LEASE_FILE,legacy_pin=None,legacy_boot=None):
    file=Path(file)
    if not file.exists() and not file.is_symlink():return dict(status='NO_PERSISTED_LEASE')
    directory=file.parent.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid!=os.getuid() or directory.st_mode&0o077:raise ValueError('Private lease directory required')
    fd=os.open(str(file),os.O_RDWR|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Private regular lease required')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        raw=os.read(fd,4097)
        if len(raw)>4096:raise ValueError('Oversized lease')
        previous=loads(raw.decode());boot=current_boot()
        if not recovery_allowed(previous,boot,legacy_pin,legacy_boot,raw):return dict(status='LEASE_ALREADY_CLEAN',boot_id=boot)
        proof=verified_fresh_driver()
        if proof['boot_id']!=boot:raise ValueError('Boot changed during recovery audit')
        history=file.parent/'boot-recovery';history.mkdir(mode=0o700,exist_ok=True)
        history_info=history.lstat()
        if not stat.S_ISDIR(history_info.st_mode) or history_info.st_uid!=os.getuid() or history_info.st_mode&0o077:raise ValueError('Private recovery history required')
        identity=uuid.uuid4().hex;backup=history/(boot+'-'+identity+'.json')
        record=dict(status='VERIFIED_PREVIOUS_BOOT_LEASE_RECOVERY',previous=previous,previous_sha256=digest(raw),proof=proof,legacy_previous_boot=legacy_boot)
        with os.fdopen(os.open(str(backup),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as out:
            json.dump(record,out,indent=2);out.flush();os.fsync(out.fileno())
        history_fd=os.open(str(history),os.O_RDONLY)
        try:os.fsync(history_fd)
        finally:os.close(history_fd)
        new=dict(schema='cabinet-native-lease-v1',state='CLEAN',pid=0,instance='',boot_id=boot,recovery=str(backup))
        data=(json.dumps(new)+'\n').encode();os.lseek(fd,0,os.SEEK_SET);os.ftruncate(fd,0)
        view=memoryview(data)
        while view:
            written=os.write(fd,view)
            if written<=0:raise OSError('Lease write failed')
            view=view[written:]
        os.fsync(fd)
        parent=os.open(str(file.parent),os.O_RDONLY)
        try:os.fsync(parent)
        finally:os.close(parent)
        return dict(status=record['status'],boot_id=boot,backup=str(backup),previous_sha256=digest(raw))
    finally:os.close(fd)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--legacy-sha256');p.add_argument('--legacy-boot');a=p.parse_args()
    print(json.dumps(recover(legacy_pin=a.legacy_sha256,legacy_boot=a.legacy_boot),indent=2))
if __name__=='__main__':main()
