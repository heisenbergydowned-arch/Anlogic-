"""Board-side exact PL-only update, with saved configuration and SD readback checks."""
import argparse
import shutil
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def require(ok,why):
    if not ok:raise RuntimeError(why)
def run(args,timeout=100):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=timeout)
    require(p.returncode==0,repr(args)+': '+p.stdout[-1200:]);return p.stdout
def config_inventory():
    return {str(p):sha(p) for p in Path('/etc/cabinet').rglob('*') if p.is_file()}
def live():
    v=read('/run/cabinet-live/state.json');o=v['observation'];s=o['status']
    require(o['link']=='ONLINE' and 0<=time.monotonic()-o['received_at']<1,'Stale live collector')
    require(s['applied_pwm_counts']==0 and s['hard_inhibit'] is True and s['requested_rpm']==0 and s['configured'] is False,'Output must already be inhibited at zero')
    c=read('/etc/cabinet/temperature-pwm.json')
    require(c['enabled'] is True and c['low_C']==25 and c['high_C']==80,'Saved default curve changed')
    require(s['input_validity']['temperature'] and -55<=s['temp_raw_1_16_C']/16.<=125,'Fresh valid temperature input required before zero-output update')
    require(o['control']['temperature_pwm']['state']=='FAULT_LATCHED' and o['control']['temperature_pwm']['faults']==['ADC_INVALID'],'Require the observed zero-output ADC latch before this update')
    require(not o.get('bench',{}).get('controls_enabled'),'Bench in progress')
    require(v['display'].get('capture_state')!='RECORDING','Capture in progress')
    return v

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',type=Path,required=True);ap.add_argument('--manifest-sha256',required=True);ap.add_argument('--apply',action='store_true');a=ap.parse_args()
    stage=a.stage;require(sha(stage/'flash_manifest.json')==a.manifest_sha256,'Flash manifest changed');m=read(stage/'flash_manifest.json')
    require(m['installer_sha256']==sha(__file__),'Installer changed')
    require(sha(stage/'BOOT.bin')==m['new_boot_sha256'],'Candidate BOOT changed')
    require(sha(stage/'rollback.BOOT.bin')==m['old_boot_sha256'],'Mac recovery copy changed')
    require(m['package_status']=='P52_ALARM_ONLY_PWM_BOOT_PS_UNCHANGED_NOT_FLASHED','No partition-reviewed candidate')
    require(m['native_status']=='BUILT_P52_ALARM_ONLY_PWM','No accepted routed candidate')
    require(str(Path('/opt/cabinet/linux').resolve())==m['active_runtime']=='/opt/cabinet/releases/r46_temperature_no_current_trip_p50_20261103/linux','Wrong active software')
    require(run(['uname','-r']).strip()=='6.1.111-rt42-r46npu-candidate4+','Stable kernel changed')
    for n,h in m['software_files'].items():require(sha(Path('/opt/cabinet/linux')/n)==h,'Runtime drift: '+n)
    require(m['timing_pass'] is False and m['user_authorized_setup_wns_ns']==-0.008,'Missing explicit experimental timing declaration')
    state=live();protected=config_inventory();cfg=read('/etc/cabinet/edge.json')
    require(not cfg['control']['enabled'] and not cfg['temperature_loop']['enabled'],'Legacy PI enabled')
    require(not any(l.split()[0]=='/dev/mmcblk0p1' for l in Path('/proc/mounts').read_text().splitlines()),'Boot partition already mounted')
    new_release=Path(m['new_runtime']).parent
    require(not new_release.exists(),'P52 release already exists; inspect before retry')
    require(sha(stage/'software_manifest.json')==m['new_software_manifest_sha256'],'New software manifest changed')
    for name,h in m['new_software_files'].items():require(sha(stage/'linux'/name)==h,'New software changed: '+name)
    new_release.mkdir(parents=True)
    shutil.copytree(str(stage/'linux'),str(new_release/'linux'))
    shutil.copy2(str(stage/'software_manifest.json'),str(new_release/'software_manifest.json'))
    for name,h in m['new_software_files'].items():require(sha(new_release/'linux'/name)==h,'Staged release readback: '+name)
    mount=Path('/run/p52-tpw1-flash-mount');mount.mkdir();mounted=False;services_stopped=False;software_switched=False
    report=dict(status='PREFLIGHT_PASS',boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),manifest_sha256=a.manifest_sha256,
                previous_boot_sha256=m['old_boot_sha256'],new_boot_sha256=m['new_boot_sha256'],temperature_C=state['observation']['status']['temp_raw_1_16_C']/16.,
                kernel_modified=False,baseline_modified=False,timing_pass=False,user_authorized_setup_wns_ns=-0.008,configured_files=protected)
    try:
        run(['mount','-o','ro','/dev/mmcblk0p1',str(mount)]);mounted=True
        require(sha(mount/'BOOT.bin')==m['old_boot_sha256'],'Current SD BOOT differs from captured rollback')
        before={p.name:sha(p) for p in mount.iterdir() if p.is_file()};require(before==m['old_boot_files'],'Boot files changed')
        if not a.apply:print(json.dumps(report));return
        live()
        services_stopped=True
        for unit in ('cabinet-fan-life','cabinet-commissioning-manager','cabinet-normal-npu'):run(['systemctl','stop',unit])
        require(read('/var/lib/cabinet/npu-lease/lease.json')['state']=='CLEAN','NPU lease not released')
        run(['systemctl','stop','cabinet-edge'])
        require(config_inventory()==protected,'Saved configuration changed during preflight')
        run(['mount','-o','remount,rw',str(mount)])
        new=mount/'.TPW1_BOOT.new';require(not new.exists(),'Unexpected staged boot file')
        fd=os.open(str(new),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write((stage/'BOOT.bin').read_bytes());f.flush();os.fsync(f.fileno())
        require(sha(new)==m['new_boot_sha256'],'Staged SD readback mismatch')
        os.replace(str(new),str(mount/'BOOT.bin'))
        fd=os.open(str(mount),os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        os.sync();run(['umount',str(mount)]);mounted=False
        run(['mount','-o','ro','/dev/mmcblk0p1',str(mount)]);mounted=True
        expected=dict(before);expected['BOOT.bin']=m['new_boot_sha256']
        require({p.name:sha(p) for p in mount.iterdir() if p.is_file()}==expected,'SD remount verification failed')
        require(config_inventory()==protected,'User calibration or model selection changed')
        link=Path('/opt/cabinet/.linux-p52-new')
        require(not link.exists() and not link.is_symlink(),'Pending runtime link exists')
        link.symlink_to(m['new_runtime']);os.replace(str(link),'/opt/cabinet/linux');software_switched=True
        require(str(Path('/opt/cabinet/linux').resolve())==m['new_runtime'],'Runtime link readback')
        os.sync()
        report.update(status='BOOT_AND_SOFTWARE_WRITTEN_READBACK_VERIFIED_REBOOT_REQUIRED',new_runtime=m['new_runtime'],software_manifest_sha256=m['new_software_manifest_sha256'])
        (new_release/'boot_installation.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k!='configured_files'}),flush=True)
    except BaseException as error:
        report.update(status='FLASH_FAILED',error=repr(error))
        if services_stopped:
            try:
                if software_switched:
                    back=Path('/opt/cabinet/.linux-p52-rollback');back.symlink_to(m['active_runtime']);os.replace(str(back),'/opt/cabinet/linux')
                if not mounted:
                    run(['mount','-o','ro','/dev/mmcblk0p1',str(mount)]);mounted=True
                if sha(mount/'BOOT.bin')!=m['old_boot_sha256']:
                    run(['mount','-o','remount,rw',str(mount)])
                    recovery=mount/'.TPW1_BOOT.rollback'
                    fd=os.open(str(recovery),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'wb') as f:f.write((stage/'rollback.BOOT.bin').read_bytes());f.flush();os.fsync(f.fileno())
                    require(sha(recovery)==m['old_boot_sha256'],'Recovery copy readback failed')
                    os.replace(str(recovery),str(mount/'BOOT.bin'));os.sync()
                    run(['umount',str(mount)]);mounted=False
                    run(['mount','-o','ro','/dev/mmcblk0p1',str(mount)]);mounted=True
                require(sha(mount/'BOOT.bin')==m['old_boot_sha256'],'Original BOOT not recovered')
                report['status']='FLASH_FAILED_ORIGINAL_BOOT_VERIFIED'
                for unit in ('cabinet-edge','cabinet-commissioning-manager','cabinet-fan-life'):run(['systemctl','start',unit])
                require(read('/var/lib/cabinet/npu-lease/lease.json')['state']=='CLEAN','NPU recovery requires clean lease')
                run(['systemctl','start','cabinet-normal-npu'])
                report['runtime_restored']=True
            except BaseException as recovery_error:report['recovery_error']=repr(recovery_error)
        Path('/opt/cabinet/releases/r46_temperature_no_current_trip_p50_20261103/boot_failure.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k!='configured_files'}),flush=True)
        raise
    finally:
        if mounted:run(['umount',str(mount)])
        mount.rmdir()
    # Caller retains the reviewable write receipt before requesting a reboot.

if __name__=='__main__':main()
