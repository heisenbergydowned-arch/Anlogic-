"""Replay real captured vectors through the hardware normal-reference network."""
import argparse,json,os,statistics,time
from pathlib import Path
from .bundle import Bundle,digest
from .core import live_input,prepare,score
from .native import Supervisor
from .live import read_state
from .numerical import review_extended_rows

def irq_counts():
    counts={}
    for line in Path('/proc/interrupts').read_text().splitlines():
        for name in ['HARD_NPU_IRQ','SOFT_NPU_IRQ']:
            if line.endswith(name):counts[name]=sum(int(x) for x in line.split()[1:3])
    return counts

def require_probe_context(bundle,saved_startup=False):
    if saved_startup:
        # These pinned vectors were captured and admitted previously. Hardware
        # arithmetic does not depend on today's fan duty or sensor readiness.
        device='machine:'+Path('/etc/machine-id').read_text().strip()
        if bundle.expected.get('device_id')!=device:raise ValueError('Saved model belongs to another board')
        return
    for unused in range(100):
        try:live_input(read_state(Path('/run/cabinet-live/state.json')),time.monotonic(),bundle.expected);return
        except (OSError,ValueError):time.sleep(.02)
    raise RuntimeError('Actual matching real platform required')

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--library',type=Path,required=True);p.add_argument('--library-sha256',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--saved-startup',action='store_true');a=p.parse_args(argv)
    b=Bundle(a.bundle,a.manifest_sha256);a.output.mkdir(parents=True,exist_ok=False)
    require_probe_context(b,a.saved_startup)
    supervisor=None;report={'status':'RUNNING','source':b.manifest['source'],'qualified':False,'fault_classes_trained':[],
        'model_sha256':a.manifest_sha256,'adapter_sha256':a.library_sha256,'npu_executed':False,
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'kernel_release':os.uname().release,'rows':[],
        'probe_context':'SAVED_REAL_VECTORS_CURRENT_BOARD' if a.saved_startup else 'CURRENT_MATCHING_COLLECTOR'}
    clean=False
    try:
        supervisor=Supervisor(a.bundle,a.manifest_sha256,a.library,a.library_sha256)
        report['backend_audit']=supervisor.ready['audit']
        (a.output/'optimized_graph.dot').write_text(supervisor.ready['graph'])
        (a.output/'native_metadata.json').write_text(json.dumps(supervisor.ready['metadata'],indent=2)+'\n')
        before=irq_counts()
        for vector in json.loads(b.data['golden.json'].decode())['vectors']:
            z,q,clipped=prepare(vector['values'],b.norm);assert list(q)==vector['input_u8']
            result=supervisor.infer(q);output=result['output'];advisory=score(z,output,b.norm,b.thresholds,clipped)
            error=max(abs(int(x)-int(y)) for x,y in zip(output,vector['reconstruction_u8']))
            report['rows'].append({'split':vector['split'],'index':vector['index'],'input_sha256':digest(q),
                'output_u8':list(output),'max_quantized_error':error,'execute_ms':result['execute_ms'],
                'reference_output_u8':vector['reconstruction_u8'],
                'reference_state':vector['expected_advisory']['state'],
                'reference_score':vector['expected_advisory']['score'],
                'score':advisory['score'],'state':advisory['state']})
            report['npu_executed']=True
        after=irq_counts();report['irq_delta']={n:after[n]-before[n] for n in before}
        report['max_quantized_error']=max(r['max_quantized_error'] for r in report['rows'])
        test=[r for r in report['rows'] if r['split']=='test']
        report['normal_holdout_alarm_rate']=sum(r['state']!='BASELINE_MATCH' for r in test)/len(test)
        report['vectors']=len(report['rows']);report['execute_ms']={n:sorted(r['execute_ms'] for r in report['rows'])[int((len(report['rows'])-1)*q)] for n,q in [('p50',.5),('p95',.95),('p99',.99)]}
        report['numerical_review']=review_extended_rows(report)
        assert report['normal_holdout_alarm_rate']<=.05,'Real normal holdout alarm budget exceeded'
        assert report['irq_delta']['HARD_NPU_IRQ']==3*report['vectors'],'Hardware IRQ evidence differs'
        assert report['irq_delta']['SOFT_NPU_IRQ']==0,'Unexpected soft NPU execution'
        assert report['execute_ms']['p99']<128,'Window deadline exceeded'
        report['status']='PASS_REAL_NORMAL_CAPTURE_ALNPU_RECONSTRUCTION_ONLY'
    except BaseException as error:
        report.update(status='FAIL',error=repr(error));raise
    finally:
        if supervisor is not None:clean=supervisor.close()
        report['native_cleanup_verified']=clean
        if not clean:report['status']='FAIL_NATIVE_CLEANUP_REQUIRES_REVIEW'
        (a.output/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
    return 0 if report['status'].startswith('PASS_') else 1

if __name__=='__main__':raise SystemExit(main())
