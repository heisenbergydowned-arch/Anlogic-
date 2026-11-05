"""Durable operator requests for the separate commissioning service.

The HTTP/collector process never stops itself or opens a second MMIO owner.
Only a freshly confirmed, boot-bound job may call the existing guarded deployer.
"""
import copy,json,os,re,time,uuid
from pathlib import Path
from .deploy import check,json_write,matching_settings
from .fit import sha
from cabinet.normal_reference_guard import bench_reason
from .configuration_permission import configuration_policy,require_apply_permission

ID=re.compile(r'^[0-9a-f]{32}$')
MANAGER_STATE=Path('/run/cabinet-commissioning/state.json')

def boot_id():return Path('/proc/sys/kernel/random/boot_id').read_text(encoding='utf-8').strip()
def document(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def nameplate(root):
    path=Path(root)/'fan-nameplate.json'
    if not path.exists():return None
    if path.is_symlink():raise ValueError('Regular nameplate record required')
    data=document(path)
    if data.get('source')!='USER_DECLARED_NAMEPLATE_NOT_CALIBRATION' or type(data.get('rated_speed_rpm')) is not int or data['rated_speed_rpm']<=0:
        raise ValueError('Invalid fan nameplate record')
    return data
def check_nameplate(root,package):
    data=nameplate(root)
    if data and package[2]['rpm_max']>data['rated_speed_rpm']:raise ValueError('Measured RPM envelope exceeds the declared rated speed')
def job_directory(root,identity):
    if type(identity) is not str or not ID.fullmatch(identity):raise ValueError('Known fit job required')
    path=Path(root)/'jobs'/identity
    if path.is_symlink() or path.resolve().parent!=(Path(root)/'jobs').resolve():raise ValueError('Regular fit job required')
    return path

def fitted(root,identity):
    folder=job_directory(root,identity)
    if not folder.is_dir() or not (folder/'job.json').is_file():raise ValueError('Known completed fit job required')
    job=document(folder/'job.json')
    if job.get('id')!=identity or job.get('operation')!='fit' or job.get('state')!='COMPLETED':raise ValueError('A completed measured fit is required')
    path=folder/'fitted'
    if path.is_symlink():raise ValueError('Regular fitted package required')
    pin=job.get('result',{}).get('manifest_sha256')
    package=check(path,pin)
    return job,path,pin,package

def manager_alive():
    try:
        state=document(MANAGER_STATE)
        return state.get('boot_id')==boot_id() and 0<=time.monotonic()-state['updated_at']<3
    except (OSError,ValueError,KeyError,TypeError):return False

class ControlJobs:
    def __init__(self,workbench):
        self.workbench=workbench;self.queue=workbench.root/'control-queue'
        if self.queue.is_symlink():raise ValueError('Regular control queue required')
        self.queue.mkdir(mode=0o700,exist_ok=True);self.preview=None
    def records(self):
        result=[]
        for path in sorted(self.queue.glob('*.json'))[-100:]:
            if path.is_symlink():raise ValueError('Regular control job required')
            result.append(document(path))
        return result
    def summary(self):
        workbench=self.workbench;base=document(workbench.base)
        completed=[];feature_targets=[]
        for folder in sorted((workbench.root/'jobs').iterdir()):
            if not ID.fullmatch(folder.name) or not (folder/'job.json').is_file():continue
            job=document(folder/'job.json')
            if job.get('operation')!='fit' or job.get('state')!='COMPLETED':continue
            try:
                unused,path,pin,package=fitted(workbench.root,folder.name)
                feature_targets.append(package[3])
                manifest=package[1];armed=package[4];standby=document(path/'edge.standby.json')
                applied=base.get('commissioning')==armed.get('commissioning') and any(matching_settings(base,t) for t in (armed,standby))
                completed.append(dict(id=folder.name,manifest_sha256=pin,evidence_sha256=manifest['evidence_sha256'],
                    applied=applied,rpm_min=package[2]['rpm_min'],rpm_max=package[2]['rpm_max'],startup_rpm=armed['temperature_loop']['startup_rpm']))
            except (OSError,ValueError,KeyError,TypeError):continue
        live=workbench.service.public_state() if workbench.service else {};status=live.get('status') or {}
        raw=status.get('raw_words') or []
        try:permission=configuration_policy(status,live.get('control_words',live.get('control',{}).get('control_words')),live.get('status_age_ms'))
        except (ValueError,TypeError):permission=dict(remote_initial_config_supported=False,initial_config_eligible=False,local_permission=False,authorization=None,local_key_required=True,remote_initial_configuration_ready=False,reason='LIVE_CONFIGURATION_PERMISSION_UNAVAILABLE')
        active_feature=live.get('feature_words')
        if permission.get('remote_initial_configuration_ready') and (type(active_feature) is not list or len(active_feature)!=17):
            permission.update(authorization='LOCAL_MAINTENANCE' if permission['local_permission'] else None,
                local_key_required=True,remote_initial_configuration_ready=False,reason='INITIAL_CONFIGURATION_FEATURE_READBACK_REQUIRED')
        if (permission.get('remote_initial_configuration_ready') and type(active_feature) is list
                and len(active_feature)==17 and (active_feature[1]!=0 or active_feature[2]!=0)
                and active_feature not in feature_targets):
            permission.update(authorization='LOCAL_MAINTENANCE' if permission['local_permission'] else None,
                local_key_required=True,remote_initial_configuration_ready=False,
                feature_update_requires_local_key=True,reason='FEATURE_CONFIGURATION_ALREADY_CALIBRATED')
        return dict(manager_online=workbench.service is not None and manager_alive(),fits=completed,jobs=self.records(),nameplate=nameplate(workbench.root),
            enabled=base.get('control',{}).get('enabled') is True,mode=base.get('control',{}).get('regulation_mode','temperature'),
            target_rpm=base.get('control',{}).get('target_rpm'),local_permission=bool(raw and raw[0]&0x8000),
            configured=status.get('configured') is True,requested_rpm=status.get('requested_rpm'),
            measured_rpm=status.get('measured_rpm'),pwm_counts=status.get('applied_pwm_counts'),
            local_key_required=dict(apply=permission['local_key_required'],arm=False,disarm=False),
            configuration_permission=permission,
            exit_behavior='PL_PROTECTION_AND_FALLBACK_RETAINED_NOT_POWER_DISCONNECT',physical_closed_loop_accepted=False)
    def _context(self,operation,package=None):
        service=self.workbench.service
        if service is None:raise ValueError('BOARD_COLLECTOR_REQUIRED')
        if not manager_alive():raise ValueError('COMMISSIONING_MANAGER_OFFLINE')
        state=service.public_state();status=state.get('status') or {}
        if operation!='disarm':
            if state.get('link')!='ONLINE' or not 0<=state.get('status_age_ms',1e9)<500:raise ValueError('Fresh board feedback required')
            if operation=='apply':
                permission=require_apply_permission(status,state.get('control_words',state.get('control',{}).get('control_words')),
                    state.get('status_age_ms'),package,state.get('feature_words'))
        thermal=getattr(service,'temperature_pwm',None)
        if operation!='disarm' and thermal and (thermal.snapshot().get('settings') or {}).get('enabled'):
            raise ValueError('先停用温度直接 PWM 模式')
        bench=service.bench.snapshot()
        if bench.get('controls_enabled') or (operation!='disarm' and bench_reason(bench)):
            raise ValueError('Stop the open-loop bench trial first and confirm its output readback')
        collector_boot=None if operation=='disarm' else service.boot+'/'+service.collector_session+'/'+str(service.connection_epoch)
        plate=self.workbench.root/'fan-nameplate.json'
        return dict(os_boot_id=boot_id(),collector_boot=collector_boot,base_config_sha256=sha(self.workbench.base),
            nameplate_sha256=sha(plate) if plate.exists() else None,
            apply_authorization=permission['authorization'] if operation=='apply' else None)
    def prepare(self,request):
        if set(request)!={'revision','fit_job_id','operation','mode','target_rpm'}:raise ValueError('Explicit control operation required')
        op=request['operation']
        if op not in ('apply','arm','disarm'):raise ValueError('Unknown control operation')
        if op!='disarm' and getattr(self.workbench,'learning',None) and self.workbench.learning.busy():
            raise ValueError('WAIT_FOR_NPU_LEARNING_OR_CANCEL_IT')
        if request['revision']!=self.workbench.revision():raise ValueError('INPUT_REVISION_CHANGED_RELOAD')
        if any(j['state'] in ('QUEUED','RUNNING') for j in self.records()):raise ValueError('Wait for the current control transaction')
        if op!='disarm' and any(j['state']=='RUNNING' for j in self.workbench.jobs.values()):raise ValueError('Wait for the current measurement job')
        job,path,pin,package=fitted(self.workbench.root,request['fit_job_id'])
        if op!='disarm':check_nameplate(self.workbench.root,package)
        if op!='disarm' and job['revision']!=request['revision']:raise ValueError('Fit the current saved measurement revision first')
        base=document(self.workbench.base)
        if op=='apply':
            if base['control'].get('enabled'):raise ValueError('Exit closed-loop control before applying parameters')
        elif op=='arm':
            if not matching_settings(base,document(path/'edge.standby.json')):raise ValueError('Apply this package in standby first')
            if request['mode'] not in ('speed','temperature'):raise ValueError('Choose speed or temperature regulation')
            target=request['target_rpm'];c=package[2]
            if request['mode']=='speed' and (type(target) is not int or not c['rpm_min']<=target<=c['rpm_max']):raise ValueError('Fixed RPM target outside measured envelope')
            if request['mode']=='temperature' and target is not None:raise ValueError('Temperature mode derives its RPM target')
        elif not any(matching_settings(base,t) for t in (package[4],document(path/'edge.standby.json'))):
            raise ValueError('Selected fit does not match the installed control parameters')
        if op!='arm' and (request['mode'] is not None or request['target_rpm'] is not None):raise ValueError('Only arm accepts mode/target')
        context=self._context(op,package);self.preview=dict(request,context=context,manifest_sha256=pin,nonce=uuid.uuid4().hex,expires_at=time.monotonic()+30)
        return dict(state='PREVIEW_NOT_APPLIED',nonce=self.preview['nonce'],expires_in_s=30,operation=op,
            mode=request['mode'],target_rpm=request['target_rpm'],restart_collector=True,
            local_key_required=op=='apply' and context['apply_authorization']!='REMOTE_INITIAL_CONFIGURATION',
            apply_authorization=context['apply_authorization'],
            model_contract_changes=op=='apply',exit_behavior='PL_PROTECTION_AND_FALLBACK_RETAINED_NOT_POWER_DISCONNECT')
    def confirm(self,request):
        if set(request)!={'nonce','confirm'} or request['confirm'] is not True:raise ValueError('Explicit preview confirmation required')
        p=self.preview;self.preview=None
        if not p or request['nonce']!=p['nonce'] or time.monotonic()>p['expires_at']:raise ValueError('Control preview expired')
        if p['operation']!='disarm' and getattr(self.workbench,'learning',None) and self.workbench.learning.busy():
            raise ValueError('WAIT_FOR_NPU_LEARNING_OR_CANCEL_IT')
        unused,path,pin,package=fitted(self.workbench.root,p['fit_job_id'])
        if pin!=p['manifest_sha256']:raise ValueError('Fit changed after preview')
        if p['revision']!=self.workbench.revision() or self._context(p['operation'],package)!=p['context']:raise ValueError('Control context changed; preview again')
        if any(j['state'] in ('QUEUED','RUNNING') for j in self.records()):raise ValueError('A control transaction is already pending')
        if len(self.records())>=100:raise ValueError('Archive control transactions before continuing')
        identity=uuid.uuid4().hex;job=dict(p,id=identity,state='QUEUED',created_at=time.monotonic())
        json_write(self.queue/(identity+'.json'),job)
        return dict(state='QUEUED_NOT_APPLIED',id=identity)

def execute(root,base,job):
    """Run only in the manager process, never from the collector/HTTP thread."""
    from . import deploy
    if job['context']['os_boot_id']!=boot_id() or time.monotonic()>job['expires_at']:raise ValueError('Expired control request; no automatic replay')
    if sha(base)!=job['context']['base_config_sha256']:raise ValueError('Configuration changed after confirmation')
    fit,path,pin,unused=fitted(root,job['fit_job_id'])
    op=job['operation']
    plate=Path(root)/'fan-nameplate.json'
    if op!='disarm':
        if (sha(plate) if plate.exists() else None)!=job['context']['nameplate_sha256']:raise ValueError('Nameplate changed after confirmation')
        check_nameplate(root,unused)
    if pin!=job['manifest_sha256'] or (op!='disarm' and fit['revision']!=job['revision']):raise ValueError('Confirmed fit changed')
    if op!='disarm':
        live=document('/run/cabinet-live/state.json')
        if live['observation']['boot']!=job['context']['collector_boot']:raise ValueError('Collector restarted; confirm again')
        if bench_reason(live['observation'].get('bench')):raise ValueError('Stop the open-loop bench trial first and confirm its output readback')
    if op=='apply':
        if job['context'].get('apply_authorization')=='REMOTE_INITIAL_CONFIGURATION':
            result=deploy.apply(path,pin,expected_authorization='REMOTE_INITIAL_CONFIGURATION')
        else:result=deploy.apply(path,pin)
    elif op=='arm':result=deploy.arm(path,pin,True,job['mode'],job['target_rpm'])
    elif op=='disarm':result=deploy.disarm(path,pin)
    else:raise ValueError('Unknown control operation')
    try:result['feedback']=wait_feedback(op,unused[4])
    except Exception:
        if op=='arm':deploy.disarm(path,pin)
        raise
    return result

def wait_feedback(operation,armed,timeout=15):
    from .measure import observation
    from .runtime import validate_binding
    deadline=time.monotonic()+timeout;last_error='No fresh collector feedback'
    while time.monotonic()<deadline:
        try:
            unused,packet,status=observation('/run/cabinet-live/state.json')
            enabled=packet.get('control',{}).get('enabled') is True
            if operation!='disarm':validate_binding(armed,packet.get('control',{}).get('control_words'),packet.get('feature_words'))
            if operation=='arm' and (not enabled or status.get('requested_rpm',0)<=0 or status.get('mode') not in ('STARTING','TRANSIENT','RUN')):
                raise ValueError('FPGA has not accepted a closed-loop target')
            if operation!='arm' and enabled:raise ValueError('Collector still reports an enabled control owner')
            return dict(owner_enabled=enabled,mode=status.get('mode'),requested_rpm=status.get('requested_rpm'),
                measured_rpm=status.get('measured_rpm'),pwm_counts=status.get('applied_pwm_counts'),
                physical_closed_loop_accepted=False,power_disconnected=False)
        except (OSError,ValueError,KeyError,RuntimeError) as error:last_error=str(error)
        time.sleep(.1)
    raise RuntimeError('CONTROL_READBACK_TIMEOUT: '+last_error)

def run_manager(root,base,stop):
    import fcntl,threading
    root=Path(root);queue=root/'control-queue';queue.mkdir(parents=True,mode=0o700,exist_ok=True)
    MANAGER_STATE.parent.mkdir(mode=0o700,exist_ok=True)
    with (MANAGER_STATE.parent/'manager.lock').open('w') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        for path in queue.glob('*.json'):
            job=document(path)
            if job.get('state')=='RUNNING':
                job.update(state='INTERRUPTED_REQUIRES_REVIEW',error='Previous manager ended during transaction; request not replayed')
                json_write(path,job)
        done=threading.Event()
        def heartbeat():
            while not done.is_set():
                json_write(MANAGER_STATE,dict(boot_id=boot_id(),updated_at=time.monotonic(),pid=os.getpid()))
                done.wait(.5)
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        try:
            while not stop.is_set():
                for path in sorted(queue.glob('*.json')):
                    if path.is_symlink() or not ID.fullmatch(path.stem):continue
                    job=document(path)
                    if job.get('state')!='QUEUED':continue
                    job['state']='RUNNING';json_write(path,job)
                    try:job.update(result=execute(root,base,job),state='COMPLETED')
                    except Exception as error:job.update(state='FAILED',error=str(error))
                    job['completed_at']=time.monotonic();json_write(path,job)
                stop.wait(.25)
        finally:done.set();thread.join(timeout=2)
