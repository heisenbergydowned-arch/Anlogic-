import hashlib,json,os,subprocess,tarfile,time
from pathlib import Path
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
archive=Path('/run/p52-feedback-patch.tar.gz')
assert sha(archive)=='4a9594843d5ef38e93150a703fa2e1d53b2d446620efcbacaba827fe5e69af42'
stage=Path('/run/p52-feedback-patch');stage.mkdir()
with tarfile.open(str(archive)) as tar:
    for item in tar.getmembers():assert not item.name.startswith('/') and '..' not in Path(item.name).parts
    tar.extractall(str(stage))
p=read(stage/'patch.json');root=Path('/opt/cabinet/releases/r46_alarm_only_pwm_p52_20261103')
assert Path('/opt/cabinet/linux').resolve()==root/'linux'
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==p['boot_id']
assert sha(root/'software_manifest.json')==p['before_manifest']
assert set(p['changes'])=={'cabinet/temperature_pwm.py','tests/test_temperature_pwm_p39.py'}
for name,h in p['changes'].items():
    assert sha(root/'linux'/name)==h['before'] and sha(stage/'linux'/name)==h['after']
assert sha(stage/'software_manifest.json')==p['after_manifest']
def pid(unit):return int(subprocess.check_output(['systemctl','show',unit,'-p','MainPID','--value']))
old_pid=pid('cabinet-edge');npu_pid=pid('cabinet-normal-npu')
for name in list(p['changes'])+['../software_manifest.json']:
    target=root/'linux'/name;source=stage/'linux'/name
    if name.startswith('../'):source=stage/'software_manifest.json'
    temp=target.with_name(target.name+'.p52-new')
    with temp.open('wb') as stream:
        stream.write(source.read_bytes());stream.flush();os.fsync(stream.fileno())
    os.chmod(str(temp),0o644);os.replace(str(temp),str(target))
os.sync()
# Restart only the monitor process, preserving the running NPU service.
# Its systemd Restart=on-failure policy reloads the updated code after two seconds.
subprocess.check_call(['systemctl','kill','--kill-who=main','--signal=HUP','cabinet-edge'])
deadline=time.monotonic()+30
while time.monotonic()<deadline:
    try:
        new_pid=pid('cabinet-edge');v=read('/run/cabinet-live/state.json')['observation']
        c=v['control']['temperature_pwm']
        if new_pid and new_pid!=old_pid and c['state']=='RUNNING' and 0<=time.monotonic()-v['received_at']<1:break
    except (OSError,ValueError,KeyError):pass
    time.sleep(.2)
else:raise RuntimeError('Monitor did not resume the saved curve')
assert sha(root/'software_manifest.json')==p['after_manifest']
for name,h in p['changes'].items():assert sha(root/'linux'/name)==h['after']
p.update(status='PASS_FEEDBACK_COHERENCE_PATCH',old_monitor_pid=old_pid,new_monitor_pid=new_pid,
         npu_pid_before=npu_pid,npu_pid_after=pid('cabinet-normal-npu'),temperature_pwm=c)
(root/'feedback_coherence_patch.json').write_text(json.dumps(p,indent=2)+'\n')
print(json.dumps({k:v for k,v in p.items() if k!='temperature_pwm'}))
