"""New link RTL + independent frame reference + PS service integration tests."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];SOC=ROOT.parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--iverilog',type=Path,default=Path('C:/Users/Heisen/AppData/Local/Programs/iverilog-v14/bin/iverilog.exe'))
    ap.add_argument('--output',type=Path,default=ROOT/'sim/results')
    ap.add_argument('--verilator',type=Path)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    report={'status':'RUNNING','started_utc':datetime.now(timezone.utc).isoformat(),'tests':[]};file=out/'validation.json'
    def save():file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        sources=[*sorted((ROOT/'rtl').glob('*.v')),*sorted((SOC/'src/features').glob('*.v')),
                 *sorted((SOC/'src/control').glob('*.v')),*sorted((SOC/'src/acq').glob('*.v'))]
        sources=[p for p in sources if not p.name.startswith('cooling_link')]
        tracked=[p for folder in [ROOT/'rtl',ROOT/'linux',ROOT/'tools',SOC/'src/features',SOC/'src/control',SOC/'src/acq'] for p in folder.rglob('*')
                 if p.is_file() and p.suffix in ('.v','.py','.c','.json','.html') and '__pycache__' not in p.parts and not ('sim' in p.parts and p.suffix!='.v')]
        tracked.append(SOC/'sim/models/icm20602_model.v')
        initial_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        vvp=args.iverilog.with_name('vvp.exe' if args.iverilog.suffix else 'vvp')
        for test in ['tb_edge_cdc','tb_edge_cdc_reset','tb_edge_mailbox','tb_edge_mailbox_abort','tb_edge_router','tb_edge_window','tb_edge_float','tb_edge_rs485','tb_edge_icm','tb_edge_features_abort','tb_edge_subsys','tb_edge_features']:
            start=time.monotonic();bench=ROOT/'sim'/f'{test}.v';used=[*sources,bench]
            if test=='tb_edge_icm':used.append(SOC/'sim/models/icm20602_model.v')
            executable=out/f'{test}.vvp'
            env=os.environ.copy()
            if args.verilator and test=='tb_edge_features':
                executable=out/test
                compiler=args.verilator.resolve();prefix=compiler.parent.parent/'share/verilator'
                if prefix.is_dir():env['VERILATOR_ROOT']=str(prefix)
                command=[str(compiler),'--binary','--timing','-j','2','-Wno-fatal','--top-module',test,
                         '--Mdir',str(out/(test+'_obj')),'-o',str(executable),*map(str,used)]
            else:command=[str(args.iverilog),'-g2012','-s',test,'-o',str(executable),*map(str,used)]
            result=subprocess.run(command,capture_output=True,text=True,env=env,timeout=240)
            (out/f'{test}_compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
            if result.returncode:raise RuntimeError('Compile failed: '+test)
            # Full fixed-cycle benches stay unchanged. Serial spectrum power
            # adds simulated cycles; allow native Icarus enough wall time.
            command=[str(executable)] if args.verilator and test=='tb_edge_features' else [str(vvp),str(executable)]
            result=subprocess.run([*command,'+OUT='+str(out/'frames.hex')],capture_output=True,text=True,env=env,timeout=300)
            (out/f'{test}_run.log').write_text(result.stdout+result.stderr,encoding='utf-8')
            if result.returncode or 'ALL PASS' not in result.stdout:raise RuntimeError(test+': '+result.stdout[-1000:])
            marker=next(l for l in result.stdout.splitlines() if 'ALL PASS' in l)
            report['tests'].append(dict(test=test,status='PASS',seconds=round(time.monotonic()-start,3),marker=marker));save();print(marker,flush=True)
        # Recreate the raw synthetic waveforms independently at each 512 hop.
        import numpy as np
        sys.path.insert(0,str(SOC/'src/features/tools'));from feature_reference import extract,process_convert
        rows=[[int(x,16) for x in line.split()] for line in (out/'frames.hex').read_text().splitlines()]
        sys.path.insert(0,str(ROOT/'linux'));from cabinet.protocol import Frame,FrameGate
        for index,row in enumerate(rows):
            if len(row)!=71:raise AssertionError('Frame length')
            frame=Frame.from_words(row[:32],row[32:]);h=frame.header
            if (h[3],h[15],h[9],h[10],h[25])!=(index+1,0x5000,1023*1000,1023*1000,0):raise AssertionError('Window quality/time/sequence')
            phase=(np.arange(1024)+index*512)%40
            ax=np.where(phase<20,2048,-2048);ay=np.where((phase<10)|(phase>=30),1024,-1024);az=phase*64-1248
            raw=np.array([ax,ay,az,ax//2,ay//2,az//2])
            expected=extract(raw,process_convert(16400,16410,480,20000,clk_hz=4000000))
            actual=np.array(frame.values)
            if not np.allclose(actual,expected,atol=0.0005,rtol=0.0003):raise AssertionError('Independent full 39-feature comparison '+str(np.max(abs(actual-expected))))
            if FrameGate({'feature_config_id':1,'calibration_id':0}).check(frame,h[4],diagnostic_test=True):raise AssertionError('Diagnostic gate rejected valid complete frame')
        report['tests'].append(dict(test='three_overlapping_frames_vs_numpy',status='PASS',features_compared=len(rows)*39));save();print('Full 39D/overlap/process reference ALL PASS',flush=True)
        code='import sys,unittest;sys.path.insert(0,'+repr(str(ROOT/'linux'))+');r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('+repr(str(ROOT/'linux/tests'))+'));sys.exit(not r.wasSuccessful())'
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT/'linux',capture_output=True,text=True,timeout=90)
        (out/'python_tests.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('Linux tests: '+result.stderr[-2500:])
        report['tests'].append(dict(test='linux_policy_journal_uplink_hmi',status='PASS',output=result.stderr[-2000:]));print(result.stderr[-700:],flush=True)
        changed=[p for p,digest in initial_hashes.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest]
        if changed:raise RuntimeError('Source changed during link regression: '+str(changed))
        report.update(status='PASS',completed_utc=datetime.now(timezone.utc).isoformat(),sources=[dict(path=p,sha256=digest) for p,digest in sorted(initial_hashes.items())]);save()
    except Exception as e:
        report.update(status='FAIL',error=str(e),completed_utc=datetime.now(timezone.utc).isoformat());save();print('LINK REGRESSION FAIL:',e,flush=True);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
