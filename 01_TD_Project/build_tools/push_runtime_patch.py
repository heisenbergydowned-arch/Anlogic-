"""Hash-bound software patch for the current board, with local source receipt."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--tag',required=True)
p.add_argument('--restart-npu',action='store_true')
p.add_argument('--evidence',type=Path)
p.add_argument('paths',nargs='+')
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
evidence=a.evidence or Path((root/'evidence/current_pwm_sweep_path.txt').read_text())
ssh=['ssh','-o','BatchMode=yes','-o','HostKeyAlias=192.168.0.127','-o','StrictHostKeyChecking=yes',
     '-o','ConnectTimeout=6','root@192.168.0.107']

def remote(script):
    result=subprocess.run(ssh+['python3 -'],input=script,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,universal_newlines=True,timeout=150)
    if result.returncode:raise RuntimeError(result.stdout+'\n'+result.stderr)
    return json.loads(result.stdout)

before=remote('names='+repr(a.paths)+'\n'+'''from pathlib import Path
import json,hashlib,base64
r=Path('/opt/cabinet/linux').resolve()
assert Path('/etc/machine-id').read_text().strip()=='843ad8d6299240c898a32874a96fe333'
print(json.dumps({'root':str(r),'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'manifest':base64.b64encode((r.parent/'software_manifest.json').read_bytes()).decode(),
 'files':{n:base64.b64encode((r/n).read_bytes()).decode() for n in names}}))
''')
(evidence/(a.tag+'_before.json')).write_text(json.dumps(before))
files={name:base64.b64encode((root/'linux'/name).read_bytes()).decode() for name in a.paths}
payload=dict(before=before,files=files,restart_npu=a.restart_npu)
encoded=base64.b64encode(json.dumps(payload).encode()).decode()
result=remote("import base64,json\np=json.loads(base64.b64decode('"+encoded+"'))\n"+'''from pathlib import Path
import os,hashlib,subprocess,sys
r=Path('/opt/cabinet/linux').resolve();old=p['before']
assert str(r)==old['root'] and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==old['boot']
manifest=r.parent/'software_manifest.json'
assert manifest.read_bytes()==base64.b64decode(old['manifest'])
for name,data in old['files'].items():assert (r/name).read_bytes()==base64.b64decode(data)
sys.path.insert(0,str(r))
from normal_npu.learning import Learning
assert not Learning().busy()
s=json.loads(Path('/run/cabinet-live/npu_input.json').read_text())['observation']
assert not s['bench'].get('controls_enabled')
if p['restart_npu']:
 subprocess.check_call(['systemctl','stop','cabinet-normal-npu'],stdout=subprocess.DEVNULL)
 assert json.loads(Path('/var/lib/cabinet/npu-lease/lease.json').read_text())['state']=='CLEAN'
def replace(path,data):
 temp=path.with_name('.'+path.name+'.runtime-patch')
 with temp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.replace(str(temp),str(path))
 fd=os.open(str(path.parent),os.O_RDONLY);os.fsync(fd);os.close(fd)
m=json.loads(base64.b64decode(old['manifest']))
for name,data in p['files'].items():
 raw=base64.b64decode(data);compile(raw,str(r/name),'exec');replace(r/name,raw)
 m['candidate_files'][name]=hashlib.sha256(raw).hexdigest()
replace(manifest,(json.dumps(m,indent=2)+'\\n').encode())
subprocess.check_call(['systemctl','restart','cabinet-edge'],stdout=subprocess.DEVNULL)
subprocess.check_call(['systemctl','start','cabinet-local-display'],stdout=subprocess.DEVNULL)
if p['restart_npu']:
 subprocess.check_call(['systemctl','reset-failed','cabinet-normal-npu'],stdout=subprocess.DEVNULL)
 subprocess.check_call(['systemctl','start','cabinet-normal-npu'],stdout=subprocess.DEVNULL)
print(json.dumps({'state':'INSTALLED','files':{n:m['candidate_files'][n] for n in p['files']},
 'manifest':m,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}))
''')
(evidence/(a.tag+'_installed.json')).write_text(json.dumps(result,indent=2))
(root/'software_manifest.json').write_text(json.dumps(result['manifest'],indent=2)+'\n')
runtime=Path('/Users/heisenberg/Library/Application Support/CabinetCooling/runtime/p52_20261104T061735Z/linux')
for name in a.paths:shutil.copy2(root/'linux'/name,runtime/name)
print(json.dumps({k:v for k,v in result.items() if k!='manifest'},indent=2))
