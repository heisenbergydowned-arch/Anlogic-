"""Run the existing independent NumPy oracle with compiled full-frame simulation.
Icarus still checks math/FFT/process; Verilator accelerates the 12-frame bench.
No source, timing constraint, feature or oracle is rewritten at runtime.
"""
import argparse, hashlib, json, os, re, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
import run_regression as regression

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--iverilog',type=Path,required=True)
    ap.add_argument('--verilator',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    report={'status':'RUNNING','started_utc':datetime.now(timezone.utc).isoformat(),'scope':'RTL numerical/protocol simulation; not place/route or physical acceptance','tests':{}}
    path=out/'validation.json'
    def save():path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    sources=sorted(regression.ROOT.glob('*.v'))
    bench=regression.ROOT/'sim/tb_feature_extract.v'
    used=[*sources,bench,regression.ROOT/"sim/tb_udiv_equivalence.v",regression.ROOT/"sim/tb_feature_square64.v",Path(__file__),regression.ROOT/'tools/run_regression.py',regression.ROOT/'tools/feature_reference.py']
    report['sources']=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in used];save()
    try:
        exe=out/'tb_feature_extract';ver=args.verilator.resolve()
        env=os.environ.copy();prefix=ver.parent.parent/'share/verilator'
        if prefix.is_dir():env['VERILATOR_ROOT']=str(prefix)
        command=[str(ver),'--binary','--timing','-j','2','-Wno-fatal','--top-module','tb_feature_extract','--Mdir',str(out/'obj'),'-o',str(exe),*map(str,sources),str(bench)]
        result=subprocess.run(command,capture_output=True,text=True,env=env,timeout=120)
        log=result.stdout+result.stderr;(out/'verilator_compile.log').write_text(log)
        if result.returncode:raise RuntimeError('Verilator compilation failed')
        warnings=re.findall(r'^%Warning-([A-Z0-9_]+): (.*)$',log,re.M)
        # Audited existing deliberate fixed-point narrowing/unsigned extension.
        # Keep each diagnostic visible; any other category fails this runner.
        if any(k not in {'WIDTHTRUNC','WIDTHEXPAND'} for k,_ in warnings):raise RuntimeError('Unreviewed Verilator diagnostic category')
        report['verilator_width_diagnostics']=[{'category':k,'message':v} for k,v in warnings];save()
        original=regression.simulate
        def simulate(iv,vvp,output,selected,plus):
            if selected!='tb_feature_extract':return original(iv,vvp,output,selected,plus)
            run=subprocess.run([str(exe),*[f'+{key}={value.as_posix()}' for key,value in plus.items()]],capture_output=True,text=True,timeout=120)
            text=run.stdout+run.stderr;(out/'tb_feature_extract_run.log').write_text(text)
            if run.returncode or 'PASS feature protocol:' not in text:raise RuntimeError('Full-frame simulation failed: '+text[-1500:])
            print(text,flush=True)
        regression.simulate=simulate
        iv=args.iverilog.resolve();vvp=iv.with_name('vvp.exe' if iv.suffix=='.exe' else 'vvp')
        for helper,marker in [('tb_udiv_equivalence','DIV equivalence ALL PASS'),('tb_feature_square64','SQUARE64_TB_PASS')]:
            original(iv,vvp,out,helper,{})
            if marker not in (out/(helper+'_run.log')).read_text():raise RuntimeError('Missing helper PASS marker '+helper)
            report['tests'][helper]={'status':'PASS','vectors':3120 if helper=='tb_udiv_equivalence' else 4117};save()
        for name,check in [('math',regression.math_tests),('fft',regression.fft_tests),('process',regression.process_tests),('features',regression.feature_tests)]:
            report['tests'][name]=check(iv,vvp,out);save()
        rows=[line.split() for line in (out/'features.txt').read_text().splitlines()]
        ends=[max(int(row[5]) for row in rows if int(row[0])==c) for c in range(12)]
        spans=[ends[0],*[ends[i]-ends[i-1] for i in range(1,12)]]
        if max(spans)>12_800_000:raise AssertionError('100MHz / 128ms computation-hop budget exceeded')
        report['throughput']={'continuous_buffered_feed_and_output_stalls':True,'max_completion_spacing_cycles':max(spans),'max_spacing_ms_at_100MHz':max(spans)/100000,'hop_budget_cycles':12_800_000,'status':'PASS'}
        if any(hashlib.sha256(Path(m['path']).read_bytes()).hexdigest()!=m['sha256'] for m in report['sources']):raise RuntimeError('Source changed during numeric regression')
        report.update(status='PASS',completed_utc=datetime.now(timezone.utc).isoformat());save();print('FULL NUMERICAL REGRESSION ALL PASS',flush=True)
    except Exception as e:
        report.update(status='FAIL',error=str(e),completed_utc=datetime.now(timezone.utc).isoformat());save();print('REGRESSION FAIL:',e,flush=True);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
