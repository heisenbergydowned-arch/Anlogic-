"""Run a fresh gate or full TD build of an isolated candidate, never program hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime,timezone


def manifest(root,project):
    result={}
    for folder in ('src','design_0','al_ip'):
        for path in (root/folder).rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.v','.vh','.sv','.xml','.mem','.hex','.adc','.sdc') and 'sim' not in path.parts:
                result[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (root/(project+'.al'),root/'migration_check/check_vm.tcl',
                 root/'migration_check/check_routed_timing.tcl',root/'migration_check/hdmi_floorplan.tcl',
                 root/'migration_check/check_gate_clocks.tcl',Path(__file__).resolve()):
        result[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def blocking_warnings(console):
    return [line.strip() for line in console.splitlines()
            if 'CRITICAL-WARNING:' in line or ('WARNING:' in line and 'src/filter_v4/' in line.replace('\\','/'))]


def verify_gate(origin,root,project,current):
    saved=json.loads((origin/'validation.json').read_text(encoding='utf-8'))
    if saved.get('status')!='PASS_GATE_ONLY_NOT_ROUTED' or saved.get('project')!=project:
        raise RuntimeError('Only a passed matching gate build can be resumed')
    normalize=lambda records:{key.replace('\\','/'):value for key,value in records.items()}
    previous=normalize(saved['source_sha256']);now=normalize(current)
    changed={key for key in set(previous)|set(now) if previous.get(key)!=now.get(key)}
    if changed-{'tools/run_candidate_td.py'}:
        raise RuntimeError('Gate RTL/IP/constraints/project/Tcl differ: '+str(sorted(changed)))
    console=(origin/'console.log').read_text(encoding='utf-8',errors='replace')
    if blocking_warnings(console):raise RuntimeError('Gate critical/new-filter warnings cannot be bypassed by checkpoint reuse')
    if 'VM_CHECK_FAILED:' in console or not all(marker in console for marker in ('VM_SYNTHESIS_PASS:','VM_GATE_CLOCKS_PASS:','VM_CHECK_PASS:')):
        raise RuntimeError('Gate completion markers missing or failed')
    clock_report=origin/'gate.chk'
    if not clock_report.is_file() or hashlib.sha256(clock_report.read_bytes()).hexdigest()!=saved.get('gate_clock_report_sha256'):
        raise RuntimeError('Gate clock qualification report missing or changed')
    checkpoint=origin/'gate.db'
    if not checkpoint.is_file() or checkpoint.stat().st_size==0:
        raise RuntimeError('Gate checkpoint missing or empty')
    started=datetime.fromisoformat(saved['started_utc']).timestamp()
    completed=datetime.fromisoformat(saved['completed_utc']).timestamp()
    if not started-2<=checkpoint.stat().st_mtime<=completed+2:
        raise RuntimeError('Gate checkpoint timestamp is outside the recorded build')
    return dict(origin=str(origin),validation_sha256=hashlib.sha256((origin/'validation.json').read_bytes()).hexdigest(),
                gate_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                runner_only_changes=sorted(changed),synthesis_reused=True,physical_results_reused=False)


def physical_script(root):
    source=(root/'migration_check/check_vm.tcl').read_text(encoding='utf-8')
    matched=re.search(r'(?m)^[ \t]*set_param place opt_timing \S+[ \t]*$',source)
    if not matched:raise RuntimeError('Physical placement strategy anchor missing')
    start=matched.start()
    end=source.index('\n   }\n }\n} message options]')
    return '''set cooling_vm_root $::env(COOLING_VM_ROOT)
cd $cooling_vm_root
set cooling_vm_project $::env(COOLING_VM_PROJECT)
if {[catch {
 source [file join $cooling_vm_root migration_check check_routed_timing.tcl]
 source [file join $cooling_vm_root migration_check hdmi_floorplan.tcl]
 source [file join $cooling_vm_root migration_check check_gate_clocks.tcl]
 import_device dr1_90.db -package DR1M90GEG400 -speed 2
 import_db $::env(COOLING_VM_GATE)
 cd $::env(COOLING_VM_OUT)
 puts "VM_SYNTHESIS_REUSED: matched source-hashed gate checkpoint"
 puts "VM_SYNTHESIS_PASS: $cooling_vm_project"
 cooling_verify_gate_clock_file gate.chk
 set cooling_reset_pad [get_cells O_adc_reset_syn_4]
 if {[llength $cooling_reset_pad] != 1} {error "RESET physical PAD missing or ambiguous"}
 foreach property {LOCATION IOTYPE DRIVE SLEWRATE PULLMODE DO_DFFMODE SRMODE DO_REGSET OUTRSTMUX} expected {W9 LVCMOS33 8 FAST PULLDOWN DFF ASYNC RESET INV} {
   if {[get_property $property $cooling_reset_pad] ne $expected} {error "RESET IO-register requirement failed: $property"}
 }
 puts "VM_RESET_PACK_PASS: W9; DFF; asynchronous clear; 8mA FAST; original 8ns budget"
'''+source[start:end]+'''
} message options]} {
 puts stderr "VM_CHECK_FAILED: $message"
 exit 1
}
puts "VM_CHECK_PASS: $cooling_vm_project"
exit 0
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--project',choices=('cooling_link','cooling_link_test'),default='cooling_link')
    parser.add_argument('--td',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=14400)
    parser.add_argument('--full',action='store_true')
    parser.add_argument('--resume-gate',type=Path)
    args=parser.parse_args();root=args.root.resolve();output=args.output.resolve()
    if output.exists():raise RuntimeError('Fresh output required; refuses stale reports/bitstream')
    if args.resume_gate and not args.full:raise RuntimeError('--resume-gate requires --full')
    output.mkdir(parents=True)
    report=dict(schema='cabinet-filter-v4-candidate-td',status='RUNNING',release_qualified=False,
                project=args.project,started_utc=datetime.now(timezone.utc).isoformat(),
                phase='full' if args.full else 'gate',board_programmed=False,boot_modified=False)
    before=manifest(root,args.project)
    report['source_sha256']=before
    path=output/'validation.json'
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    try:
        origin=args.resume_gate.resolve() if args.resume_gate else None
        if origin:report['checkpoint']=verify_gate(origin,root,args.project,before)
        environment=os.environ.copy()
        environment.update(COOLING_VM_PROJECT=args.project,COOLING_VM_SYNTH='1',
                           COOLING_VM_FULL='1' if args.full else '0',COOLING_VM_OUT=output.as_posix())
        script=root/'migration_check/check_vm.tcl'
        if origin:
            for name in ('gate.db','gate.area','gate.timing','gate.ts','gate.chk','rtl.area'):
                if (origin/name).is_file():shutil.copy2(origin/name,output/name)
            script=output/'physical_from_gate.tcl';script.write_text(physical_script(root),encoding='utf-8')
            report['physical_script_sha256']=hashlib.sha256(script.read_bytes()).hexdigest()
            environment.update(COOLING_VM_ROOT=root.as_posix(),COOLING_VM_GATE=(output/'gate.db').as_posix())
            path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        with (output/'console.log').open('w',encoding='utf-8') as log:
            result=subprocess.run([str(args.td),script.as_posix()],cwd=str(root),
                                  stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                                  env=environment,timeout=args.timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        text=(output/'console.log').read_text(encoding='utf-8',errors='replace')
        report['warnings']=[line.strip() for line in text.splitlines() if 'WARNING:' in line]
        if result.returncode or 'VM_CHECK_FAILED:' in text:raise RuntimeError('TD tool failure; inspect console.log')
        blocked_warnings=blocking_warnings(text)
        if blocked_warnings:raise RuntimeError('Critical or new-filter warnings block qualification: '+str(blocked_warnings[:3]))
        if manifest(root,args.project)!=before:raise RuntimeError('RTL/IP/project/build sources changed during build')
        if origin and hashlib.sha256((output/'gate.db').read_bytes()).hexdigest()!=report['checkpoint']['gate_sha256']:
            raise RuntimeError('Gate checkpoint changed during physical build')
        for marker in ('VM_SYNTHESIS_PASS:','VM_GATE_CLOCKS_PASS:','VM_CHECK_PASS:'):
            if marker not in text:raise RuntimeError('Missing completion marker '+marker)
        report['gate_clock_report_sha256']=hashlib.sha256((output/'gate.chk').read_bytes()).hexdigest()
        area=(output/('phy.area' if args.full else 'gate.area')).read_text(encoding='utf-8',errors='replace')
        resources={}
        for name,pattern in (('slice',r'#slice\*?\s+(\d+)'),('eram',r'#eram\s+(\d+)'),('dsp',r'#dsp\s+(\d+)')):
            match=re.search(pattern,area)
            if not match:raise RuntimeError('Missing resource '+name)
            resources[name]=int(match[1])
        report['resources']=resources
        if resources['slice']>52480 or resources['eram']>280 or resources['dsp']>240:raise RuntimeError('Device resource capacity exceeded')
        if args.full:
            for marker in ('VM_HDMI_BOUND_PASS:','VM_RESET_PACK_PASS:','VM_RESET_ROUTED_PACK_PASS:',
                           'VM_PLACE_PASS:','VM_ROUTE_PASS:','VM_ROUTED_TIMING_PASS:','VM_BITGEN_PASS:'):
                if marker not in text:raise RuntimeError('Missing full completion '+marker)
            timing=(output/'pr.timing').read_text(encoding='utf-8',errors='replace')
            metrics={}
            for key,pattern in (('setup_wns_ns',r'SWNS:\s*(-?[\d.]+)ns'),
                                ('hold_wns_ns',r'HWNS:\s*(-?[\d.]+)ns'),
                                ('coverage_percent',r'STA coverage\s*:\s*([\d.]+)%')):
                match=re.search(pattern,timing)
                if not match:raise RuntimeError('Missing timing metric '+key)
                metrics[key]=float(match[1])
            if min(metrics['setup_wns_ns'],metrics['hold_wns_ns'])<0 or metrics['coverage_percent']<99.9:
                raise RuntimeError('Routed timing/coverage not qualified')
            bit=output/(args.project+'.bit')
            if not bit.is_file() or not bit.stat().st_size:raise RuntimeError('Missing new bitstream')
            report.update(metrics)
            report['bit_sha256']=hashlib.sha256(bit.read_bytes()).hexdigest()
            report['routed_timing_qualified']=True
            report['status']='PASS_ROUTED_CANDIDATE_NOT_BOARD_ACCEPTANCE'
        else:
            report['status']='PASS_GATE_ONLY_NOT_ROUTED'
    except Exception as error:
        report.update(status='FAIL',error=repr(error))
    report['completed_utc']=datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key not in ('source_sha256','warnings')},ensure_ascii=False,indent=2))
    return 0 if report['status'].startswith('PASS_') else 1


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as error:
        print('BUILD_FAIL: '+repr(error));sys.exit(1)
