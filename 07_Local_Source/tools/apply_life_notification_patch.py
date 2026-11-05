import argparse,hashlib,json,os,subprocess,tarfile,time
from pathlib import Path
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
ap=argparse.ArgumentParser();ap.add_argument('--sha',required=True);a=ap.parse_args()
archive=Path('/run/p52-life-patch.tar.gz');assert sha(archive)==a.sha
stage=Path('/run/p52-life-patch');stage.mkdir()
with tarfile.open(str(archive)) as tar:
    for item in tar.getmembers():assert not item.name.startswith('/') and '..' not in Path(item.name).parts
    tar.extractall(str(stage))
p=read(stage/'patch.json');root=Path('/opt/cabinet/releases/r46_alarm_only_pwm_p52_20261103')
assert Path('/opt/cabinet/linux').resolve()==root/'linux'
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==p['boot_id']
assert sha(root/'software_manifest.json')==p['before_manifest']
assert set(p['changes'])=={'cabinet/fan_life.py','tests/test_fan_life_p46.py','static/index.html'}
for name,h in p['changes'].items():
    assert sha(root/'linux'/name)==h['before'] and sha(stage/'linux'/name)==h['after']
assert sha(stage/'software_manifest.json')==p['after_manifest']
config_hash=sha('/etc/cabinet/fan-life.json');before=read('/var/lib/cabinet/fan-life/ledger.json')
subprocess.check_call(['systemctl','stop','cabinet-fan-life'])
try:
    for name in p['changes']:
        target=root/'linux'/name;temp=target.with_name(target.name+'.p52-new')
        with temp.open('wb') as stream:
            stream.write((stage/'linux'/name).read_bytes());stream.flush();os.fsync(stream.fileno())
        os.chmod(str(temp),0o644);os.replace(str(temp),str(target))
    target=root/'software_manifest.json';temp=target.with_name('software_manifest.next')
    with temp.open('wb') as stream:
        stream.write((stage/'software_manifest.json').read_bytes());stream.flush();os.fsync(stream.fileno())
    os.replace(str(temp),str(target));os.sync()
finally:subprocess.check_call(['systemctl','start','cabinet-fan-life'])
assert sha(root/'software_manifest.json')==p['after_manifest']
for name,h in p['changes'].items():assert sha(root/'linux'/name)==h['after']
assert sha('/etc/cabinet/fan-life.json')==config_hash
after=read('/var/lib/cabinet/fan-life/ledger.json')
assert before['reference']==after['reference'] and before['points']==after['points']
p.update(status='PASS_LIFE_NOTIFICATION_PATCH',settings_and_reference_preserved=True,pwm_service_restarted=False)
(root/'life_notification_patch.json').write_text(json.dumps(p,indent=2)+'\n')
print(json.dumps(p))
