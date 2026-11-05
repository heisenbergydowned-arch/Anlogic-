"""FCB1 control RTL regression; generated files stay in --output.

Failures, missing PASS markers, compilation failures and timeouts are nonzero.
This is RTL evidence, not integrated place/route or physical fan acceptance.
"""
from pathlib import Path
import argparse, hashlib, json, random, shutil, subprocess, time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT/'sim/results')
    ap.add_argument('--iverilog', type=Path)
    ap.add_argument('--timeout', type=int, default=60)
    args = ap.parse_args()
    fallback = Path.home()/'AppData/Local/Programs/iverilog-v14/bin/iverilog.exe'
    iv = args.iverilog or shutil.which('iverilog') or fallback
    iv = Path(iv).resolve(); vv = iv.with_name('vvp.exe' if iv.suffix=='.exe' else 'vvp')
    if not iv.exists() or not vv.exists(): raise RuntimeError('Icarus Verilog/vvp missing')
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    # A failed or unfinished rerun must never expose the previous PASS result.
    report_path=out/'validation.json'
    report_path.write_text(json.dumps({'status':'RUNNING','started_utc':datetime.now(timezone.utc).isoformat()})+'\n',encoding='utf-8')
    sources = [*sorted(ROOT.glob('*.v')), ROOT.parent/'features/feature_udiv.v',
               ROOT.parent/'acq/pwm_out.v', ROOT.parent/'acq/dbg_uart.v', ROOT.parent/'edge/rtl/edge_csr_mux.v',
               ROOT.parent/'edge/rtl/edge_rs485.v', ROOT.parent/'edge/rtl/edge_uart_byte.v',
               ROOT.parent/'edge/rtl/edge_environment.v']
    records=[];used_sources={}
    def remember(paths):
        for p in paths:
            used_sources[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    remember([Path(__file__).resolve(),ROOT/'tools/control_cli.py',ROOT/'config_unqualified.template.json'])
    def simulate(name, extra=(), plus=()):
        exe=out/(name+'.vvp'); src=list(dict.fromkeys([*sources,*extra]))
        bench=ROOT/'sim'/(name+'.v')
        if not bench.exists(): bench=ROOT.parent.parent/'sim'/(name+'.v')
        remember([*src,bench])
        compile_cmd=[str(iv),'-g2012','-Wall','-s',name,'-o',str(exe),*[str(s) for s in src],str(bench)]
        t=time.monotonic()
        p=subprocess.run(compile_cmd,capture_output=True,text=True,timeout=args.timeout)
        (out/(name+'_compile.log')).write_text(p.stdout+p.stderr,encoding='utf-8')
        if p.returncode: raise RuntimeError(name+' compilation failed')
        p=subprocess.run([str(vv),str(exe),*plus],capture_output=True,text=True,timeout=args.timeout)
        (out/(name+'_run.log')).write_text(p.stdout+p.stderr,encoding='utf-8')
        if p.returncode or 'ALL PASS' not in p.stdout or 'FAIL' in p.stdout or 'TIMEOUT' in p.stdout:
            raise RuntimeError(name+' failed; '+p.stdout[-1500:])
        marker=next(line for line in p.stdout.splitlines() if 'ALL PASS' in line)
        print(marker,flush=True);records.append({'test':name,'status':'PASS','seconds':round(time.monotonic()-t,3),'marker':marker})
    for name in ['tb_control_edges','tb_control_axi','tb_control_uart','tb_control_unqualified','tb_cooling_control']:
        simulate(name)
    # Independent integer arithmetic reference: exact 60*Fs/(period*PPR).
    rng=random.Random(20602)
    cases=[(0,2,128,100000000),(127,2,128,100000000),(128,0,128,100000000),
           (500000,2,128,100000000),(1000000,1,128,100000000),(600000000,8,128,1000000000)]
    cases += [(rng.randrange(128,200000000),rng.randrange(1,9),128,200000000) for _ in range(74)]
    input_path=out/'rpm_input.hex'; result_path=out/'rpm_output.txt'
    input_path.write_text(''.join(f'{p:08x} {pp:02x} {lo:08x} {hi:08x}\n' for p,pp,lo,hi in cases),encoding='ascii')
    simulate('tb_rpm_vectors',plus=[f'+IN={input_path.as_posix()}',f'+OUT={result_path.as_posix()}'])
    result=[tuple(map(int,line.split())) for line in result_path.read_text().splitlines()]
    if len(result)!=len(cases):raise AssertionError('RPM vector count')
    old_rpm=0
    for j,((p,pp,lo,hi),(idx,rpm,valid,fresh)) in enumerate(zip(cases,result)):
        q=6_000_000_000//(p*pp) if pp and lo<=p<=hi else 0
        ok=int(1<=q<=65535)
        if ok:old_rpm=q
        if (idx,rpm,valid,fresh)!=(j,old_rpm,ok,ok):raise AssertionError(f'RPM vector {j}: {(idx,rpm,valid,fresh)}')
    # Reference PI equations in arbitrary-precision Python: conditional integral,
    # applied-output tracking, Q8 units, clipping and no repeated-old integration.
    vectors=[];expected=[];integral=0;primed=False;previous_enable=False;duty=0;saturated=0
    def vector(en,nf,target,rpm,applied,lo,hi,kp,ki):
        nonlocal integral,primed,previous_enable,duty,saturated
        vectors.append((en,nf,target,rpm,applied,lo,hi,kp,ki))
        if not en:
            duty=applied;integral=0;primed=False;saturated=0;previous_enable=False
        else:
            if not previous_enable:duty=applied
            if nf:
                err=target-rpm;p=err*kp
                if not primed:
                    integral=(applied<<8)-p;duty=max(lo,min(hi,applied));saturated=0;primed=True
                else:
                    attempt=integral+err*ki;u=p+attempt
                    if (u>hi*256 and err>0) or (u<lo*256 and err<0):u=p+integral
                    else:integral=attempt
                    saturated=int(u<lo*256 or u>hi*256)
                    duty=max(lo,min(hi,u//256))
            previous_enable=True
        expected.append((len(expected),duty,saturated))
    for block in range(12):
        lo,hi=500,4000;seed=rng.randrange(lo,hi+1);kp=rng.choice([1,32,128,256,1024,32767]);ki=rng.choice([0,1,8,64,1024,32767])
        vector(0,0,0,0,seed,lo,hi,kp,ki)
        for _ in range(40):
            t=rng.choice([500,6000,7000,65535,rng.randrange(500,7000)])
            r=rng.choice([0,500,6000,65535,rng.randrange(500,7000)])
            vector(1,int(rng.random()>.2),t,r,seed,lo,hi,kp,ki)
    pin=out/'pi_input.txt';pout=out/'pi_output.txt'
    pin.write_text(''.join(' '.join(map(str,v))+'\n' for v in vectors),encoding='ascii')
    simulate('tb_pi_vectors',plus=[f'+IN={pin.as_posix()}',f'+OUT={pout.as_posix()}'])
    actual=[tuple(map(int,line.split())) for line in pout.read_text().splitlines()]
    if len(actual)!=len(expected):raise AssertionError('PI vector count')
    for j,(a,e) in enumerate(zip(actual,expected)):
        if a!=e:raise AssertionError(f'PI vector {j}: RTL={a}, ref={e}, inputs={vectors[j]}')
    # Changed legacy drivers still honor their default interfaces.
    simulate('tb_pwm_out');simulate('tb_pwm20k');simulate('tb_dbg_uart')
    if (ROOT/'sim/tb_subsys_control.v').exists():
        simulate('tb_subsys_control',extra=sorted((ROOT.parent/'acq').glob('*.v')))
    p=subprocess.run([__import__('sys').executable,str(ROOT/'tools/control_cli.py'),'selftest'],capture_output=True,text=True,timeout=args.timeout)
    (out/'control_cli_run.log').write_text(p.stdout+p.stderr,encoding='utf-8')
    if p.returncode or 'ALL PASS' not in p.stdout:raise RuntimeError('Control client selftest failed')
    print(p.stdout.strip(),flush=True);records.append({'test':'control_cli','status':'PASS','marker':p.stdout.strip()})
    for path,digest in used_sources.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise RuntimeError('Source changed during regression: '+path)
    report={'run_utc':datetime.now(timezone.utc).isoformat(),'status':'PASS',
            'scope':'Control RTL and native-unit/reference arithmetic; no board, bitstream or routed timing acceptance',
            'tests':records,'rpm_reference_vectors':len(cases),'pi_reference_vectors':len(vectors),
            'sources':[{'path':path,'sha256':digest} for path,digest in sorted(used_sources.items())]}
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('REGRESSION PASS: '+str(out/'validation.json'),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('REGRESSION FAIL: '+str(e),flush=True);raise SystemExit(1)
