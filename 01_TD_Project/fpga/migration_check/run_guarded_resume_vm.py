"""Build one complete TD variant into a new directory with source/artifact hashes.
No board/SD programming. Routed timing guard runs inside check_vm.tcl before bitgen.
A failed/incomplete run cannot inherit reports or bitstreams from an older build.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,re,shutil,subprocess,sys
import run_guarded_vm as original_guard
ROOT=Path(__file__).resolve().parents[1]

def manifest(project):
    files={ROOT/(project+'.al'),Path(__file__),ROOT/'migration_check/run_guarded_vm.py',ROOT/'migration_check/resume_guarded_gate.tcl',ROOT/'migration_check/check_vm.tcl',ROOT/'migration_check/check_routed_timing.tcl'}
    for folder in ['src','design_0','al_ip']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and p.suffix.lower() in {'.v','.sv','.vh','.xml','.mem','.hex','.sdc','.adc'} and not any(x in p.parts for x in ['sim','__pycache__']):files.add(p)
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def verify_origin(origin, project, current):
    saved=json.loads((origin/'validation.json').read_text(encoding='utf-8'))
    if saved.get('project')!=project:raise RuntimeError('Checkpoint project mismatch')
    if saved.get('status')!='FAIL' or 'timed out' not in saved.get('error',''):
        raise RuntimeError('Only an archived timeout run may be resumed')
    if saved.get('sources')!=current:raise RuntimeError('Checkpoint sources differ from current project')
    console=(origin/'console.log').read_text(encoding='utf-8',errors='replace')
    if 'VM_SYNTHESIS_PASS: '+project not in console or 'VM_CHECK_FAILED:' in console:
        raise RuntimeError('Checkpoint has no successful synthesis marker')
    gate=origin/'gate.db'
    if not gate.is_file() or not gate.stat().st_size:raise RuntimeError('Checkpoint database missing/empty')
    return {'directory':origin.as_posix(), 'gate_sha256':hashlib.sha256(gate.read_bytes()).hexdigest(),
            'validation_sha256':hashlib.sha256((origin/'validation.json').read_bytes()).hexdigest(),
            'synthesis_reused':True, 'physical_validation_reused':False}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',choices=['cooling_link_test','cooling_link'],required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--td',type=Path,required=True)
    ap.add_argument('--timeout',type=int,default=43200)
    ap.add_argument('--resume-from',type=Path)
    args=ap.parse_args();out=args.output if args.output.is_absolute() else ROOT/args.output
    if out.exists():raise RuntimeError('Use a new output directory; refusing stale build artifacts: '+str(out))
    if not args.td.is_file():raise RuntimeError('TD executable does not exist')
    if args.timeout<1:raise RuntimeError('Invalid compilation timeout')
    provenance=None
    if args.resume_from:
        origin=args.resume_from if args.resume_from.is_absolute() else ROOT/args.resume_from
        provenance=verify_origin(origin,args.project,original_guard.manifest(args.project))
    out.mkdir(parents=True);report_file=out/'validation.json'
    report={'status':'RUNNING','release_qualified':False,'project':args.project,
            'started_utc':datetime.now(timezone.utc).isoformat(),
            'scope':'Full SoC compilation; optional matching synthesis checkpoint, fresh place/route/bitgen. No board or PS boot-package acceptance.',
            'tool_timeout_seconds':args.timeout}
    if provenance:report['checkpoint']=provenance
    def save():report_file.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    initial=manifest(args.project);report['sources']=initial;save()
    env=os.environ.copy();env.update(COOLING_VM_PROJECT=args.project,COOLING_VM_SYNTH='1',COOLING_VM_FULL='1',COOLING_VM_OUT=out.resolve().as_posix())
    try:
        script=ROOT/'migration_check/check_vm.tcl'
        if provenance:
            for name in ['gate.db','gate.area','gate.timing','gate.qor','gate.ts','rtl.area']:
                if (origin/name).is_file():shutil.copy2(origin/name,out/name)
            env['COOLING_VM_GATE']=(out/'gate.db').resolve().as_posix()
            script=ROOT/'migration_check/resume_guarded_gate.tcl'
        with (out/'console.log').open('w',encoding='utf-8') as log:
            result=subprocess.run([str(args.td),script.as_posix()],cwd=ROOT,
                                  stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=args.timeout)
        report['tool_exit_code']=result.returncode
        final=manifest(args.project)
        report['source_changes']=[p for p,h in initial.items() if final.get(p)!=h]
        report['new_sources']=sorted(set(final)-set(initial))
        if provenance and hashlib.sha256((out/'gate.db').read_bytes()).hexdigest()!=provenance['gate_sha256']:
            raise RuntimeError('Checkpoint database changed during physical build')
        if report['new_sources']:raise RuntimeError('New RTL/IP source appeared during build')
        if report['source_changes']:raise RuntimeError('Source changed during TD build')
        console=(out/'console.log').read_text(encoding='utf-8',errors='replace')
        if result.returncode or 'VM_CHECK_FAILED:' in console:raise RuntimeError('TD build failed; inspect console.log')
        for marker in ['VM_SYNTHESIS_PASS:','VM_PLACE_PASS:','VM_ROUTE_PASS:','VM_ROUTED_TIMING_PASS:','VM_BITGEN_PASS:','VM_CHECK_PASS:']:
            if marker not in console:raise RuntimeError('Missing completion marker '+marker)
        timing=(out/'pr.timing').read_text(encoding='utf-8',errors='replace')
        def number(pattern,body):
            m=re.search(pattern,body)
            if not m:raise RuntimeError('Missing acceptance field '+pattern)
            return float(m.group(1))
        sw=number(r'SWNS:\s*(-?[\d.]+)ns',timing);hw=number(r'HWNS:\s*(-?[\d.]+)ns',timing)
        coverage=number(r'STA coverage\s*:\s*([\d.]+)%',timing)
        period=number(r'Period Check WNS:\s*(-?[\d.]+)ns',timing)
        if 'Routed' not in timing or not re.search(r'Check Corner\s*:\s*Both',timing) or min(sw,hw,period)<0 or coverage<99.9:
            raise RuntimeError('Routed timing/coverage not qualified')
        clocks={}
        for suffix,expected in [('HP0',150),('GP0S',75),('GP1S',150),('HP1',150)]:
            m=re.search(r'\n\s*clk\d+:\s*([\d.]+)\s+(\d+)\s+[^\n]*GEN_PL_'+suffix+r'(?:\s|\n)',timing)
            if not m or int(m[2])<1 or abs(float(m[1])-expected)>.1:raise RuntimeError('Native PS clock not qualified: '+suffix)
            clocks[suffix]=float(m[1])
        area=(out/'phy.area').read_text(encoding='utf-8',errors='replace')
        resources={k:int(number(v,area)) for k,v in [('slice',r'#slice\*?\s+(\d+)'),('eram',r'#eram\s+(\d+)'),('dsp',r'#dsp\s+(\d+)')]}
        if resources['slice']>52480 or resources['eram']>280 or resources['dsp']>240:raise RuntimeError('Device resource capacity exceeded')
        bit=out/(args.project+'.bit')
        if not bit.is_file() or bit.stat().st_size==0:raise RuntimeError('Bitstream missing/empty')
        report.update(status='PASS',release_qualified=True,setup_wns_ns=sw,hold_wns_ns=hw,sta_coverage_percent=coverage,
                      period_wns_ns=period,native_ps_clock_mhz=clocks,resources=resources)
        report['artifacts']={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                             for p in [bit,out/'pr.timing',out/'phy.area',out/'console.log']}
    except Exception as e:
        report.update(status='FAIL',error=str(e));print('GUARDED_BUILD_FAILED:',e,flush=True)
    report['completed_utc']=datetime.now(timezone.utc).isoformat();save()
    print('GUARDED_BUILD_'+report['status'],flush=True)
    return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
