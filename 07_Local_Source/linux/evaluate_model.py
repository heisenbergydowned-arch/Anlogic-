#!/usr/bin/env python3
"""Evaluate every pinned held-out REAL record on Alnpu, with exclusive native ownership.
Does not modify the live classifier, controller, FPGA or boot files.
"""
from cabinet.input_policy import fault_policy, model_values, semantics, input_state
import argparse,hashlib,json,multiprocessing as mp,os,subprocess,time
from pathlib import Path
from v4_runtime.bundle import Bundle,LABELS,digest
from v4_runtime.platform_gate import verify_platform_state
from v4_runtime.server import worker
from v4_runtime.native_lease import NATIVE_LEASE_FILE
from cabinet.protocol import Frame,FrameGate
from normal_npu.probe import irq_counts

def sha(p):return digest(Path(p).read_bytes())
def save(p,d):Path(p).write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def canonical(d):return json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def system(*args):return subprocess.run(['systemctl']+list(args),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=50)

def check_request(request,b):
    if (request.get('schema')!='cabinet-real-model-evaluation-v1' or request.get('source')!='REAL_FRM1_DECLARED'
            or request.get('bundle_manifest_sha256')!=b.manifest_sha256 or b.synthetic):raise ValueError('Matching real evaluation request required')
    rows=request.get('rows');gates={};seen=set()
    if type(rows) is not list or not 100<=len(rows)<=100000:raise ValueError('At least 100 test records required')
    test=request['dataset']['test_sessions'];train=request['dataset']['train_sessions']
    if not train or not test or len(set(train+test))!=len(train+test):raise ValueError('Session overlap')
    for r in rows:
        record=r['record']
        if (record.get('source')!='REAL_FRM1_DECLARED' or record.get('split')!='test' or record.get('label_reviewed') is not True
                or record.get('label_source')!='BENCH_REVIEWED' or record.get('label') not in LABELS):raise ValueError('Actual independently reviewed test records required')
        identity=digest(canonical(record))
        if r['sample_sha256']!=identity or identity in seen or r['session_sha256'] not in test:raise ValueError('Duplicate or changed test sample')
        seen.add(identity);frame=Frame.from_words(record['header'],record['feature_words'])
        key=tuple(record[k] for k in ('device_id','installation_id','session_id','boot_id'))
        reasons=gates.setdefault(key,FrameGate(b.contract)).check(frame,record['now_ms'])
        if reasons or frame.test  or frame.header[17]!=b.contract['calibration_id']:raise ValueError('Unqualified original frame: '+str(reasons))
        _,encoded=b.encode(model_values(frame,b.contract))
        if encoded!=r['input_u8']:raise ValueError('Preprocessing changed')
        b.decode(r['expected_u8'])
    if any(sum(r['record']['label']==label for r in rows)<20 for label in LABELS):raise ValueError('Every class needs >=20 held-out observations')
    return rows

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('bundle','request','library','output'):p.add_argument('--'+n,type=Path,required=True)
    for n in ('manifest-sha256','request-sha256','library-sha256'):p.add_argument('--'+n,required=True)
    a=p.parse_args(argv)
    if sha(a.request)!=a.request_sha256 or sha(a.library)!=a.library_sha256:raise ValueError('Evaluation inputs changed')
    request=json.loads(a.request.read_text())
    b=Bundle(a.bundle,a.manifest_sha256,graph_audit={'path':str(a.bundle/'candidate_graph.json'),'sha256':request['graph_sha256']})
    rows=check_request(request,b);platform_info=verify_platform_state('/run/cabinet-live/state.json')
    state=json.loads(Path('/run/cabinet-live/state.json').read_text())
    if state['display'].get('capture_state')=='RECORDING':raise ValueError('Finish the active capture before offline NPU evaluation')
    a.output.mkdir(parents=True,exist_ok=False)
    units=[n for n in ('cabinet-normal-npu','cabinet-npu-v4-shadow','cabinet-npu-formal') if system('is-active',n).stdout.strip()=='active']
    for n in units:
        if system('stop',n).returncode:raise RuntimeError('Could not stop '+n)
    if json.loads(NATIVE_LEASE_FILE.read_text())['state']!='CLEAN':raise RuntimeError('Retained native owner requires recovery; no forced kill')
    process=None;pipe=None;pending=False;clean=False
    report=dict(status='RUNNING',source='REAL_FRM1_DECLARED',request_sha256=a.request_sha256,backend='Alnpu',
        bundle_manifest_sha256=a.manifest_sha256,model_sha256=b.manifest['artifacts_sha256']['model_logits_u8.onnx'],
        library_sha256=a.library_sha256,pl_build_id=platform_info['pl_build_id'],hardware_profile=b.hardware_profile,
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),kernel_release=os.uname().release,
        device_id='machine:'+Path('/etc/machine-id').read_text().strip(),hardware_executed=False,
        actuator_commands_issued=False,qualified=False)
    predictions=[];errors=[];agreements=[];latencies=[]
    try:
        context=mp.get_context('spawn');pipe,child=context.Pipe()
        process=context.Process(target=worker,args=(child,dict(backend='alnpu',library_bytes=a.library.read_bytes()),b));process.start();child.close()
        if not pipe.poll(25):raise RuntimeError('Native load timeout; worker retained')
        ready=pipe.recv()
        if ready.get('ready') is not True:raise RuntimeError(str(ready))
        save(a.output/'native.json',ready)
        libraries={Path(line.split()[-1]).resolve() for line in Path('/proc/%d/maps'%process.pid).read_text().splitlines() if '/' in line and 'libarmnn.so' in line.lower()}
        if len(libraries)!=1:raise ValueError('Cannot bind loaded vendor SDK')
        report['sdk_path']=str(next(iter(libraries)));report['sdk_sha256']=sha(report['sdk_path']);before=irq_counts()
        for row in rows:
            pipe.send(row['input_u8']);pending=True
            if not pipe.poll(1):raise RuntimeError('Native inference deadline; worker retained')
            r=pipe.recv();pending=False
            if 'error' in r:raise RuntimeError(str(r))
            output=r['output'];b.decode(output);expected=row['expected_u8']
            predicted=max(range(5),key=output.__getitem__);errors.append(max(abs(x-y) for x,y in zip(output,expected)))
            agreements.append(predicted==max(range(5),key=expected.__getitem__));latencies.append(r['execute_ms'])
            predictions.append(dict(sample_sha256=row['sample_sha256'],session_sha256=row['session_sha256'],test=False,
                actual=row['record']['label'],predicted=LABELS[predicted],output_u8=output,execute_ms=r['execute_ms']))
        after=irq_counts();deltas={n:after[n]-before[n] for n in before}
        report.update(hardware_executed=True,cases=len(rows),class_agreement=sum(agreements)/len(agreements),
            max_probability_lsb_error=max(errors),p99_ms=sorted(latencies)[int(.99*(len(latencies)-1))],irq_delta=deltas)
        if deltas.get('HARD_NPU_IRQ')!=3*len(rows) or deltas.get('SOFT_NPU_IRQ')!=0:raise ValueError('Hardware IRQ execution differs')
        if max(errors)>1 or not all(agreements) or report['p99_ms']>=128:raise ValueError('Native numeric/class/deadline comparison failed')
        report['accuracy']=sum(r['actual']==r['predicted'] for r in predictions)/len(predictions)
        if report['accuracy']<.95:raise ValueError('Independent real test accuracy below 95%; retain old model')
        report['status']='PASS_REAL_MODEL_TARGET_EVALUATION'
    except BaseException as error:
        report.update(status='FAIL',error=repr(error));raise
    finally:
        if process is not None:
            try:
                if pending and pipe.poll(5):pipe.recv();pending=False
                if process.is_alive() and not pending:pipe.send(None)
                process.join(5)
                clean=not process.is_alive() and process.exitcode==0 and json.loads(NATIVE_LEASE_FILE.read_text())['state']=='CLEAN'
            except (OSError,EOFError,ValueError):clean=False
            if not clean:report.update(status='FAIL_NATIVE_CLEANUP_REQUIRES_REVIEW',retained_pid=process.pid)
        report['native_cleanup_verified']=clean
        save(a.output/'predictions.json',predictions);report['prediction_sha256']=sha(a.output/'predictions.json');save(a.output/'target.json',report)
        if clean:
            for n in units:
                if system('start',n).returncode:raise RuntimeError('Evaluation complete but previous NPU service did not resume: '+n)
        print(json.dumps(report,indent=2))
    return 0 if report['status'].startswith('PASS_') else 1
if __name__=='__main__':raise SystemExit(main())
