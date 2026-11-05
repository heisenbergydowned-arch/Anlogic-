"""Two-step, bounded PS setpoint changes executed only by the existing owner."""
from collections import OrderedDict
import math
import secrets
import threading
import time
from v4_runtime.qualification import pinned_json


class ParameterControl:
    def __init__(self,service):
        self.service=service;self.lock=threading.RLock();self.revision=0
        self.previews=OrderedDict();self.results=OrderedDict();self.pending=None
        self.config=service.config.get('parameter_control',{})
        if type(self.config) is not dict or set(self.config)-{'enabled','profile','sha256','local_socket'} or type(self.config.get('enabled',False)) is not bool:
            raise ValueError('Invalid parameter-control configuration')
        self.profile=None
        if self.config.get('enabled'):
            if (not {'enabled','profile','sha256'}<=set(self.config) or type(self.config['sha256']) is not str
                    or len(self.config['sha256'])!=64 or any(character not in '0123456789abcdef' for character in self.config['sha256'])):
                raise ValueError('Externally pinned commissioning profile required')
            self.profile=pinned_json(self.config.get('profile'),self.config.get('sha256'))
            profile=self.profile
            if set(profile)!={'schema','device_id','control_evidence','temperature_evidence','calibration_id','feature_config_id','pl_build_id','setpoint_C'} or profile['schema']!='cabinet-parameter-envelope-v1':
                raise ValueError('Explicit commissioned parameter envelope required')
            bounds=profile['setpoint_C']
            if (type(bounds) is not list or len(bounds)!=2 or any(type(value) not in (int,float) or not math.isfinite(value) for value in bounds)
                    or not -55<=bounds[0]<bounds[1]<=125):
                raise ValueError('Invalid commissioned setpoint range')
            config=service.config
            if (profile['device_id']!=config['device_id'] or profile['control_evidence']!=config['control'].get('evidence')
                    or profile['temperature_evidence']!=config['temperature_loop'].get('evidence') or not profile['control_evidence'] or not profile['temperature_evidence']
                    or type(profile['calibration_id']) is not int or profile['calibration_id']<=0
                    or profile['calibration_id']!=config['contract'].get('calibration_id')
                    or type(profile['pl_build_id']) is not int or type(profile['feature_config_id']) is not int
                    or profile['feature_config_id']!=config['contract'].get('feature_config_id')):
                raise ValueError('Commissioning profile does not bind this device/control/contract')

    def context(self):
        return dict(collector_session=self.service.collector_session,connection_epoch=self.service.connection_epoch,boot_id=self.service.boot)

    def guard(self,recheck_profile=True):
        service=self.service;config=service.config
        if self.profile is None or service.stop.is_set():raise ValueError('Parameter writes are disabled or stopping')
        if config['control'].get('regulation_mode','temperature')!='temperature':raise ValueError('Temperature setpoint requires temperature regulation mode')
        if recheck_profile:pinned_json(self.config['profile'],self.config['sha256'])
        state=service.public_state();status=state.get('status') or {};frame=state.get('frame') or {}
        if config.get('commissioning'):
            owner=state.get('control_owner') or {}
            if (owner.get('verified') is not True or owner.get('binding_error') or
                    any(owner.get(k)!=v for k,v in self.context().items())):
                raise ValueError('Current collector has not verified the commissioned control owner')
        if (service.mock or service.diagnostic_test or not service.valid_input or state.get('test') is not False
                or config['control'].get('enabled') is not True or config['control'].get('qualified') is not True
                or config['temperature_loop'].get('enabled') is not True or config['temperature_loop'].get('qualified') is not True
                or state.get('link')!='ONLINE' or type(state.get('status_age_ms')) not in (int,float) or not 0<=state['status_age_ms']<=500
                or type(state.get('frame_age_ms')) not in (int,float) or not 0<=state['frame_age_ms']<=500
                or status.get('configured') is not True or status.get('mode')!='RUN' or status.get('active') or status.get('latched')
                or frame.get('quality')!=0 or frame.get('test') is not False or not service.boot
                or frame.get('calibration_id')!=self.profile['calibration_id'] or frame.get('feature_config_id')!=self.profile['feature_config_id']
                or frame.get('bitstream_id')!=format(self.profile['pl_build_id'],'08x')
                or (status.get('input_validity') or {}).get('temperature') is not True
                or type(status.get('temp_age_ms')) not in (int,float) or not 0<=status['temp_age_ms']<=min(2000,config['temperature_loop']['temp_age_ms'])):
            raise ValueError('Fresh commissioned fault-free live owner required; no enable/reset/protection bypass')

    def summary(self):
        with self.lock:
            reason=None
            if self.profile is None:reason='PARAMETERS_NOT_COMMISSIONED'
            elif self.service.config['control'].get('regulation_mode','temperature')!='temperature':reason='FIXED_SPEED_MODE'
            elif not self.service.config['control'].get('enabled') or not self.service.config['temperature_loop'].get('enabled'):reason='CONTROL_DISABLED'
            else:
                try:self.guard(recheck_profile=False)
                except (ValueError,OSError):reason='LIVE_OWNER_NOT_READY'
            return dict(enabled=reason is None,profile_loaded=self.profile is not None,readiness_reason=reason,
                revision=self.revision,context=self.context(),
                setpoint_C=self.service.outer.c.get('setpoint_C'),bounds=self.profile['setpoint_C'] if self.profile else None,
                pending=self.pending['request_id'] if self.pending else None,recent=list(self.results.values())[-10:],
                persistence='RUNTIME_ONLY_RESTART_RESTORES_COMMISSIONED_CONFIG',pl_output_confirmed=False)

    def preview(self,request):
        with self.lock:
            self.guard()
            if (type(request) is not dict or set(request)!={'request_id','expected_revision','context','setpoint_C'}
                    or type(request['request_id']) is not str or len(request['request_id'])!=32
                    or any(character not in '0123456789abcdef' for character in request['request_id'])
                    or type(request['expected_revision']) is not int or request['expected_revision']!=self.revision
                    or request['context']!=self.context() or type(request['setpoint_C']) not in (int,float)
                    or not math.isfinite(request['setpoint_C']) or not self.profile['setpoint_C'][0]<=request['setpoint_C']<=self.profile['setpoint_C'][1]
                    or self.pending is not None):
                raise ValueError('Stale context, revision, range or unsupported parameter')
            identity=request['request_id']
            if identity in self.results:raise ValueError('Request identity already used')
            now=time.monotonic()
            self.previews={key:value for key,value in self.previews.items() if value['expires_at']>=now}
            if len(self.previews)>=32:raise ValueError('Too many outstanding previews')
            result=dict(request,nonce=secrets.token_hex(16),expires_at=now+30,expires_in_s=30,state='PREVIEW_NOT_APPLIED',previous_setpoint_C=self.service.outer.c['setpoint_C'])
            self.previews[identity]=result
            return dict(result)

    def commit(self,request):
        with self.lock:
            if type(request) is not dict or set(request)!={'request_id','nonce'}:raise ValueError('Preview nonce required')
            previous=self.results.get(request['request_id'])
            if previous is not None:
                if not secrets.compare_digest(str(previous['nonce']),str(request['nonce'])):raise ValueError('Conflicting command identity')
                return dict(previous)
            self.guard();preview=self.previews.get(request['request_id'])
            if (preview is None or preview['nonce']!=request['nonce'] or time.monotonic()>preview['expires_at']
                    or preview['context']!=self.context() or preview['expected_revision']!=self.revision or self.pending is not None):
                raise ValueError('Expired or superseded preview')
            command=dict(preview,state='QUEUED_NOT_APPLIED')
            self.service.store.diagnostic('PARAMETER_INTENT',command)
            self.pending=command;self.results[command['request_id']]=command
            while len(self.results)>64:self.results.popitem(last=False)
            self.previews.pop(command['request_id'])
            return dict(command)

    def process(self):
        if not self.lock.acquire(False):return False
        try:return self.process_locked()
        finally:self.lock.release()

    def process_locked(self):
        with self.lock:
            if self.pending is None:return
            command=self.pending;self.pending=None
            try:
                self.guard(recheck_profile=False)
                if command['context']!=self.context() or command['expected_revision']!=self.revision or time.monotonic()>command['expires_at']:
                    raise ValueError('Queued command expired or owner changed')
                result=dict(command,state='APPLIED_PS_SETPOINT_NOT_PL_OUTPUT_CONFIRMATION',revision=self.revision+1)
                if not self.service.put_journal(('parameter_audit',self.service.boot,result)):
                    raise ValueError('Audit queue unavailable')
                self.service.outer.c=dict(self.service.outer.c,setpoint_C=command['setpoint_C'])
                # Preserve the active PI state. Reseeding from the same RPM
                # against the NEW temperature error would cancel the entire
                # proportional response (and ignore the change when Ki=0).
                # The existing RPM slew limit bounds the resulting transition.
                self.revision+=1
            except (ValueError,OSError) as error:
                result=dict(command,state='REJECTED_NOT_APPLIED',error=str(error),revision=self.revision)
                self.service.put_journal(('parameter_audit',self.service.boot,result))
            self.results[command['request_id']]=result
