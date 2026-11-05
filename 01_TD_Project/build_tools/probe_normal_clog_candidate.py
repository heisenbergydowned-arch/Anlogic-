"""Replay a scoped candidate on Alnpu and restore the selected normal model.

This records hardware arithmetic evidence, not live class agreement or an
installation of a new startup model. No control register is written.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,d):
    raw=(json.dumps(d,indent=2)+'\n').encode();temporary=p.with_suffix(p.suffix+'.tmp')
    with temporary.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(str(temporary),str(p));fd=os.open(str(p.parent),os.O_RDONLY);os.fsync(fd);os.close(fd)


def run_engine(a):
    sys.path.insert(0,'/opt/cabinet/linux')
    from labeled_npu.native import Engine
    from v4_runtime.native_lease import NativeLease
    from normal_npu.probe import irq_counts
    from normal_npu.core import prepare
    assert Path('/etc/machine-id').read_text().strip()=='843ad8d6299240c898a32874a96fe333'
    assert sha(a.candidate/'manifest.json')==a.manifest
    m=read(a.candidate/'manifest.json')
    assert m['schema']=='cabinet-scoped-training-candidate-v1' and m['trained_labels']==['normal','clog']
    assert m['ready_for_hardware_probe'] and not m['deployed'] and not m['qualified']
    for name,digest in m['artifacts_sha256'].items():
        assert Path(name).name==name and not (a.candidate/name).is_symlink()
        assert sha(a.candidate/name)==digest
    assert sha(a.library)==a.library_sha256
    a.output.mkdir(exist_ok=False)
    result=dict(status='RUNNING',trained_labels=['normal','clog'],qualified=False,control_authority='NONE',
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),kernel=os.uname().release,
        manifest_sha256=a.manifest,adapter_sha256=a.library_sha256,npu_executed=False,
        startup_selection_changed=False,deployed=False,rows=[])
    engine=None;lease=None;clean=False;failed=None
    try:
        assert read('/var/lib/cabinet/npu-lease/lease.json')['state']=='CLEAN'
        lease=NativeLease();norm=read(a.candidate/'normalization.json')
        engine=Engine(a.library,a.candidate/'model_alnpu_u8.onnx',norm)
        result['backend_audit']=engine.audit
        save(a.output/'native_metadata.json',engine.info)
        (a.output/'optimized_graph.dot').write_text(engine.graph)
        vectors=read(a.candidate/'golden.json')['vectors']
        assert len(vectors)==64 and all(sum(v['label']==l for v in vectors)==32 for l in ('normal','clog'))
        before=irq_counts()
        for v in vectors:
            _,q,clipped=prepare(v['values'],norm)
            assert not clipped and list(q)==v['input_u8']
            out,latency=engine.run(q)
            result['rows'].append(dict(label=v['label'],output_u8=out,reference_output_u8=v['output_u8'],
                execute_ms=latency,error=max(abs(x-y) for x,y in zip(out,v['output_u8']))))
        result['npu_executed']=True
        after=irq_counts();result['irq_delta']={k:after[k]-before[k] for k in before}
        result['max_probability_lsb_error']=max(r['error'] for r in result['rows'])
        result['class_agreement']=sum(max(range(5),key=r['output_u8'].__getitem__)==max(range(5),key=r['reference_output_u8'].__getitem__) for r in result['rows'])/64.
        result['execute_p99_ms']=sorted(r['execute_ms'] for r in result['rows'])[62]
        assert result['irq_delta']=={'HARD_NPU_IRQ':192,'SOFT_NPU_IRQ':0}
        assert result['max_probability_lsb_error']<=3 and result['class_agreement']>=.98
        assert result['execute_p99_ms']<128
        assert all(r['output_u8'][i]==0 for r in result['rows'] for i in (1,2,4))
        result['status']='PASS_SCOPED_CANDIDATE_HARDWARE_REPLAY'
    except BaseException as e:
        failed=e;result.update(status='FAIL',error=repr(e))
    finally:
        if engine is not None:clean=engine.close()
        elif lease is None:clean=True
        if lease is not None:lease.close(clean=clean)
        result['native_cleanup_verified']=clean
        save(a.output/'hardware_validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2),flush=True)
    if failed or not clean:raise RuntimeError(repr(failed) if failed else 'Native cleanup incomplete')


def main(a):
    if a.worker:return run_engine(a)
    assert subprocess.call(['systemctl','is-active','--quiet','cabinet-normal-npu'])==0
    env=Path('/etc/cabinet/normal-npu.env');env_hash=sha(env)
    previous=read('/run/cabinet-normal-npu/state.json')['model_sha256']
    assert not a.output.exists()
    subprocess.check_call(['systemctl','stop','cabinet-normal-npu'])
    restoration=dict(previous_model_restored=False,restored_model_sha256=previous,env_sha256=env_hash)
    try:
        # The SDK retains its driver descriptor in process-global backend
        # objects. Engine.close alone is insufficient: join the native owner
        # before starting another process, just like the production Supervisor.
        command=[sys.executable,str(Path(__file__).resolve()),'--worker']
        for key in ('candidate','manifest','library','library_sha256','output'):
            command.extend(['--'+key.replace('_','-'),str(getattr(a,key))])
        child=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             universal_newlines=True,timeout=75)
        a.output.mkdir(exist_ok=True)
        (a.output/'worker.stdout.log').write_text(child.stdout)
        (a.output/'worker.stderr.log').write_text(child.stderr)
        restoration['native_owner_exit_code']=child.returncode
    finally:
        a.output.mkdir(exist_ok=True)
        try:
            assert read('/var/lib/cabinet/npu-lease/lease.json')['state']=='CLEAN'
            assert sha(env)==env_hash
            subprocess.check_call(['systemctl','reset-failed','cabinet-normal-npu'])
            subprocess.check_call(['systemctl','start','cabinet-normal-npu'])
            start=time.monotonic();counts=set()
            while time.monotonic()-start<35:
                try:
                    current=read('/run/cabinet-normal-npu/state.json');now=time.monotonic()
                    if (current.get('valid') and current.get('model_sha256')==previous and
                            start<=current.get('updated_at',0)<=now and now-current['updated_at']<1):
                        counts.add(current['inference_count'])
                        if len(counts)>=8:break
                except (OSError,ValueError):pass
                time.sleep(.1)
            restoration.update(previous_model_restored=len(counts)>=8,restored_fresh_inferences=len(counts))
        except BaseException as error:
            restoration['error']=repr(error)
        save(a.output/'restoration.json',restoration)
    result=read(a.output/'hardware_validation.json');result.update(restoration)
    save(a.output/'hardware_validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2),flush=True)
    if child.returncode or not restoration['previous_model_restored']:
        raise RuntimeError('Replay or restoration failed; retained evidence in '+str(a.output))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--worker',action='store_true')
    for name in ('candidate','library','output'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('manifest','library-sha256'):p.add_argument('--'+name,required=True)
    main(p.parse_args())
