#!/usr/bin/env python3
"""Validate the admitted SDK and real golden vectors before starting the formal daemon."""
import argparse,json,multiprocessing as mp,os,sys,time,signal,threading
from pathlib import Path
from v4_runtime.bundle import Bundle
from v4_runtime.server import worker
from v4_runtime.native_lease import NATIVE_LEASE_FILE
from v4_runtime.platform_gate import verify_platform_state
from commissioning.fit import sha
from normal_npu.probe import irq_counts

def main():
    p=argparse.ArgumentParser();p.add_argument('--launch',type=Path,required=True);a=p.parse_args();c=json.loads(a.launch.read_text())
    q=dict(directory=c['admission'],sha256=c['receipt_sha256'],registry=c['registry'])
    b=Bundle(c['bundle'],c['manifest_sha256'],qualification=q);b.admission.assert_current(c['library_sha256'])
    target=json.loads((Path(c['admission'])/'target.json').read_text())
    if sha(c['library'])!=c['library_sha256'] or sha(target['sdk_path'])!=target['sdk_sha256'] or target['kernel_release']!=os.uname().release:raise ValueError('Admitted native platform changed')
    verify_platform_state('/run/cabinet-live/state.json')
    if json.loads(NATIVE_LEASE_FILE.read_text())['state']!='CLEAN':raise ValueError('Native lease not clean')
    stopping=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    ctx=mp.get_context('spawn');parent,child=ctx.Pipe();process=ctx.Process(target=worker,args=(child,dict(backend='alnpu',library_bytes=Path(c['library']).read_bytes()),b))
    process.start();child.close();busy=False;success=False
    try:
        if not parent.poll(25) or parent.recv().get('ready') is not True:raise RuntimeError('Native load failed; retain unresolved owner')
        before=irq_counts();vectors=b.json('runtime_golden.json')['vectors']
        if len(vectors)<40:raise ValueError('Forty real golden vectors required')
        for row in vectors:
            if stopping.is_set():raise RuntimeError('Startup cancelled; drain native worker before exit')
            parent.send(row['input_u8']);busy=True
            if not parent.poll(1):raise RuntimeError('Native startup inference timeout')
            result=parent.recv();busy=False
            if 'error' in result:raise RuntimeError(str(result))
            expected=row['output_u8'];actual=result['output']
            if max(abs(x-y) for x,y in zip(expected,actual))>1 or max(range(5),key=expected.__getitem__)!=max(range(5),key=actual.__getitem__):raise ValueError('Native startup golden mismatch')
        after=irq_counts()
        if after['HARD_NPU_IRQ']-before['HARD_NPU_IRQ']!=len(vectors)*3 or after['SOFT_NPU_IRQ']!=before['SOFT_NPU_IRQ']:raise ValueError('Native startup execution differs')
        success=True
    finally:
        if busy and parent.poll(5):parent.recv();busy=False
        if not busy:parent.send(None)
        process.join(5)
        if process.is_alive() or process.exitcode!=0 or json.loads(NATIVE_LEASE_FILE.read_text())['state']!='CLEAN':raise RuntimeError('Native cleanup unverified; do not force kill')
    if stopping.is_set():raise RuntimeError('Startup cancelled after verified native cleanup')
    if not success:raise RuntimeError('Startup verification incomplete')
    command=[sys.executable,'-m','v4_runtime.server','--backend','alnpu','--bundle',c['bundle'],'--manifest-sha256',c['manifest_sha256'],
        '--library',c['library'],'--library-sha256',c['library_sha256'],'--socket','/run/cabinet-npu-formal/npu.sock',
        '--qualification',c['admission'],'--qualification-sha256',c['receipt_sha256'],'--release-registry',c['registry']]
    os.execv(sys.executable,command)
if __name__=='__main__':main()
