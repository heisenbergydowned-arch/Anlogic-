"""Read-only deployed BOOT, software, saved settings, and real TPW1 readback."""
import hashlib,json,subprocess,time
from pathlib import Path
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
root=Path('/opt/cabinet/releases/r46_alarm_only_pwm_p52_20261103')
r=read(root/'boot_installation.json');boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert r['status']=='BOOT_AND_SOFTWARE_WRITTEN_READBACK_VERIFIED_REBOOT_REQUIRED' and boot!=r['boot_id']
assert r['timing_pass'] is False and r['user_authorized_setup_wns_ns']==-0.008
assert subprocess.check_output(['uname','-r']).decode().strip()=='6.1.111-rt42-r46npu-candidate4+'
assert Path('/opt/cabinet/linux').resolve()==root/'linux'
m=read(root/'software_manifest.json')
for name,h in m['candidate_files'].items():assert sha(root/'linux'/name)==h,name
for name,h in r['configured_files'].items():assert sha(name)==h,name
assert not any(line.split()[0]=='/dev/mmcblk0p1' for line in Path('/proc/mounts').read_text().splitlines())
p=Path('/run/p52-boot-readback');p.mkdir()
try:
 subprocess.check_call(['mount','-o','ro','/dev/mmcblk0p1',str(p)])
 actual={x.name:sha(x) for x in p.iterdir() if x.is_file()}
 assert actual['BOOT.bin']==r['new_boot_sha256']
finally:
 subprocess.check_call(['umount',str(p)]);p.rmdir()
v=read('/run/cabinet-live/state.json');o=v['observation'];s=o['status'];c=o['control']['temperature_pwm']
assert o['link']=='ONLINE' and 0<=time.monotonic()-o['received_at']<1
assert s['raw_words'][0]&(1<<22)
assert c['state']=='RUNNING' and c['hardware_supported'] and c['hardware_armed']
assert c['current_threshold_cutoff_enabled'] is False and c['applied_revision']==c['settings']['revision']
assert c['settings']['enabled'] is True and c['settings']['low_C']==25 and c['settings']['high_C']==80
assert c['current_sensor_cutoff_enabled'] is False
expected=max(0,min(100,(c['temperature_C']-25)*100/55))
assert abs(c['actual_pwm_percent']-expected)<1,(c,expected)
units={n:subprocess.run(['systemctl','is-active',n],stdout=subprocess.PIPE,universal_newlines=True).stdout.strip() for n in ['cabinet-edge','cabinet-normal-npu','cabinet-local-display','cabinet-commissioning-manager','cabinet-fan-life']}
assert all(units[n]=='active' for n in units if n!='cabinet-normal-npu')
n=read('/run/cabinet-normal-npu/state.json') if Path('/run/cabinet-normal-npu/state.json').exists() else dict(status='NO_LIVE_STATE',valid=False);life=read('/run/cabinet-fan-life/state.json')
if 'model_sha256' in n:assert n['model_sha256']=='5dff036e191b4b83aa327fb82c8456eb55fc24798882bef04a5d1e46304de749'
assert life['settings']['revision']==2 and life['settings']['nominal_hours']==5000
result=dict(status='PASS_P52_BOOT_RUNTIME_AND_SAVED_SETTINGS',timing_pass=False,setup_wns_ns=-.008,previous_boot_id=r['boot_id'],boot_id=boot,boot_files=actual,software_files_verified=len(m['candidate_files']),saved_config_files_verified=len(r['configured_files']),units=units,temperature_pwm=c,npu={k:n.get(k) for k in ['status','valid','model_sha256','inference_count','advisory']},life=life)
Path('/run/p52-postboot.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['life','temperature_pwm']}))
