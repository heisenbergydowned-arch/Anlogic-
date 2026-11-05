"""Local authenticated workbench. Files are versioned; actuator ownership stays in Service."""
import copy,csv,hashlib,io,json,os,shutil,threading,time,uuid,zipfile,math
from pathlib import Path
from cabinet.normal_reference_guard import bench_reason
from .fit import build,sha,TEMPLATE
from .deploy import atomic
from .measure import record_point,record_trace,evaluate_trace,record_current_zero,current_zero_declaration
from .bench import plan
from .bench_admission import collector_identity,require_admission,AUTHORIZATION

FILES=('settings.json','calibration.csv','actuator.csv','bench.json','control_trace.csv')
HEADERS={'calibration.csv':'channel,split,raw,reference,unit,session_id,source',
         'actuator.csv':'duty_percent,rpm,current_A,temperature_C,session_id,source',
         'control_trace.csv':'time_s,target_rpm,rpm,pwm_counts,temperature_C,setpoint_C,mode,valid,session_id,source'}
BENCH={'profile':{'source':'REAL_USER_MEASUREMENTS','operator':'','reference_evidence_sha256':'',
    'wiring_verified':False,'zero_pwm_not_poweroff_confirmed':False,'max_duty_percent':None,
    'current_zero_code':None,'current_trip_distance_code':None,'temperature_trip_C':None,
    'minimum_fg_period_clocks':None,'duration_limit_s':None},'steps':[]}

class Workbench:
    def __init__(self,directory,base_config,service=None,state_path='/run/cabinet-live/state.json'):
        self.root=Path(directory);self.base=Path(base_config);self.service=service;self.state_path=state_path
        self.lock=threading.RLock();self.jobs={};self.preview=None
        if self.root.is_symlink():raise ValueError('Regular workspace required')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.inputs=self.root/'inputs';self.inputs.mkdir(exist_ok=True,mode=0o700)
        base=json.loads(self.base.read_text(encoding='utf-8'));settings=copy.deepcopy(TEMPLATE);settings['device_id']=base['device_id']
        defaults={'settings.json':json.dumps(settings,ensure_ascii=False,indent=2)+'\n','bench.json':json.dumps(BENCH,indent=2)+'\n'}
        defaults.update({k:v+'\n' for k,v in HEADERS.items()})
        for name,data in defaults.items():
            p=self.inputs/name
            if p.is_symlink():raise ValueError('Symlink input refused')
            if not p.exists():atomic(p,data.encode())
        (self.root/'jobs').mkdir(exist_ok=True,mode=0o700)
        for path in sorted((self.root/'jobs').glob('*/job.json'))[-100:]:
            if path.is_symlink():raise ValueError('Regular job record required')
            previous=json.loads(path.read_text(encoding='utf-8'))
            if previous.get('id')==path.parent.name:self.jobs[previous['id']]=previous
        from .control_jobs import ControlJobs
        self.control=ControlJobs(self)
        from normal_npu.learning import Learning
        self.learning=Learning(root=self.root.parent/'npu-learning' if service is not None else self.root/'npu-learning',
                               config=base_config,state=state_path)
        from labeled_npu.learning import Learning as LabeledLearning
        self.labeled_learning=LabeledLearning(root=self.learning.root,config=base_config,state=state_path)
        if self.service is not None:
            def persist_bench():
                saved=None
                while not self.service.stop.wait(.2):
                    b=self.service.bench.snapshot(record_limit=0)
                    if b.get('id') and b['id']!=saved and b['state'] in ('COMPLETED','STOPPED','REJECTED','OUTPUT_STOP_UNCONFIRMED'):
                        identity=b['id']
                        b=self.service.bench.snapshot()
                        if b.get('id')!=identity or b['state'] not in ('COMPLETED','STOPPED','REJECTED','OUTPUT_STOP_UNCONFIRMED'):continue
                        folder=self.root/'jobs'/b['id'];folder.mkdir(exist_ok=True)
                        atomic(folder/'bench-record.json',json.dumps(b,ensure_ascii=False,allow_nan=False,indent=2).encode())
                        saved=b['id']
            threading.Thread(target=persist_bench,daemon=True).start()
    def revision(self):
        return hashlib.sha256(b''.join(n.encode()+b'\0'+(self.inputs/n).read_bytes() for n in FILES)).hexdigest()
    def documents(self):
        return {n:(self.inputs/n).read_text(encoding='utf-8') for n in FILES}
    def status(self):
        with self.lock:
            base=json.loads(self.base.read_text(encoding='utf-8'));live=self.service.public_state() if self.service else {'link':'OFFLINE'}
            snapshot=self.learning.status_snapshot()
            result=dict(schema='cabinet-workbench-v1',mode='BOARD_COLLECTOR' if self.service else 'LOCAL_FILES_ONLY',
                revision=self.revision(),device_id=base['device_id'],documents=self.documents(),
                live=dict(link=live.get('link'),status_age_ms=live.get('status_age_ms'),status=live.get('status')),
                bench=self.service.bench.snapshot(record_limit=8) if self.service else dict(state='LOCAL_ONLY',hardware_supported=False,controls_enabled=False),
                temperature_pwm=live.get('temperature_pwm'),
                waveform=dict(configured=base.get('waveform',{}).get('enabled') is True,state=live.get('waveform')),
                jobs=copy.deepcopy(list(self.jobs.values())),control=self.control.summary(),npu_learning=self.learning.status(snapshot),
                labeled_learning=self.labeled_learning.status(snapshot),physical_closed_loop_accepted=False,
                calibration_csv_sha256=sha(self.inputs/'calibration.csv'),
                stages=['参考测量','受限调速辨识','拟合与参数检查','板端受控试运行','五类实测训练','整机量化验收'])
            # The second context check can wait for a frame. Do not let it
            # prolong the first status's original 45-second heartbeat deadline.
            self.learning.refresh_status_worker(result['npu_learning'],snapshot)
            self.labeled_learning.refresh_status_worker(result['labeled_learning'],snapshot)
            return result
    def update(self,request):
        if set(request)!={'revision','name','content'} or request['name'] not in FILES or type(request['content']) is not str:raise ValueError('Known input and revision required')
        with self.lock:
            if any(j['state']=='RUNNING' for j in self.jobs.values()) or (self.service and self.service.bench.snapshot().get('controls_enabled')):raise ValueError('Wait for current operation before editing measurements')
            if any(j['state'] in ('QUEUED','RUNNING') for j in self.control.records()):raise ValueError('Wait for the control transaction before editing measurements')
            if request['revision']!=self.revision():raise ValueError('INPUT_REVISION_CHANGED_RELOAD')
            name=request['name'];text=request['content']
            if len(text.encode())>60000:raise ValueError('Input size limit')
            if name.endswith('.json'):
                value=json.loads(text,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                if type(value) is not dict:raise ValueError('JSON object required')
                if name=='settings.json' and (value.get('schema')!=TEMPLATE['schema'] or value.get('source')!=TEMPLATE['source'] or value.get('device_id')!=json.loads(self.base.read_text(encoding='utf-8'))['device_id']):raise ValueError('Measured source and device identity must match')
            else:
                rows=csv.DictReader(io.StringIO(text))
                if rows.fieldnames!=HEADERS[name].split(','):raise ValueError('CSV units/columns differ')
                for row in rows:
                    if None in row or any(v is None for v in row.values()) or row.get('source')!='REAL_USER_MEASUREMENTS':raise ValueError('Real measurement rows only')
            backup=self.root/'revisions'/self.revision();backup.mkdir(parents=True,exist_ok=True)
            atomic(backup/name,(self.inputs/name).read_bytes());atomic(self.inputs/name,text.encode())
            self.preview=None
            return dict(state='INPUT_SAVED_NOT_APPLIED',revision=self.revision())
    def submit(self,operation,request):
        allowed={'fit':{'revision'},'point':{'revision','channel','reference','split','seconds'},
                 'record-control':{'revision','seconds'},'evaluate-control':{'revision','temperature_tolerance_C'},
                 'current-zero':{'revision','seconds','operator','load_path_open','sensor_chain_powered'}}
        if operation not in allowed or set(request)!=allowed[operation]:raise ValueError('Unknown job or fields')
        if operation=='current-zero':
            current_zero_declaration(request['operator'],request['load_path_open'],request['sensor_chain_powered'])
            if type(request['seconds']) not in (int,float) or not math.isfinite(request['seconds']) or not 1<=request['seconds']<=60:
                raise ValueError('CURRENT_ZERO_DURATION_1_TO_60_SECONDS')
        for key in ('reference','seconds','temperature_tolerance_C'):
            if key in request and not (key=='temperature_tolerance_C' and request[key] is None):
                if type(request[key]) not in (int,float) or not math.isfinite(request[key]):raise ValueError('Finite numeric value required: '+key)
        with self.lock:
            if request['revision']!=self.revision():raise ValueError('INPUT_REVISION_CHANGED_RELOAD')
            if any(j['state']=='RUNNING' for j in self.jobs.values()):raise ValueError('One durable job at a time')
            if len(self.jobs)>=100:raise ValueError('Workspace job bound reached; archive and reopen')
            if operation in ('point','record-control','current-zero') and self.service is None:raise ValueError('BOARD_COLLECTOR_REQUIRED_NO_OFFLINE_SENSOR_VALUES')
            if self.service and self.service.bench.snapshot().get('controls_enabled'):raise ValueError('Stop bench trial before fitting or recording calibration')
            if operation=='current-zero':self._current_zero_guard()
            identity=uuid.uuid4().hex;folder=self.root/'jobs'/identity;folder.mkdir()
            shutil.copytree(self.inputs,folder/'inputs');shutil.copy2(self.base,folder/'base-edge.json')
            j=dict(id=identity,operation=operation,state='RUNNING',revision=request['revision']);self.jobs[identity]=j
        def task():
            try:
                if operation=='fit':result=build(folder/'inputs',folder/'base-edge.json',folder/'fitted')
                elif operation in ('point','current-zero'):
                    if operation=='current-zero':
                        result=record_current_zero(folder/'inputs',request['seconds'],request['operator'],
                            request['load_path_open'],request['sensor_chain_powered'],self.state_path,guard=self._current_zero_guard)
                    else:result=record_point(folder/'inputs',request['channel'],request['reference'],request['split'],request['seconds'],self.state_path)
                    with self.lock:
                        if self.revision()!=request['revision']:raise ValueError('Input changed; recorded point retained in job only')
                        csv_bytes=(folder/'inputs/calibration.csv').read_bytes()
                        self._copy_point(folder/'inputs/points',result)
                        # The CSV is the commit point. An orphan evidence file
                        # is harmless; a live row without its origin is not.
                        atomic(self.inputs/'calibration.csv',csv_bytes)
                elif operation=='record-control':result=record_trace(folder/'control_trace.csv',request['seconds'],self.state_path)
                else:result=evaluate_trace(folder/'inputs/control_trace.csv',temperature_tolerance_C=request['temperature_tolerance_C'])
                j.update(state='COMPLETED',result=result)
            except Exception as e:j.update(state='FAILED',error=str(e))
            atomic(folder/'job.json',(json.dumps(j,ensure_ascii=False,indent=2)+'\n').encode())
        threading.Thread(target=task,daemon=True).start()
        return copy.deepcopy(j)
    def _current_zero_guard(self):
        with self.lock:
            if self.service is None:raise ValueError('BOARD_COLLECTOR_REQUIRED_NO_OFFLINE_SENSOR_VALUES')
            if getattr(self.service,'mock',False) or getattr(self.service,'diagnostic_test',False):
                raise ValueError('REAL_COLLECTOR_REQUIRED_FOR_CURRENT_ZERO')
            if self.learning.busy() or self.labeled_learning.busy():raise ValueError('WAIT_FOR_NPU_LEARNING_OR_CANCEL_IT')
            bench=self.service.bench.snapshot()
            if bench.get('controls_enabled') or bench.get('state') in ('QUEUED_NOT_APPLIED','ACTIVE_BENCH_NOT_CLOSED_LOOP','OUTPUT_STOP_UNCONFIRMED'):
                raise ValueError('STOP_BENCH_BEFORE_CURRENT_ZERO')
            if any(j['state'] in ('QUEUED','RUNNING') for j in self.control.records()):raise ValueError('CONTROL_TRANSACTION_PENDING')
    def _current_zero_running(self):
        return any(j['state']=='RUNNING' and j['operation']=='current-zero' for j in self.jobs.values())
    def _copy_point(self,source,result):
        identity=result['session_id']
        if type(identity) is not str or str(uuid.UUID(identity))!=identity:raise ValueError('Invalid point session identity')
        source=Path(source);path=source/(identity+'.json')
        if source.is_symlink() or path.is_symlink():raise ValueError('Regular point evidence required')
        data=path.read_bytes()
        if json.loads(data.decode('utf-8'))!=result:raise ValueError('Point evidence differs from capture result')
        target=self.inputs/'points'
        if target.is_symlink():raise ValueError('Regular point evidence directory required')
        target.mkdir(exist_ok=True)
        output=target/path.name
        if output.is_symlink():raise ValueError('Regular point evidence required')
        if output.exists():
            if output.read_bytes()!=data:raise ValueError('Existing point evidence differs; refusing overwrite')
        else:atomic(output,data)
        if output.read_bytes()!=data:raise ValueError('Point evidence readback differs')
    def bench_preview(self,request):
        if set(request)!={'revision'}:raise ValueError('Revision required')
        with self.lock:
            if request['revision']!=self.revision():raise ValueError('INPUT_REVISION_CHANGED_RELOAD')
            prepared=plan(json.loads((self.inputs/'bench.json').read_text(encoding='utf-8')))
            if prepared['document']['profile']['reference_evidence_sha256']!=sha(self.inputs/'calibration.csv'):raise ValueError('Bench reference pin differs from saved preliminary measurements')
            if len(list(csv.DictReader((self.inputs/'calibration.csv').open(encoding='utf-8'))))<1:raise ValueError('Preliminary real reference measurements required')
            self.preview=dict(id=uuid.uuid4().hex,revision=self.revision(),expires=time.monotonic()+30,
                boot=self.service.boot if self.service else None,collector_boot=collector_identity(self.service) if self.service else None,prepared=prepared)
            available=False;unavailable='BOARD_OFFLINE'
            if self.service is not None and self.service.public_state().get('link')=='ONLINE':
                try:
                    bench=getattr(self.service,'bench',None)
                    check=getattr(bench,'current_admission',None)
                    (check if callable(check) else require_admission)(self.preview['collector_boot'])
                    available=True;unavailable=None
                except ValueError:unavailable='REMOTE_PWM_FIRMWARE_NOT_ADMITTED'
            return dict(state='PREVIEW_NOT_APPLIED',preview_id=self.preview['id'],expires_in_s=30,
                duration_s=prepared['total_seconds'],profile=prepared['document'],live_start_available=available,
                start_unavailable_reason=unavailable,authorization=AUTHORIZATION,local_key_required=False)
    def bench_start(self,request):
        with self.lock:
            thermal=getattr(self.service,'temperature_pwm',None)
            if thermal and (thermal.snapshot().get('settings') or {}).get('enabled'):
                raise ValueError('先停用温度直接 PWM 模式')
            if self._current_zero_running():raise ValueError('WAIT_FOR_CURRENT_ZERO_COLLECTION')
            if self.learning.busy() or self.labeled_learning.busy():raise ValueError('WAIT_FOR_NPU_LEARNING_OR_CANCEL_IT')
            if any(j['state'] in ('QUEUED','RUNNING') for j in self.control.records()):raise ValueError('CONTROL_TRANSACTION_PENDING')
            p=self.preview
            if (set(request)!={'preview_id','start_controlled_trial','authorization'} or request['start_controlled_trial'] is not True
                    or request['authorization']!=AUTHORIZATION):raise ValueError('Explicit remote bounded PWM authorization required')
            if not p or p['id']!=request['preview_id'] or time.monotonic()>p['expires'] or self.revision()!=p['revision']:raise ValueError('Preview expired or inputs changed')
            if self.service is None:raise ValueError('BOARD_COLLECTOR_REQUIRED')
            self.preview=None
            if p['collector_boot']!=collector_identity(self.service):raise ValueError('COLLECTOR_CHANGED_PREVIEW_AGAIN')
            return self.service.bench.request_start(p['prepared'],p['boot'])
    def action(self,name,request):
        if name in ('npu-start','labeled-start'):
            with self.lock:
                if self._current_zero_running():raise ValueError('WAIT_FOR_CURRENT_ZERO_COLLECTION')
                if not self.service:raise ValueError('BOARD_COLLECTOR_REQUIRED')
                if bench_reason(self.service.bench.snapshot()):raise ValueError('STOP_BENCH_BEFORE_LEARNING')
                if any(j['state'] in ('QUEUED','RUNNING') for j in self.control.records()):raise ValueError('CONTROL_TRANSACTION_PENDING')
                return (self.learning if name=='npu-start' else self.labeled_learning).start(request)
        if name=='npu-cancel':return self.learning.cancel(request)
        if name=='labeled-cancel':return self.labeled_learning.cancel(request)
        if name=='control-preview':
            with self.lock:return self.control.prepare(request)
        if name=='control-confirm':
            with self.lock:return self.control.confirm(request)
        if name=='inputs':return self.update(request)
        if name=='bench-preview':return self.bench_preview(request)
        if name=='bench-start':return self.bench_start(request)
        if name in ('bench-stop','bench-heartbeat'):
            if not self.service:raise ValueError('BOARD_COLLECTOR_REQUIRED')
            if name=='bench-stop':
                if request:raise ValueError('Empty stop body required')
                return self.service.bench.stop()
            if set(request)!={'id'}:raise ValueError('Trial identity required')
            return self.service.bench.heartbeat(request['id'])
        return self.submit(name,request)
    def archive(self):
        with self.lock:
            if any(j['state']=='RUNNING' for j in self.jobs.values()):raise ValueError('Wait for durable job completion')
            if self.service and self.service.bench.snapshot().get('controls_enabled'):raise ValueError('Stop trial before export')
            if sum(p.stat().st_size for folder in (self.inputs,self.root/'jobs') for p in folder.rglob('*') if p.is_file())>32*1024*1024:raise ValueError('Archive workspace locally; web export exceeds 32 MiB')
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
                for folder in (self.inputs,self.root/'jobs',self.root/'control-queue'):
                    for p in folder.rglob('*'):
                        if p.is_symlink():raise ValueError('Symlinks not exported')
                        if p.is_file():z.write(str(p),str(p.relative_to(self.root)))
                if self.service:z.writestr('bench-record.json',json.dumps(self.service.bench.snapshot(),ensure_ascii=False,allow_nan=False))
                plate=self.root/'fan-nameplate.json'
                if plate.is_file() and not plate.is_symlink():z.write(str(plate),'fan-nameplate.json')
                z.writestr('scope.json',json.dumps(dict(deployed=False,physical_accepted=False,revision=self.revision())))
            if output.tell()>32*1024*1024:raise ValueError('Export size bound reached; archive workspace locally')
            return output.getvalue()
