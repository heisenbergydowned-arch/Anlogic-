"""Install only reviewed startup/display changes and preserve model/data bytes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

stage=Path(sys.argv[1]);plan=json.loads((stage/'plan.json').read_text())
root=Path('/opt/cabinet/releases/r46_alarm_only_pwm_p52_20261103');code=root/'linux'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert Path('/opt/cabinet/linux').resolve()==code
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==plan['boot_id']
assert sha(root/'software_manifest.json')==plan['before_manifest']
sys.path.insert(0,str(code))
from normal_npu.learning import Learning
assert not Learning().busy()
assert json.loads(Path('/var/lib/cabinet/npu-lease/lease.json').read_text())['state']=='CLEAN'
for name,pin in plan['preserved_files'].items():assert sha(name)==pin,name
for name,pins in plan['changes'].items():
    target=code/name
    assert (sha(target) if target.exists() else None)==pins['before'],name
    assert sha(stage/'linux'/name)==pins['after'],name
assert sha(stage/'software_manifest.json')==plan['after_manifest']

def run(*args):
    print('RUN '+' '.join(args),flush=True)
    subprocess.check_call(list(args),timeout=110)

def replace(source,target):
    mode=target.stat().st_mode & 0o777 if target.exists() else 0o644
    fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',dir=str(target.parent))
    with os.fdopen(fd,'wb') as stream:
        stream.write(source.read_bytes());stream.flush();os.fsync(stream.fileno())
    os.chmod(tmp,mode);os.replace(tmp,str(target))
    fd=os.open(str(target.parent),os.O_RDONLY);os.fsync(fd);os.close(fd)

run('systemctl','stop','cabinet-normal-npu','cabinet-local-display')
for name in plan['changes']:replace(stage/'linux'/name,code/name)
replace(stage/'software_manifest.json',root/'software_manifest.json')
print('REVIEWED_FILES_INSTALLED',flush=True)
# P52 shutdown preserves autonomous TPW1, and startup reattaches to its saved revision.
run('systemctl','restart','cabinet-edge')
run('systemctl','start','cabinet-local-display')
run('systemctl','reset-failed','cabinet-normal-npu')
run('systemctl','start','cabinet-normal-npu')
for name,pin in plan['preserved_files'].items():assert sha(name)==pin,name
for name,pins in plan['changes'].items():assert sha(code/name)==pins['after'],name
receipt=dict(status='INSTALLED_NPU_STARTUP_FIX_DATA_PRESERVED',boot_id=plan['boot_id'],
             before_manifest=plan['before_manifest'],after_manifest=plan['after_manifest'],
             changes=plan['changes'],preserved_file_count=len(plan['preserved_files']))
(root/'npu_startup_patch.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
