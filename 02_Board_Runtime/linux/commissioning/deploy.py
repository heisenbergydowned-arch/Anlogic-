"""Explicit on-board commissioning with readback, preserved configs and no implicit arm."""
import copy,hashlib,json,os,shutil,subprocess,time,uuid
from pathlib import Path
from . import SOURCE
from .fit import sha,validate_control
from .measure import observation
from .runtime import read_control_words,validate_binding
from cabinet.io import open_controller
from hmi_daily.read_real import read_feature_configuration
from link_cli import pack_feature,commit_feature
from normal_npu.baseline_store import durable_atomic
from .configuration_permission import require_apply_permission,safe_start_values,REMOTE
from cabinet.normal_reference_guard import bench_reason

def atomic(path,data):
    durable_atomic(Path(path),data)
def json_write(path,value):atomic(path,(json.dumps(value,indent=2,allow_nan=False)+'\n').encode())
def run(args,check=True):
    r=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=40)
    if check and r.returncode:raise RuntimeError(r.stdout[-2000:])
    return r
def check(directory,pin):
    root=Path(directory)
    if sha(root/'manifest.json')!=pin:raise ValueError('Commissioning manifest pin differs')
    m=json.loads((root/'manifest.json').read_text())
    if m.get('schema')!='cabinet-commissioned-parameters-v1' or m.get('source')!=SOURCE:raise ValueError('Fixture or unknown source cannot be installed')
    expected={'control.json','feature.json','edge.armed.json','edge.standby.json','capture-contract.json','learning.json','parameter-envelope.json','fit-report.json'}
    if set(m.get('files_sha256',{}))!=expected:raise ValueError('Incomplete commissioned package')
    for n,h in m['files_sha256'].items():
        if (root/n).is_symlink() or sha(root/n)!=h:raise ValueError('Changed commissioning file: '+n)
    c=json.loads((root/'control.json').read_text());f=json.loads((root/'feature.json').read_text())
    armed=json.loads((root/'edge.armed.json').read_text());standby=json.loads((root/'edge.standby.json').read_text())
    cw,fw=validate_control(c),pack_feature(f);validate_binding(armed,cw,fw)
    if any(standby[k].get('enabled') is not False for k in ('control','temperature_loop','parameter_control')):raise ValueError('Standby must not enable control')
    if (armed['device_id']!=m['device_id'] or armed['control'].get('evidence')!=m['evidence_sha256'] or
            armed['temperature_loop'].get('evidence')!=m['evidence_sha256']):raise ValueError('Evidence binding differs')
    return root,m,c,fw,armed

def same_board(manifest):
    if 'machine:'+Path('/etc/machine-id').read_text().strip()!=manifest['device_id']:
        raise ValueError('Wrong physical board')

def matching_settings(active,template):
    # An independently admitted model may be installed after commissioning.
    # It must not prevent a local operator from disarming the PS controller.
    def normalized(config):
        result=copy.deepcopy(config);result.pop('model',None)
        control=result['control'];mode=control.pop('regulation_mode','temperature');target=control.pop('target_rpm',None)
        envelope=result['temperature_loop']
        if mode not in ('temperature','speed'):raise ValueError('Unknown regulation mode')
        if target is not None and (type(target) is not int or not envelope['rpm_min']<=target<=envelope['rpm_max']):raise ValueError('RPM target outside measured envelope')
        return result
    return normalized(active)==normalized(template)

def apply(directory,pin,expected_authorization=None):
    root,m,c,fw,armed=check(directory,pin)
    if os.geteuid()!=0:raise ValueError('On-board administrator required')
    same_board(m)
    edge=Path('/etc/cabinet/edge.json');base=json.loads(edge.read_text())
    allowed=(m['base_config_sha256'],m['files_sha256']['edge.standby.json'],m['files_sha256']['edge.armed.json'])
    standby=json.loads((root/'edge.standby.json').read_text())
    if sha(edge) not in allowed and not any(matching_settings(base,t) for t in (armed,standby)):
        raise ValueError('Configuration changed; rebuild against the current configuration')
    preserve_formal=(base.get('commissioning')==armed['commissioning'] and base.get('model',{}).get('qualified') is True)
    if preserve_formal:standby['model']=base['model']
    d,o,s=observation('/run/cabinet-live/state.json');safe_start_values(s,c)
    reset_restore=base['control']['enabled'] and s.get('configured') is False and s.get('configuration_id')==0
    if s['applied_pwm_counts']!=0 or (base['control']['enabled'] and not reset_restore) or d['display'].get('capture_state')=='RECORDING':raise ValueError('Stop data capture and disarm control before applying')
    package=(root,m,c,fw,armed)
    received=o.get('received_at')
    age=(time.monotonic()-received)*1000 if type(received) in (int,float) else None
    permission=require_apply_permission(s,o.get('control',{}).get('control_words'),age,package,o.get('feature_words'))
    if expected_authorization is not None and permission['authorization']!=expected_authorization:
        raise ValueError('Confirmed configuration authorization changed; preview again')
    if permission['authorization']==REMOTE and bench_reason(o.get('bench')):
        raise ValueError('Stop the open-loop bench trial first and confirm its output readback')
    target=Path('/etc/cabinet/commissioned')/m['evidence_sha256']
    backup=Path('/var/lib/cabinet/commissioning')/(m['evidence_sha256']+'-'+str(int(time.time()))+'-'+uuid.uuid4().hex)
    backup.mkdir(parents=True,mode=0o700)
    for name in ('edge.json','capture-contract.json','learning.json'):
        shutil.copy2('/etc/cabinet/'+name,str(backup/name))
    if not target.exists():shutil.copytree(str(root),str(target))
    for n,h in m['files_sha256'].items():
        if sha(target/n)!=h:raise ValueError('Stored package changed')
    record=dict(status='PREPARED',manifest_sha256=pin,package=str(target),configuration_backup=str(backup),arm_requested=False,apply_permission=permission)
    json_write(backup/'transaction.json',record)
    ctrl=None;changed=False
    formal_was_active=run(['systemctl','is-active','cabinet-npu-formal'],False).stdout.strip()=='active'
    run(['systemctl','stop','cabinet-normal-npu','cabinet-npu-formal','cabinet-npu-v4-shadow'],False)
    lease=Path('/var/lib/cabinet/npu-lease/lease.json')
    if lease.exists() and json.loads(lease.read_text())['state']!='CLEAN':raise ValueError('Native cleanup not verified; preserve the retained worker')
    run(['systemctl','stop','cabinet-local-display','cabinet-edge'])
    try:
        # Even a failed restore must restart a read-only owner, not the old arm flag.
        json_write('/etc/cabinet/edge.json',standby)
        for source,dest in [('capture-contract.json','capture-contract.json'),('learning.json','learning.json')]:
            atomic('/etc/cabinet/'+dest,(target/source).read_bytes())
        ctrl=open_controller(base);sample_started=time.monotonic();s=ctrl.status()
        from hmi_daily.read_real import normalize_status
        s=normalize_status(s,keep_raw=True);safe_start_values(s,c)
        old_control=read_control_words(ctrl.io);old_feature=read_feature_configuration(ctrl.io)
        current_permission=require_apply_permission(s,old_control,(time.monotonic()-sample_started)*1000,package,old_feature)
        if current_permission['authorization']!=permission['authorization'] or s['applied_pwm_counts']!=0:
            raise ValueError('Configuration permission changed or output is active; preview again')
        record.update(control_before=old_control,feature_before=old_feature);json_write(backup/'transaction.json',record)
        cw=validate_control(c)
        if old_feature!=fw:
            # The installed PL requires a NEW feature ID at every commit. Use
            # an explicitly unqualified intermediate only while the collector
            # and actuator owner are stopped; final V4 ID remains compatible.
            if old_feature[0]==fw[0]:
                intermediate=list(fw);intermediate[0]=(fw[0]^0x80000000) or 1;intermediate[1]=intermediate[2]=0
                commit_feature(ctrl,intermediate);changed=True
            commit_feature(ctrl,fw);changed=True
        if old_control!=cw:
            for i,word in enumerate(cw):ctrl.io.write(0x300+4*i,word)
            ctrl.io.write(0x18,0x434f4d54);changed=True
        validate_binding(armed,read_control_words(ctrl.io),read_feature_configuration(ctrl.io))
        ctrl.close();ctrl=None
        json_write('/etc/cabinet/edge.json',standby)
        for source,dest in [('capture-contract.json','capture-contract.json'),('learning.json','learning.json')]:
            atomic('/etc/cabinet/'+dest,(target/source).read_bytes())
        run(['systemctl','disable','cabinet-normal-npu'],False)
        if not preserve_formal:run(['systemctl','disable','cabinet-npu-formal'],False)
        run(['systemctl','start','cabinet-edge','cabinet-local-display'])
        if preserve_formal and formal_was_active:run(['systemctl','start','cabinet-npu-formal'])
        record.update(status='PARAMETERS_APPLIED_CONTROL_DISARMED',registers_verified=True,control_enabled=False)
        json_write(backup/'transaction.json',record);return record
    except BaseException as error:
        if ctrl is not None:ctrl.close()
        # Keep the disabled owner on error; never issue an unqualified target
        # or reuse the old model under a new calibration identity.
        record.update(status='COMMISSIONING_INCOMPLETE_CONTROL_DISARMED',error=repr(error),hardware_words_changed=changed)
        json_write(backup/'transaction.json',record)
        run(['systemctl','start','cabinet-edge','cabinet-local-display'],False)
        raise

def arm(directory,pin,confirmed=False,mode='temperature',target_rpm=None):
    root,m,c,fw,armed=check(directory,pin)
    if os.geteuid()!=0 or not confirmed:raise ValueError('Explicit --start-controlled-trial required on the board')
    same_board(m)
    if mode not in ('temperature','speed'):raise ValueError('Unknown regulation mode')
    if mode=='speed' and (type(target_rpm) is not int or not c['rpm_min']<=target_rpm<=c['rpm_max']):raise ValueError('Fixed RPM target outside measured envelope')
    if mode=='temperature' and target_rpm is not None:raise ValueError('Temperature regulation derives its RPM target')
    d,o,s=observation('/run/cabinet-live/state.json');safe_start_values(s,c,allow_expired_owner=True)
    if d['display'].get('capture_state')=='RECORDING':raise ValueError('Stop the active data capture before changing control mode')
    active=json.loads(Path('/etc/cabinet/edge.json').read_text())
    if not matching_settings(active,json.loads((root/'edge.standby.json').read_text())):raise ValueError('Apply this exact package in standby first')
    armed['model']=active['model']
    armed['control'].update(regulation_mode=mode,target_rpm=target_rpm if mode=='speed' else armed['temperature_loop']['startup_rpm'])
    control=o.get('control',{})
    validate_binding(armed,control.get('control_words'),o.get('feature_words'))
    run(['systemctl','stop','cabinet-local-display','cabinet-edge'])
    try:
        json_write('/etc/cabinet/edge.json',armed)
        run(['systemctl','start','cabinet-edge','cabinet-local-display'])
    except BaseException as error:
        try:
            # A rename may have succeeded before fsync reports failure.
            # Restore the exact standby selection on either write or start
            # failure; an unsuccessful restore must never be called disarmed.
            json_write('/etc/cabinet/edge.json',active)
            run(['systemctl','start','cabinet-edge','cabinet-local-display'])
        except BaseException as rollback_error:
            raise RuntimeError('CONTROL_ARM_FAILED_ROLLBACK_REQUIRES_REVIEW: '+repr(rollback_error)) from error
        raise
    return dict(status='CONTROLLED_TRIAL_REQUESTED',regulation_mode=mode,configured_startup_rpm=armed['control']['target_rpm'],
                physical_closed_loop_accepted=False,next='Record and evaluate real control traces before accepting performance')

def disarm(directory,pin):
    root,m,c,fw,armed=check(directory,pin)
    if os.geteuid()!=0:raise ValueError('On-board administrator required')
    same_board(m)
    active=json.loads(Path('/etc/cabinet/edge.json').read_text());standby=json.loads((root/'edge.standby.json').read_text())
    if not any(matching_settings(active,t) for t in (armed,standby)):raise ValueError('Wrong active parameter package')
    standby['model']=active['model'];json_write('/etc/cabinet/edge.json',standby)
    run(['systemctl','restart','cabinet-edge','cabinet-local-display'])
    return dict(status='PS_CONTROL_DISARMED_PL_PROTECTION_REMAINS',power_disconnected=False,pwm_zero_guaranteed=False,
        note='FPGA retains its independent protection/fallback; use local maintenance and physical isolation for recalibration')
