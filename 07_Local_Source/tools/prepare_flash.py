import hashlib,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'r46_temperature_no_current_trip_p50_20261103'
SOFTWARE=OLD
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())
p=read(ROOT/'boot_package_candidate/validation.json');n=read(ROOT/'reports/build_008/validation.json')
assert p['status']=='P52_ALARM_ONLY_PWM_BOOT_PS_UNCHANGED_NOT_FLASHED'
assert n['status']=='BUILT_P52_ALARM_ONLY_PWM'
assert p['boot_sha256']==sha(ROOT/'boot_package_candidate/BOOT.bin') and p['bit_sha256']==n['bit_sha256']
s=read(ROOT/'software_manifest.json');old=read(SOFTWARE/'software_manifest.json')
for name,h in s['candidate_files'].items():assert sha(ROOT/'linux'/name)==h,name
out=ROOT/'deployment';out.mkdir()
m=dict(installer_sha256=sha(ROOT/'tools/install_boot.py'),active_runtime='/opt/cabinet/releases/r46_temperature_no_current_trip_p50_20261103/linux',new_runtime='/opt/cabinet/releases/r46_alarm_only_pwm_p52_20261103/linux',new_boot_sha256=p['boot_sha256'],old_boot_sha256=p['old_boot_sha256'],old_boot_files=read(OLD/'evidence/p50-postboot.json')['boot_files'],software_files=old['candidate_files'],new_software_files=s['candidate_files'],new_software_manifest_sha256=sha(ROOT/'software_manifest.json'),package_status=p['status'],native_status=n['status'],timing_pass=False,user_authorized_setup_wns_ns=-.008)
(out/'flash_manifest.json').write_text(json.dumps(m,indent=2)+'\n')
with tarfile.open(out/'flash_payload.tar.gz','w:gz') as a:
 for path,name in [(ROOT/'boot_package_candidate/BOOT.bin','BOOT.bin'),(OLD/'boot_package_candidate/BOOT.bin','rollback.BOOT.bin'),(ROOT/'tools/install_boot.py','install_boot.py'),(out/'flash_manifest.json','flash_manifest.json'),(ROOT/'software_manifest.json','software_manifest.json')]:a.add(path,arcname=name)
 for name in s['candidate_files']:a.add(ROOT/'linux'/name,arcname='linux/'+name)
r=dict(status='READY_P52_PAIRED_BOOT_AND_SOFTWARE_NOT_FLASHED',manifest_sha256=sha(out/'flash_manifest.json'),payload_sha256=sha(out/'flash_payload.tar.gz'),new_boot_sha256=p['boot_sha256'],software_manifest_sha256=sha(ROOT/'software_manifest.json'))
(out/'package.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
