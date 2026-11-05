"""Read the sole collector, execute a normal-only NPU model, publish advisory results."""
import argparse
import json
import os
from pathlib import Path
import signal
import stat
import time
from .bundle import Bundle
from .core import live_input,prepare,score
from .native import Supervisor
from .advisory import Advisory
from v4_runtime.bundle import loads

def read_state(path):
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022 or info.st_size>1048576:
            raise ValueError('Unsafe collector state')
        with os.fdopen(fd,'rb',closefd=False) as stream:return loads(stream.read(1048577).decode('utf-8'))
    finally:os.close(fd)

def publish(path,value):
    temp=path.with_name(path.name+'.next')
    with temp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    temp.chmod(0o600);os.replace(str(temp),str(path))

def publish_live(path,value,sample=None):
    """Give the read-only display the validated result without a UI round trip."""
    from .presentation import fields
    publish(path,value)
    rendered=fields(sample or {},time.monotonic(),path,os_boot=value['os_boot_id'])
    rendered['panel_nn_present']='1'
    rendered['panel_nn_model_sha256']=value['model_sha256']
    if not value.get('valid'):
        rendered.update(panel_nn_valid='0',panel_nn_state=value.get('status','WAITING_INPUT'),
                        panel_nn_reason=str(value.get('reason') or value.get('status','WAITING_INPUT')))
    context=(sample['boot']+'|'+','.join(str(v) for v in sample['feature_words'])) if (
        type(sample) is dict and isinstance(sample.get('boot'),str) and type(sample.get('feature_words')) is list) else ''
    source_status=sample.get('status',{}) if type(sample) is dict else {}
    header=dict(display_schema='cabinet-normal-display-v2',display_os_boot=value['os_boot_id'],
                display_collector_context=context,display_status_uptime_ms=source_status.get('uptime_ms',''))
    header.update(rendered)
    target=path.with_name(path.stem+'.display.txt');temp=target.with_name(target.name+'.next')
    text=''.join(str(k)+'='+str(v).replace('\n',' ').replace('\r',' ')+'\n' for k,v in header.items())
    temp.write_text(text,encoding='utf-8');temp.chmod(0o600);os.replace(str(temp),str(target))

def check_start_selection(args):
    # Import on invocation: start_gate itself imports read_state from this module.
    from .boot_selection import require_live_selection
    return require_live_selection(args)

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--library',type=Path,required=True);p.add_argument('--library-sha256',required=True)
    p.add_argument('--input',type=Path,default=Path('/run/cabinet-live/npu_input.json'))
    p.add_argument('--output',type=Path,default=Path('/run/cabinet-normal-npu/state.json'))
    a=p.parse_args();check_start_selection(a)
    bundle=Bundle(a.bundle,a.manifest_sha256);a.output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    splits=bundle.provenance['sessions']
    session_count=sum(len(group.get('session_ids', [group.get('session_id')])) for group in splits.values())
    base={'schema':'cabinet-normal-npu-live-v1','os_boot_id':boot,'model_id':bundle.manifest['model_id'],
          'model_sha256':a.manifest_sha256,'model_source':bundle.manifest['source'],'training_rows':bundle.manifest['training_rows'],
          'backend':'Alnpu','execution_model':'ALNPU_NORMAL_RECONSTRUCTION_39','formal':False,
          'input_contract':bundle.expected,
          'reference_session_count':session_count,'reference_total_rows':sum(group['rows'] for group in splits.values()),
          'fault_classes_trained':[],'control_authority':'NONE','updated_at':time.monotonic(),'valid':False,
          'status':'LOADING','inference_count':0}
    advisory=Advisory();base['advisory']=advisory.invalidate('LOADING')
    publish_live(a.output,base);stopping=[False]
    def stop(*unused):stopping[0]=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    supervisor=None;last_key=None;last_result=None;count=0;last_published=0;failure=None;gaps=0;sample=None
    try:
        check_start_selection(a)
        supervisor=Supervisor(a.bundle,a.manifest_sha256,a.library,a.library_sha256)
        publish(a.output.parent/'native_graph_audit.json',supervisor.ready)
        while not stopping[0]:
            now=time.monotonic()
            try:
                document=read_state(a.input)
                sample=document.get('observation') if type(document) is dict else None
                # A new collector publication can arrive after the loop began.
                # Keep its source timestamp and check it using the read-end clock.
                now=time.monotonic()
                values,identity=live_input(document,now,bundle.expected,allow_temperature_pwm=True)
                key=(identity['collector_boot'],identity['frame_id'])
                if key==last_key:
                    if last_result and now>=last_result['input_deadline']:raise ValueError('FRAME_STALE')
                    time.sleep(.025);continue
                if last_key and (key[0]!=last_key[0] or (key[1]-last_key[1])&0xffffffff!=1):gaps+=1
                last_key=key
                started=time.monotonic();z,q,clipped=prepare(values,bundle.norm)
                native=supervisor.infer(q);result=score(z,native['output'],bundle.norm,bundle.thresholds,clipped)
                completed=time.monotonic();count+=1
                if completed>=identity['input_deadline']:raise ValueError('FRAME_STALE')
                last_result=dict(base,**identity,**result)
                last_result.update(valid=True,status='RUNNING',updated_at=completed,execute_ms=native['execute_ms'],
                    total_ms=(completed-started)*1000,inference_count=count,observed_frame_gaps=gaps,
                    input_sha256=__import__('hashlib').sha256(q).hexdigest(),output_u8=list(native['output']),
                    input_values=values,source='REAL_CURRENT_SENSOR_FRAME')
                if not identity['baseline_eligible']:
                    last_result['model_assessment']=last_result['assessment']
                    last_result['assessment']='OUTSIDE_OPERATING_REFERENCE'
                last_result['advisory']=advisory.observe(last_result,completed)
                publish_live(a.output,last_result,sample);last_published=completed
            except (OSError,ValueError) as error:
                reason=str(error)
                # A poll with no newly queued FRM1 is normal; retain only a bounded fresh result.
                if reason=='NO_NEW_REAL_FRAME' and last_result and now<last_result['input_deadline']:
                    time.sleep(.025);continue
                temporal=advisory.invalidate(reason)
                was_valid=last_result is not None;last_result=None
                if was_valid or now-last_published>.1:
                    publish_live(a.output,dict(base,status='WAITING_INPUT',reason=reason,valid=False,updated_at=now,
                                         inference_count=count,observed_frame_gaps=gaps,advisory=temporal),sample);last_published=now
            time.sleep(.025)
    except (Exception,KeyboardInterrupt) as error:
        failure=type(error).__name__+': '+str(error)
    finally:
        try:clean=supervisor.close() if supervisor is not None else False
        except Exception as error:
            clean=False;failure=(failure+'; ' if failure else '')+'Native cleanup: '+repr(error)
        publish_live(a.output,dict(base,status='STOPPED' if failure is None and clean else 'NATIVE_FAULT',
            valid=False,reason=failure,updated_at=time.monotonic(),inference_count=count,
            native_cleanup_verified=clean,forced_native_kill=False,
            advisory=advisory.invalidate('NATIVE_FAULT' if failure else 'STOPPED')),sample)
    if failure:raise RuntimeError(failure)

if __name__=='__main__':main()
