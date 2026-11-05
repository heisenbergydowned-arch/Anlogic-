"""Advisory classified results from fresh real frames; no actuator writes."""
import argparse
import json
from pathlib import Path
import signal
import time
from normal_npu.live import read_state,publish
from .bundle import Bundle,prepare,classify
from .core import live_input, runtime_decision
from .native import Supervisor
from .boot_selection import require_live_selection

def main():
    p=argparse.ArgumentParser()
    for name in ('bundle','manifest-sha256','library','library-sha256'): p.add_argument('--'+name,required=True)
    p.add_argument('--input',type=Path,default=Path('/run/cabinet-live/state.json'))
    p.add_argument('--output',type=Path,default=Path('/run/cabinet-labeled-npu/state.json'))
    a=p.parse_args(); require_live_selection(a); b=Bundle(a.bundle,a.manifest_sha256); b.hardware_model(); a.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    base=dict(schema='cabinet-labeled-npu-live-v1',model_sha256=b.pin,model_id=b.manifest['model_id'],
        model_source=b.manifest['source'],backend='Alnpu',execution_model='ALNPU_LOGITS_PS_SOFTMAX',
        labels=b.manifest['labels'],fault_classes_trained=b.manifest['labels'][1:],input_contract=b.expected,
        os_boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),qualified=False,
        formal=False,control_authority='NONE',training_rows=b.manifest['training_rows'])
    stopping=[False]
    def stop(*unused): stopping[0]=True
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    supervisor=None; last=None; last_result=None; count=0; failure=None
    try:
        live_input(read_state(a.input),time.monotonic(),b.expected)
        require_live_selection(a)
        supervisor=Supervisor(a.bundle,b.pin,a.library,a.library_sha256)
        publish(a.output.parent/'native_graph_audit.json',supervisor.ready)
        while not stopping[0]:
            try:
                doc=read_state(a.input); now=time.monotonic(); values,identity=live_input(doc,now,b.expected)
                key=(identity['collector_boot'],identity['frame_id'])
                if key==last:
                    if last_result and now-last_result['received_at']>.5: raise ValueError('FRAME_STALE')
                    time.sleep(.025); continue
                last=key; z,q=prepare(values,b.norm); native=supervisor.infer(q)
                result=runtime_decision(classify(native['output'],b.policy),identity); count+=1
                last_result=dict(base,**identity,**result); last_result.update(status='RUNNING',valid=True,
                    updated_at=time.monotonic(),inference_count=count,execute_ms=native['execute_ms'],
                    output_u8=native['output'],source='REAL_CURRENT_SENSOR_FRAME',
                    frame_header=doc['observation']['frame']['header'],
                    frame_status=doc['observation']['status'],
                    feature_identity=doc['observation']['frame']['header'][16:19])
                if len(json.dumps(last_result,ensure_ascii=False,allow_nan=False).encode('utf-8'))>32768:
                    raise ValueError('CLASSIFIER_RESULT_SIZE_BOUND')
                publish(a.output,last_result)
            except (ValueError,OSError) as error:
                now=time.monotonic()
                if str(error)=='NO_NEW_REAL_FRAME' and last_result and now-last_result['received_at']<=.5:
                    time.sleep(.025); continue
                last_result=None
                publish(a.output,dict(base,status='WAITING_INPUT',valid=False,reason=str(error),
                    updated_at=now,inference_count=count))
            time.sleep(.025)
    except (Exception,KeyboardInterrupt) as error: failure=str(error)
    finally:
        clean=supervisor.close() if supervisor is not None else False
        publish(a.output,dict(base,status='NATIVE_FAULT' if failure or not clean else 'STOPPED',valid=False,
            reason=failure,updated_at=time.monotonic(),inference_count=count,native_cleanup_verified=clean))
    if failure: raise RuntimeError(failure)

if __name__=='__main__': main()
