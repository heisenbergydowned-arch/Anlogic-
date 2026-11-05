"""Separate hardware, inference, journal and uplink workers.

The hardware worker owns all command staging. It never waits for inference,
filesystem writes or network delivery.
"""
from datetime import datetime,timezone
import hashlib
import queue
import threading
import time
import uuid
from .io import open_controller,FCB1
from commissioning.runtime import read_control_words,validate_binding
from .mock import MockController
from .model import Model
from .policy import Fusion,TemperatureLoop,FixedRpmLoop
from .protocol import FrameGate,elapsed32
from .store import Store,EventTracker
from .uplink import Uplink
from .environment import age_environment, read_environment, unavailable
from .freshness import aged_ms
from .waveform import WaveformReader,canonical
from .icm_diagnostics import IcmDiagnostics,age_diagnostics
from .normal_reference_guard import NormalReferenceGuard
from hmi_daily.read_real import normalize_status, read_feature_configuration, read_mailbox

HARD={'OC_HARD','TEMP_HARD','CURRENT_PROTECTION_LOST','STALL_CORROBORATED','OVERSPEED','VIB_HARD'}
WARN={'CURRENT_HIGH','TEMP_WARN','TEMP_LOSS','FG_LOSS','START_FAIL','VIB_WARN','PS_LOSS','CMD_EXPIRED','TRACK_ERROR'}

class Service:
    def __init__(self,config,*,mock=False,controller=None,observer=None,recorder=None):
        if mock and config['temperature_loop'].get('enabled'):raise ValueError('Mock service cannot enable real control')
        if config['control'].get('enabled') and (config['control'].get('qualified') is not True or not config['control'].get('evidence')):
            raise ValueError('Control owner needs commissioned configuration and evidence')
        self.config=config;self.mock=mock;self.controller=controller
        self.observer=observer;self.observation_sequence=0
        self.recorder=recorder;self.capture_sequence=0
        self.collector_session=str(uuid.uuid4());self.connection_epoch=0
        self.diagnostic_test=mock or config.get('diagnostic_test',False)
        if self.diagnostic_test and config['control'].get('enabled'):raise ValueError('Diagnostic test cannot own actuator control')
        if config.get('load_executor',{}).get('enabled'):raise ValueError('External power/load execution has been removed')
        self.model=Model(config['model']);self.fusion=Fusion(config['policy']);self.gate=FrameGate(config['contract'])
        self.regulation_mode=config['control'].get('regulation_mode','temperature')
        if self.regulation_mode not in ('temperature','speed'):raise ValueError('Unknown control regulation mode')
        self.outer=(FixedRpmLoop(config['temperature_loop'],config['control'].get('target_rpm'))
                    if config['control'].get('enabled') and self.regulation_mode=='speed' else TemperatureLoop(config['temperature_loop']))
        from .fault_grade import FaultGrade
        self.fault_grade=FaultGrade(config.get('fault_grade'))
        self.maintenance = None
        if config.get('maintenance',{}).get('enabled'):
            from .predictive import Maintenance
            self.maintenance = Maintenance(dict(config['maintenance'],device_id=config['device_id']))
        waveform=config.get('waveform',{})
        if type(waveform) is not dict or set(waveform)-{'enabled','transactions_per_poll','budget_ms','reviewed_abi'}:
            raise ValueError('Unknown WAV1 policy')
        if type(waveform.get('enabled',False)) is not bool:raise ValueError('WAV1 enable must be boolean')
        if waveform.get('enabled') and (type(waveform.get('reviewed_abi')) is not int or waveform['reviewed_abi']!=0x10000):
            raise ValueError('Explicit reviewed WAV1 ABI required before optional MMIO access')
        self.wave_reader=WaveformReader(waveform.get('transactions_per_poll',64),waveform.get('budget_ms',2)) if waveform.get('enabled') else None
        self.wave_result=None
        self.icm_reader=IcmDiagnostics(config.get('icm_diagnostics',{}))
        self.snapshot_ms=config.get('snapshot_interval_ms',1000)
        if type(self.snapshot_ms) is not int or not 100<=self.snapshot_ms<=60000:raise ValueError('Snapshot interval must be 100..60000ms')
        self.snapshot_identity=self.snapshot_written=None
        self.storage_checked=None
        if config.get('project_level')=='advanced' and not config.get('journal_encryption'):
            raise ValueError('Advanced deployment requires authenticated journal encryption')
        self.store=Store(config['database'],config.get('storage'),config.get('journal_encryption'));self.store.reset_retry_clock()
        from .reports import MonitorReports
        try:
            self.monitor_reports=MonitorReports(self.store,config['device_id'],config.get('monitor_reports'))
            self.uplink=Uplink(config['uplink'],self.store)
        except BaseException:self.store.close();raise
        self.stop=threading.Event();self.lock=threading.RLock();self.threads=[]
        self.frames=queue.Queue(maxsize=2);self.journal=queue.Queue(maxsize=256);self.commands=queue.Queue(maxsize=32)
        self.state=dict(link='CONNECTING',test=self.diagnostic_test,status=None,frame=None,model=None,decision=None,
                        level=None,error=None,frame_drops=0,journal_backpressure=0,
                        environment=unavailable('CONNECTING'))
        self.updated=None;self.boot=None;self.valid_input=False;self.pending_fifo=None;self.input_generation=0
        self.frame_received=None
        self.fifo_ack_ready=None
        self.trackers={};self.link_tracker=EventTracker(self.store,config['device_id'],config['device_id']+'/LINK')
        self.soft_nonzero=False;self.started=False
        from .parameters import ParameterControl
        try:self.parameters=ParameterControl(self)
        except BaseException:self.store.close();raise
        self.parameter_rpc=None
        from commissioning.bench import BenchController
        self.bench=BenchController(self)
        from .temperature_pwm import TemperaturePWM
        self.temperature_pwm=TemperaturePWM(self)
        self.normal_reference_guard=NormalReferenceGuard()
        from .pressure_calibration import PressureCalibration
        try:self.pressure=PressureCalibration(self)
        except BaseException:self.store.close();raise
    def persist_status(self,state):
        status=state.get('status') or {}
        identity=canonical([self.boot,state.get('link'),state.get('test'),state.get('error'),
            {key:status.get(key) for key in ('active','latched','alarm_level','config_id','configured','fan_action')}])
        now=time.monotonic()
        if identity!=self.snapshot_identity or self.snapshot_written is None or now-self.snapshot_written>=self.snapshot_ms/1000:
            self.store.snapshot(self.config['device_id'],state)
            if self.store.history.record(self.config['device_id'],dict(state,boot_id=self.boot)) and self.monitor_reports.enabled:
                with self.store.lock:
                    row=self.store.db.execute('SELECT id,payload FROM history_samples WHERE device=? ORDER BY id DESC LIMIT 1',(self.config['device_id'],)).fetchone()
                    document=self.store.unpack(row[1],'history_samples',row[0])
                self.monitor_reports.observe(document)
            self.snapshot_identity=identity;self.snapshot_written=now
        if self.storage_checked is None or now-self.storage_checked>=5:
            self.set(storage=self.store.storage_health())
            self.storage_checked=now
    def poll_waveform(self):
        if self.wave_reader is None:return
        if not hasattr(self.controller,'io'):
            self.set(waveform=dict(state='TRANSPORT_UNAVAILABLE',qualified=False));return
        with self.lock:
            result=self.wave_result;self.wave_result=None
        if result is not None:self.wave_reader.result(*result)
        status=self.wave_reader.poll(self.controller.io,self.boot,self.controller.boot_cookie,
            lambda token,record:self.put_journal(('waveform',token,record)))
        self.set(waveform=status)
    def set(self,**values):
        with self.lock:self.state.update(values)
    def public_state(self):
        with self.lock:
            state=dict(self.state);updated=self.updated;frame_received=self.frame_received
        state['snapshot_monotonic']=time.monotonic()
        state['status_age_ms']=round((time.monotonic()-updated)*1000) if updated is not None else None
        if state['status_age_ms'] is None or state['status_age_ms']>self.config.get('link_stale_ms',2000):state['link']='OFFLINE'
        if state['link']=='OFFLINE':state['environment']=unavailable('OFFLINE')
        else:state['environment']=age_environment(state.get('environment'),state['status_age_ms'])
        state['icm_diagnostics']=age_diagnostics(state.get('icm_diagnostics'),offline=state['link']=='OFFLINE')
        model=state.get('model');status=state.get('status') or {}
        frame=state.get('frame')
        state['frame_age_ms']=elapsed32(status.get('uptime_ms',0),frame['end_ms']) if frame else None
        if frame and frame_received is not None:
            state['frame_age_ms']=max(state['frame_age_ms'],round(max(0,time.monotonic()-frame_received)*1000))
        if state.get('maintenance') and (state['link']!='ONLINE' or state.get('test') is True or not frame or
                frame.get('quality')!=0 or not frame.get('calibration_id') or
                state['frame_age_ms'] is None or state['frame_age_ms']>1000):
            state['maintenance']=dict(state='INVALID_INPUT',remaining_life_s=None,control_authority=False)
        if model and (state['link']=='OFFLINE' or state['status_age_ms']>self.config['contract']['max_result_age_ms'] or
                      elapsed32(status.get('uptime_ms',0),model['frame_end_ms'])>self.config['contract']['max_result_age_ms'] or
                      (state['frame_age_ms'] is not None and state['frame_age_ms']>self.config['contract']['max_result_age_ms'])):
            state['model']=None;state['decision']=dict(model_state='EXPIRED',reason='result_ttl',level=status.get('alarm_level',0))
        state['level']=max(status.get('alarm_level',0),(state.get('decision') or {}).get('level',0))
        state['coordination']=dict(self.outer.coordination)
        state['temperature_pwm']=self.temperature_pwm.snapshot()
        from .monitor_view import snapshot as monitor_snapshot
        identity=(self.boot+'/'+self.collector_session+'/'+str(self.connection_epoch)
                  if self.boot and state['link']=='ONLINE' else None)
        state['monitor_display']=monitor_snapshot(self.observer,identity,time.monotonic())
        pressure_display=getattr(self.observer,'pressure_display_mean',None)
        if pressure_display is not None:
            identity=(self.boot+'/'+self.collector_session+'/'+str(self.connection_epoch)
                      if self.boot and state['link']=='ONLINE' else None)
            state['pressure_display']=pressure_display.summary(identity,time.monotonic())
        return state
    def enqueue_command(self,boot,op,payload):
        try:self.commands.put_nowait((boot,op,payload))
        except queue.Full:self.set(error='Command queue full; no unsafe retry/lease extension')
    def start(self):
        if self.started:raise RuntimeError('Service already started')
        self.started=True
        self.pressure.start()
        if self.parameters.config.get('enabled') and self.parameters.config.get('local_socket'):
            from .parameter_rpc import ParameterRPC
            self.parameter_rpc=ParameterRPC(self,self.parameters.config['local_socket'])
        if self.recorder is not None:self.recorder.start()
        if self.observer is not None:self.observer.start()
        for name,target in [('hardware',self.io_loop),('model',self.model_loop),('journal',self.journal_loop),('uplink',self.uplink_loop)]:
            thread=threading.Thread(name='cabinet-'+name,target=target,daemon=True);thread.start();self.threads.append(thread)
    def put_journal(self,item):
        try:self.journal.put_nowait(item);return True
        except queue.Full:
            with self.lock:self.state['journal_backpressure']+=1
            return False
    def io_loop(self):
        heartbeat_at=target_at=0
        previous_uptime=None;progress_at=None
        while not self.stop.is_set():
            catch_up=False
            try:
                if self.controller is None:self.controller=MockController() if self.mock else open_controller(self.config)
                if self.boot is None:
                    self.controller.identify();self.boot=f'{self.config["device_id"]}/{self.controller.boot_cookie:08x}'
                    self.connection_epoch+=1
                    self.gate.reset()
                    with self.lock:self.fusion.reset();self.input_generation+=1
                    self.pending_fifo=None;self.valid_input=False
                    with self.lock:self.fifo_ack_ready=None
                    previous_uptime=None;progress_at=time.monotonic()
                if hasattr(self.controller,'io') and self.controller.io.read(0x1050)!=self.controller.boot_cookie:
                    raise RuntimeError('PL reset detected; discard old commands/results')
                now=time.monotonic();owned=self.config['control'].get('enabled',False) and not self.mock
                control_words=[]
                binding_error=None
                if hasattr(self.controller,'io'):
                    control_words=read_control_words(self.controller.io)
                    if owned and self.config.get('commissioning'):
                        try:validate_binding(self.config,control_words,read_feature_configuration(self.controller.io))
                        except ValueError as error:
                            binding_error=str(error);owned=False
                if owned and now>=heartbeat_at:
                    self.controller.command(3);heartbeat_at=now+self.config['control'].get('heartbeat_ms',250)/1000
                with self.lock:ack=self.fifo_ack_ready
                if ack is not None:
                    if ack[0]==self.boot and self.pending_fifo==ack:
                        try:self.controller.command(8,ack[1])
                        except Exception as error:self.set(error='Durable FIFO acknowledgement pending: '+str(error))
                        else:
                            with self.lock:
                                if self.fifo_ack_ready==ack:self.fifo_ack_ready=None
                            if self.pending_fifo==ack:self.pending_fifo=None
                    else:
                        with self.lock:
                            if self.fifo_ack_ready==ack:self.fifo_ack_ready=None
                # Only the hardware worker issues commands. Work from an old
                # PL boot can never pop a new FIFO or apply an old model result.
                for _ in range(4):
                    try:boot,op,payload=self.commands.get_nowait()
                    except queue.Empty:break
                    if boot==self.boot and (owned or op==8):
                        try:self.controller.command(op,payload)
                        except Exception as e:self.set(error='Command rejected: '+str(e))
                        else:
                            if op==8 and self.pending_fifo==(boot,payload):self.pending_fifo=None
                mailbox={'queued_frames':0,'dropped_frames':0}
                feature_words=[]
                if hasattr(self.controller,'io'):
                    mailbox=read_mailbox(self.controller.io)
                    frame=self.controller.frame()
                    # A full two-frame mailbox must be drained before taking
                    # the normal idle pause. Preserve every consumed frame and
                    # its source timestamp; never spin on an empty read.
                    catch_up=frame is not None and mailbox.get('queued_frames',0)>=2
                    status=normalize_status(self.controller.status(),keep_raw=True)
                    if self.observer is not None or self.recorder is not None or self.maintenance is not None:feature_words=read_feature_configuration(self.controller.io)
                else:
                    status=normalize_status(self.controller.status(),keep_raw=True)
                    frame=self.controller.frame()
                    feature_words=list(getattr(self.controller,'feature_words',[]))
                now=time.monotonic()
                uptime=status['uptime_ms']
                # Renew an already admitted finite trial immediately after its
                # fresh status read. Waiting until all optional diagnostics and
                # display preparation complete can consume the 500 ms lease.
                # poll() repeats every ownership, duration and feedback check;
                # the later call is retained and deduplicates the same sample.
                if self.bench.active is not None:
                    self.bench.poll(self.controller,status)
                if control_words:
                    if status.get('configuration_id')!=control_words[1]:raise RuntimeError('Control status/readback identity mismatch')
                    status['protection_qualifications']={name:bool(control_words[0]&(1<<bit)) for bit,name in
                        enumerate(('current','temperature','actuator','pi','vibration'))}
                environment=(read_environment(self.controller.io,mailbox) if hasattr(self.controller,'io')
                             else unavailable('DIAGNOSTIC_UNAVAILABLE'))
                if hasattr(self.controller,'io'):
                    self.set(icm_diagnostics=self.icm_reader.poll(self.controller.io,self.boot,self.controller.boot_cookie))
                if previous_uptime is not None and uptime<previous_uptime and previous_uptime-uptime<0x80000000:
                    raise RuntimeError('PL uptime restarted')
                if uptime!=previous_uptime:progress_at=now
                elif now-progress_at>2:raise RuntimeError('PL status clock stopped')
                previous_uptime=uptime
                with self.lock:
                    self.state['status']=status;self.state['environment']=environment;self.state['link']='ONLINE';self.state['updated_utc']=datetime.now(timezone.utc).isoformat();self.updated=now
                    self.state['control_owner']=dict(verified=owned,binding_error=binding_error,
                        collector_session=self.collector_session,connection_epoch=self.connection_epoch,boot_id=self.boot)
                    # Same hardware sample as status; expose existing readback
                    # without another MMIO owner or another register read.
                    self.state['control_words']=list(control_words)
                    self.state['feature_words']=list(feature_words)
                self.parameters.process()
                self.temperature_pwm.poll(self.controller,status,now,self.boot+'/'+self.collector_session+'/'+str(self.connection_epoch))
                self.bench.poll(self.controller,status)
                observation_boot=self.boot+'/'+self.collector_session+'/'+str(self.connection_epoch)
                # The display/learning subscriber needs current ownership and
                # stop evidence, not the full, growing trial trace each poll.
                bench_snapshot=self.bench.snapshot(record_limit=0)
                reference_guard=self.normal_reference_guard.update(observation_boot,status,bench_snapshot,frame)
                if owned:
                    target=self.outer.update(status,now)
                    if target is not None and now>=target_at:
                        self.controller.command(1,target);target_at=now+self.config['control'].get('target_refresh_ms',250)/1000
                rejected=[]
                if frame is not None:
                    rejected=self.gate.check(frame,status['uptime_ms'],diagnostic_test=self.diagnostic_test)
                    with self.lock:self.state['frame']=frame.as_dict();self.state['frame_header']=list(frame.header);self.valid_input=not rejected;self.frame_received=now
                    if rejected:
                        with self.lock:self.fusion.reset();self.input_generation+=1
                        self.set(model=None,decision=dict(model_state='INVALID_INPUT',reason=','.join(rejected),level=status['alarm_level']))
                        if self.soft_nonzero and owned:self.enqueue_command(self.boot,5,0x100);self.soft_nonzero=False
                    else:
                        item=(self.boot,frame,status,now,self.input_generation)
                        try:self.frames.put_nowait(item)
                        except queue.Full:
                            try:self.frames.get_nowait()
                            except queue.Empty:pass
                            try:self.frames.put_nowait(item)
                            except queue.Full:pass
                            with self.lock:self.state['frame_drops']+=1
                if self.recorder is not None:
                    self.capture_sequence+=1
                    self.recorder.submit(dict(sequence=self.capture_sequence,boot=self.boot+'/'+self.collector_session+'/'+str(self.connection_epoch),
                        link='ONLINE',received_at=now,now_ms=uptime,status=status,frame=frame,
                        configuration_words=feature_words,mailbox=mailbox,environment=environment,test=self.diagnostic_test,rejected=rejected))
                if self.observer is not None:
                    current=self.public_state()
                    model=current.get('model')
                    model_required=(not self.diagnostic_test and self.config['model']['backend']=='npu_v4' and
                                    self.config['model'].get('qualified') is True and bool(self.config['model'].get('evidence')))
                    self.observation_sequence+=1
                    self.observer.submit(dict(sequence=self.observation_sequence,boot=self.boot+'/'+self.collector_session+'/'+str(self.connection_epoch),link='ONLINE',
                                              received_at=now,reported_at=time.time(),status=status,frame=frame,
                                              mailbox=mailbox,environment=environment,feature_words=feature_words,test=self.diagnostic_test,
                                              icm_diagnostics=current.get('icm_diagnostics'),
                                              bench=bench_snapshot,normal_reference_guard=reference_guard,
                                              control=dict(enabled=owned,regulation_mode=self.regulation_mode,temperature_enabled=self.regulation_mode=='temperature' and self.config['temperature_loop'].get('enabled',False),
                                                  binding_error=binding_error,requested_enabled=self.config['control'].get('enabled',False),
                                                  setpoint_C=self.outer.c.get('setpoint_C'),coordination=dict(self.outer.coordination),
                                                  temperature_pwm=self.temperature_pwm.snapshot(now),
                                                  control_words=control_words),
                                              model=model,model_required=model_required,
                                              model_state=(current.get('decision') or {}).get('model_state'),
                                              model_formal=model_required and bool(model and model.get('formal') is True and model.get('test') is False),
                                              model_fresh=bool(model and self.valid_input and
                                                  (current.get('decision') or {}).get('model_state') not in ('EXPIRED','INVALID_INPUT','UNAVAILABLE','REJECTED_CONFIDENCE','REJECTED_MARGIN','NORMAL_CANDIDATE'))))
                event=self.controller.event()
                if event is not None and self.pending_fifo is None:
                    self.pending_fifo=(self.boot,event[0])
                    if not self.put_journal(('fifo',self.boot,event)):self.pending_fifo=None
                self.poll_waveform()
                self.put_journal(('status',self.boot,self.public_state()))
            except Exception as e:
                catch_up=False
                self.bench.lost_link(e)
                self.temperature_pwm.lost_link(e)
                self.set(link='OFFLINE',environment=unavailable('OFFLINE'),model=None,decision=dict(model_state='UNAVAILABLE',level=0),error=type(e).__name__+': '+str(e))
                self.parameters.process()
                if self.recorder is not None:
                    self.capture_sequence+=1
                    self.recorder.submit(dict(sequence=self.capture_sequence,boot=self.boot,link='OFFLINE',received_at=time.monotonic()))
                if self.observer is not None:
                    self.observation_sequence+=1
                    self.observer.submit(dict(sequence=self.observation_sequence,link='OFFLINE',received_at=time.monotonic()))
                self.put_journal(('status',self.boot or self.config['device_id']+'/CONNECTING',self.public_state()))
                with self.lock:self.fusion.reset();self.input_generation+=1
                self.valid_input=False;self.pending_fifo=None;self.boot=None
                try:
                    if self.controller:self.controller.close()
                except Exception:pass
                self.controller=None
                if self.stop.wait(0.5):break
            pause=self.config.get('poll_ms',128)/1000
            # BNC1 needs a renewal inside 500 ms. Do not spend another full
            # frame period asleep after its I/O/telemetry work. The sole MMIO
            # owner still performs every write and retains all bench checks.
            if self.bench.active is not None or self.bench.pending is not None:
                pause=min(pause,.02)
            # A real capture must keep the two-frame mailbox drained. Sleeping
            # a complete 128 ms hop after I/O leaves no budget for its work and
            # can drop otherwise valid windows while the recorder is active.
            if self.recorder is not None and self.recorder.snapshot().get('state')=='RECORDING':
                pause=min(pause,.02)
            self.stop.wait(0 if catch_up else pause)
        try:self.temperature_pwm.shutdown(self.controller)
        except Exception as error:self.set(error='Temperature PWM stop: '+str(error))
    def model_loop(self):
        while not self.stop.is_set():
            try:boot,frame,status,received,generation=self.frames.get(timeout=0.2)
            except queue.Empty:continue
            try:
                result=self.model.infer(frame,context=dict(session_id=self.collector_session,boot_id=boot,
                    generation=generation,now_ms=status['uptime_ms'],received_at=received))
                formal=not self.diagnostic_test and self.model.formal_result(result)
                result['formal']=formal
                result['fault_grade']=self.fault_grade.predict(frame,result)
                state=self.public_state();latest=state.get('status') or status
                latest_frame=state.get('frame') or {}
                if boot!=self.boot or generation!=self.input_generation or not self.valid_input or state['link']!='ONLINE' or (time.monotonic()-received)*1000>self.config['contract']['max_result_age_ms'] or elapsed32(latest['uptime_ms'],frame.header[4])>self.config['contract']['max_result_age_ms']:
                    continue
                if (latest_frame.get('feature_config_id'),latest_frame.get('calibration_id'))!=(frame.header[16],frame.header[17]):continue
                result['frame_end_ms']=frame.header[4]
                with self.lock:
                    if boot!=self.boot or generation!=self.input_generation:continue
                    decision=self.fusion.evaluate(result,latest,latest['uptime_ms'],formal=formal)
                    self.set(model=result,decision=decision)
                if self.config['control'].get('enabled') and formal:
                    level=1 if decision['model_state']=='CONFIRMED_MAINTENANCE' else 0
                    # No physical corroboration bit; no fan action is encoded.
                    self.enqueue_command(boot,5,(0x100+level)|((result['label_id']+1)<<16));self.soft_nonzero=level!=0
            except Exception as e:
                state=self.public_state();latest=state.get('status') or status
                if boot==self.boot:
                    with self.lock:self.set(model=None,decision=self.fusion.evaluate(None,latest,latest['uptime_ms']),error='Model: '+type(e).__name__+': '+str(e))
                    if self.soft_nonzero:self.enqueue_command(boot,5,0x100);self.soft_nonzero=False
    def journal_loop(self):
        while not self.stop.is_set() or not self.journal.empty():
            try:kind,boot,payload=self.journal.get(timeout=0.2)
            except queue.Empty:continue
            try:
                if kind=='parameter_audit':
                    self.store.diagnostic('PARAMETER_RESULT',payload)
                elif kind=='bench_trace':
                    self.store.diagnostic('COMMISSIONING_BENCH_TRACE',payload)
                elif kind=='waveform':
                    token=boot
                    self.store.waveform(token[2],payload)
                    self.store.history.index_waveform(self.config['device_id'],token[2],payload)
                    with self.lock:self.wave_result=(token,None)
                elif kind=='fifo':
                    self.store.fifo(boot+'/'+str(payload[0]),payload,self.fifo_event(boot,payload))
                    with self.lock:
                        if boot==self.boot and self.pending_fifo==(boot,payload[0]):
                            self.fifo_ack_ready=(boot,payload[0])
                else:
                    state=payload;status=dict(state.get('status') or {})
                    capture_age=aged_ms(dict(state,capture_age_ms=0),'capture_age_ms',require_snapshot=True)
                    status_age=aged_ms(state,'status_age_ms',require_snapshot=True)
                    maximum=self.config.get('link_stale_ms',2000)
                    if (boot!=self.boot or capture_age is None or capture_age>maximum
                            or (state.get('link')=='ONLINE' and (status_age is None or status_age>maximum))):continue
                    status['test_mode']=status.get('test_mode',False) or state.get('test',False)
                    frame=state.get('frame') or {}
                    status.update(frame_id=frame.get('frame_id'),sensor_quality=frame.get('quality'),
                                  values_with_units=frame.get('values'),calibration_id=frame.get('calibration_id'),
                                  model_id=(state.get('model') or {}).get('model_id'),bitstream_id=frame.get('bitstream_id'))
                    if boot not in self.trackers:self.trackers[boot]=EventTracker(self.store,self.config['device_id'],boot)
                    tracker=self.trackers[boot]
                    if state.get('link')!='ONLINE':
                        self.link_tracker.update('PL_LINK_LOSS',1,True,status,source='SYSTEM')
                        if self.maintenance:
                            self.set(maintenance=self.maintenance.update(dict(state,boot_id=boot),time.time()))
                        if boot==self.boot:self.persist_status(state)
                        continue # stale status cannot recover a physical fault
                    self.link_tracker.update('PL_LINK_LOSS',0,False,status,source='SYSTEM')
                    decision=state.get('decision') or {}
                    if self.maintenance:
                        try:
                            maintenance=self.maintenance.update(dict(state,boot_id=boot),time.time())
                            self.set(maintenance=maintenance)
                            alert=maintenance.get('state')=='THRESHOLD_FORECAST'
                            if alert:
                                tracker.update('DEGRADATION_FORECAST',1,True,
                                    dict(status,maintenance=maintenance),source='PREDICTION',notify=maintenance.get('advisory_qualified') is True)
                        except (ValueError,KeyError,TypeError) as failure:
                            self.maintenance.predictor.update(None,time.time(),0,False)
                            self.set(maintenance=dict(state='UNAVAILABLE',remaining_life_s=None,error=str(failure),control_authority=False))
                    for code,present in [('MODEL_UNAVAILABLE',self.config['model']['backend']!='disabled' and decision.get('model_state')=='UNAVAILABLE'),
                                         ('DATA_INVALID',decision.get('model_state') in ('INVALID_INPUT','EXPIRED')),
                                         ('UPLINK_OFFLINE',bool(state.get('uplink_error'))),
                                         ('EVENT_FIFO_LOSS',bool(status.get('lost_events')))]:
                        tracker.update(code,1 if present else 0,present,status,source='SYSTEM')
                    active=set(status.get('active',[])+status.get('latched',[]))
                    for code in active:
                        tracker.update(code,3 if code in HARD else 2 if code in WARN else 1,True,status)
                    for key in list(tracker.active):
                        source,code=key.split(':',1)
                        if source=='PL' and code not in active:tracker.update(code,0,False,status)
                    self.model_events(tracker,state,status)
                    if boot==self.boot:self.persist_status(state)
            except Exception as e:
                self.set(error='Journal unavailable: '+str(e))
                if kind=='fifo':self.pending_fifo=None # retain PL head; retry persistence
                if kind=='waveform':
                    with self.lock:self.wave_result=(boot,str(e))
    def model_events(self,tracker,state,status):
        model=state.get('model') or {};model_state=(state.get('decision') or {}).get('model_state')
        if model:
            maximum=self.config['contract']['max_result_age_ms']
            status_age=aged_ms(state,'status_age_ms',require_snapshot=True)
            frame_age=aged_ms(state,'frame_age_ms',require_snapshot=True)
            end=model.get('frame_end_ms');uptime=status.get('uptime_ms')
            result_age=aged_ms(dict(state,result_age_ms=elapsed32(uptime,end)),'result_age_ms',require_snapshot=True) if type(end) is int and type(uptime) is int else None
            if state.get('link')!='ONLINE' or any(age is None or age>maximum for age in (status_age,frame_age,result_age)):return
        label=model.get('label')
        try:formal=not self.diagnostic_test and self.model.formal_result(model)
        except (ValueError,RuntimeError,OSError):formal=False
        confirmed=formal and model_state=='CONFIRMED_MAINTENANCE' and label!='normal'
        normal=formal and label=='normal' and model_state=='NORMAL_OBSERVATION'
        accepted=model_state in ('CANDIDATE','CONFIRMED_MAINTENANCE','TEST_OBSERVATION','OBSERVATION_UNQUALIFIED')
        evidence=dict(status,model_evidence_state=model_state or 'UNAVAILABLE',model_admission_sha256=model.get('admission_sha256'),fault_grade=model.get('fault_grade'))
        if label and label!='normal' and accepted:
            old=tracker.active.get('MODEL:'+label)
            established=bool(old and old.get('notify'))
            tracker.update(label,1 if confirmed or established else 0,True,evidence,source='MODEL',notify=confirmed or established)
        for key,old in list(tracker.active.items()):
            source,code=key.split(':',1)
            if source!='MODEL' or (code==label and accepted):continue
            if normal or not old.get('notify'):
                tracker.update(code,0,False,evidence,source='MODEL',notify=bool(old.get('notify')))
            else:
                tracker.update(code,old['severity_current'],True,evidence,source='MODEL',notify=True)
    def fifo_event(self,boot,words):
        if len(words)!=8 or any(type(x) is not int or not 0<=x<=0xffffffff for x in words):
            raise ValueError('Eight uint32 FIFO words required')
        seq,uptime,active,latched,meta,changed,cfg,lost=words
        names=lambda mask:[name for bit,name in enumerate(FCB1.FAULTS) if mask & (1<<bit)]
        return dict(event_id=hashlib.sha256((boot+'/FIFO/'+str(seq)).encode()).hexdigest()[:32],
                    event_revision=1,device_id=self.config['device_id'],boot_id=boot,code='PL_TRANSITION',source='PL_FIFO',
                    # This is historical evidence, never a claim about current
                    # actuators. Live per-cause lifecycle uses fresh status.
                    state='RECORDED',severity_current=0,severity_peak=meta&3,acknowledged=False,
                    notify=bool(meta&3 or changed),event_sequence=seq,uptime_ms=uptime,
                    active_causes=names(active),latched_causes=names(latched),changed_causes=names(changed),
                    actual_action={'fan_action':FCB1.FAN_ACTIONS[(meta>>6)&7]},
                    protection_latched=bool(latched),config_id=cfg,record_loss_count=lost,raw_words=words,
                    maintenance_test_flag=self.diagnostic_test or bool(meta&0x2000),
                    wall_time=datetime.now(timezone.utc).isoformat(),wall_time_valid=False)
    def uplink_loop(self):
        while not self.stop.wait(0.25):
            try:
                self.uplink.once();self.set(uplink_error=self.uplink.last_error)
                if self.uplink.backhaul:self.set(backhaul=dict(self.uplink.backhaul.status))
            except Exception as e:self.set(uplink_error=str(e))
    def close(self):
        self.stop.set()
        self.pressure.close()
        if self.parameter_rpc is not None:self.parameter_rpc.close();self.parameter_rpc=None
        from commissioning.bench import BenchController
        self.bench=BenchController(self)
        for thread in self.threads:thread.join(timeout=3)
        if any(t.is_alive() for t in self.threads):raise RuntimeError('Worker failed to stop within bounded deadline')
        if self.controller:self.controller.close()
        if self.observer is not None:self.observer.close()
        if self.recorder is not None:self.recorder.close()
        self.store.close()
