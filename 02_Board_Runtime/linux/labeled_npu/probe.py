"""Replay balanced real held-out labels on the actual exclusive Alnpu accelerator."""
import argparse
import json
import os
from pathlib import Path
import time
from normal_npu.live import read_state,publish
from normal_npu.probe import irq_counts
from .bundle import Bundle,prepare,classify,quality,validate_quality
from .core import live_input,LABELS
from .native import Supervisor

def validate_report(r, pin, adapter_pin, boot, kernel):
    if (r.get('status')!='PASS_REAL_LABELED_CAPTURE_ALNPU_CLASSIFICATION_ONLY'
            or r.get('source')!='REAL_USER_DECLARED_LABELED_DIAGNOSTIC' or r.get('qualified') is not False
            or r.get('control_authority')!='NONE' or r.get('npu_executed') is not True
            or r.get('native_cleanup_verified') is not True or r.get('model_sha256')!=pin
            or r.get('adapter_sha256')!=adapter_pin or r.get('boot_id')!=boot or r.get('kernel_release')!=kernel):
        raise ValueError('PINNED_REAL_LABELED_HARDWARE_PROBE_REQUIRED')
    if r.get('vectors')!=160 or r.get('irq_delta')!={'HARD_NPU_IRQ':480,'SOFT_NPU_IRQ':0}: raise ValueError('CLASSIFIER_IRQ_EVIDENCE_CHANGED')
    audit=r.get('backend_audit',{})
    if audit.get('assigned_backends')!=['Alnpu'] or audit.get('backend_assignment_verified') is not True: raise ValueError('ALNPU_ONLY_GRAPH_REQUIRED')
    if (type(r.get('max_probability_lsb_error')) is not int or not 0<=r['max_probability_lsb_error']<=3
            or not .98<=r.get('class_agreement',-1)<=1 or not 0<r.get('execute_p99_ms',-1)<128
            or r.get('heldout_quality',{}).get('status')!='PASS_ENGINEERING_QUALITY_ONLY'):
        raise ValueError('CLASSIFIER_HARDWARE_NUMERICAL_GATES_FAILED')
    validate_quality(r['heldout_quality'])

def main(argv=None):
    p=argparse.ArgumentParser()
    for name in ('bundle','manifest-sha256','library','library-sha256','output'): p.add_argument('--'+name,required=True)
    a=p.parse_args(argv); b=Bundle(a.bundle,a.manifest_sha256); b.hardware_model()
    directory=Path(a.output); directory.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',source=b.manifest['source'],model_sha256=b.pin,adapter_sha256=a.library_sha256,
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),kernel_release=os.uname().release,
        qualified=False,control_authority='NONE',npu_executed=False,rows=[])
    supervisor=None; clean=False; failure=None
    try:
        for unused in range(100):
            try: live_input(read_state(Path('/run/cabinet-live/state.json')),time.monotonic(),b.expected); break
            except (ValueError,OSError): time.sleep(.02)
        else: raise ValueError('ACTUAL_MATCHING_REAL_PLATFORM_REQUIRED')
        supervisor=Supervisor(a.bundle,b.pin,a.library,a.library_sha256)
        report['backend_audit']=supervisor.ready['audit']; publish(directory/'native_metadata.json',supervisor.ready['metadata'])
        (directory/'optimized_graph.dot').write_text(supervisor.ready['graph'])
        before=irq_counts(); agreements=[]; errors=[]
        for vector in b.golden['vectors']:
            z,q=prepare(vector['values'],b.norm)
            if list(q)!=vector['input_u8']: raise ValueError('FROZEN_PREPROCESSING_CHANGED')
            native=supervisor.infer(q); output=native['output']; classify(output,b.policy)
            error=max(abs(x-y) for x,y in zip(output,vector['output_u8'])); errors.append(error)
            agreements.append(max(range(5),key=output.__getitem__)==max(range(5),key=vector['output_u8'].__getitem__))
            report['rows'].append(dict(label=vector['label'],output_u8=output,index=vector['index'],execute_ms=native['execute_ms'],max_probability_lsb_error=error))
            report['npu_executed']=True
        after=irq_counts(); report['irq_delta']={n:after[n]-before[n] for n in before}
        report.update(vectors=len(errors),max_probability_lsb_error=max(errors),class_agreement=sum(agreements)/len(agreements),
            execute_p99_ms=sorted(r['execute_ms'] for r in report['rows'])[int((len(errors)-1)*.99)],
            heldout_quality=quality([v['label'] for v in b.golden['vectors']],[v['output_u8'] for v in report['rows']],b.policy))
        report['status']='PASS_REAL_LABELED_CAPTURE_ALNPU_CLASSIFICATION_ONLY'
    except BaseException as error:
        report.update(status='FAIL',error=str(error)); failure=error
    finally:
        if supervisor is not None: clean=supervisor.close()
        report['native_cleanup_verified']=clean
        if not clean: report['status']='FAIL_NATIVE_CLEANUP_REQUIRES_REVIEW'
        if failure is None:
            try: validate_report(report,b.pin,a.library_sha256,report['boot_id'],report['kernel_release'])
            except Exception as error: failure=error; report.update(status='FAIL',error=str(error))
        publish(directory/'validation.json',report)
    if failure is not None: raise RuntimeError(str(failure))
    return 0

if __name__=='__main__': main()
