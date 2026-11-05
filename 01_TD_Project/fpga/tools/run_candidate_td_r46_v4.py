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
    for path in (root/(project+'.al'),root/'migration_check/check_vm_r46_v4.tcl',
                 root/'migration_check/check_routed_timing.tcl',root/'migration_check/hdmi_floorplan.tcl',
                 root/'migration_check/check_gate_clocks.tcl',root/'migration_check/hdmi_locations_r46_v4.tcl',Path(__file__).resolve()):
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
    source=(root/'migration_check/check_vm_r46_v4.tcl').read_text(encoding='utf-8')
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


def inspect_actual_placement(text,phase):
    lane='system/design_0_inst/design_0_uihdmi_tx_0_Inst/uihdmi_tx/u_hdmi_tx_phy_wrapper/u1_lane_lvds_10_1/'
    section=text.split('PACKING_AUDIT_'+phase+'_BEGIN\n',1)[1].split('PACKING_AUDIT_'+phase+'_END',1)[0]
    cells=[]
    for name,body in re.findall(r'PACK_CELL_BEGIN: ([^\n]+)\n(.*?)PACK_CELL_END',section,re.S):
        grid=re.search(r'Grid\s*\|\s*col=(\d+) row=(\d+)',body);offset=re.search(r'Offset\s*\|\s*(\d+)',body)
        if not grid or not offset:continue
        nets={line.split('|')[-1].strip() for line in body.splitlines() if re.search(r'\|\s*oq[ab]\s*\|',line)}
        loc=tuple(map(int,grid.groups()))+(int(offset[1]),)
        fixed=bool(re.search(r'IsFixed\s*\|\s*True',body))
        member=bool(re.search(r'HadBound\s*\|\s*True',body)) and 'cooling_hdmi_local' in body
        cells.append(dict(name=name,location=loc,output_nets=sorted(nets),fixed=fixed,bound_member=member,inside_original_bbox=102<=loc[0]<122 and 82<=loc[1]<102))
    selected={}
    for key,net in [('source','I_data_in[8]'),('target8','S_shift_data[8]'),('target6','S_shift_data[6]')]:
        found=[c for c in cells if lane+net in c['output_nets']]
        if len(found)!=1:raise RuntimeError('Missing or duplicate exact full-hierarchy output '+key)
        selected[key]=found[0]
        if not found[0]['inside_original_bbox'] or not (found[0]['fixed'] or found[0]['bound_member']):raise RuntimeError('Selected HDMI signal lacks original geometry enforcement '+key)
    if not re.search(r'Name\s*\|\s*cooling_hdmi_local\b',section) or not re.search(r'Type\s*\|\s*Hard\b',section):raise RuntimeError('Original Hard bound absent')
    if not re.search(r'BBox[^\n]*\|\s*102,\s*82,\s*122,\s*102',section):raise RuntimeError('Original bound geometry changed')
    paired=selected['target8']['name']==selected['target6']['name']
    requested=paired and selected['source']['location']==(121,98,6) and selected['target8']['location']==(121,98,1) and selected['source']['fixed'] and selected['target8']['fixed']
    return dict(status='RECORDED_ACTUAL_PLACEMENT_NOT_TIMING_QUALIFIED',phase=phase,selected=selected,hdmi_physical_cells_reported=len(cells),requested_pairing_realized=requested,same_lane_pairing_realized=paired,original_hard_bound_bbox=[102,82,122,102],explicit_fixed_membership_conversion=True,direct_lut_register_connection_claimed=False)


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
    if args.resume_gate:raise RuntimeError('R46 v4 requires new full synthesis; checkpoint reuse prohibited')
    output.mkdir(parents=True)
    report=dict(schema='cabinet-filter-v4-candidate-td',status='RUNNING',release_qualified=False,
                project=args.project,started_utc=datetime.now(timezone.utc).isoformat(),
                phase='full' if args.full else 'gate',synthesis_reused=False,board_programmed=False,boot_modified=False)
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
        script=root/'migration_check/check_vm_r46_v4.tcl'
        if origin:
            for name in ('gate.db','gate.area','gate.timing','gate.ts','gate.chk','rtl.area'):
                if (origin/name).is_file():shutil.copy2(origin/name,output/name)
            script=output/'physical_from_gate.tcl';script.write_text(physical_script(root),encoding='utf-8')
            report['physical_script_sha256']=hashlib.sha256(script.read_bytes()).hexdigest()
            environment.update(COOLING_VM_ROOT=root.as_posix(),COOLING_VM_GATE=(output/'gate.db').as_posix())
            path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        with (output/'console.log').open('w',encoding='utf-8') as log:
            result=subprocess.Popen([str(args.td),script.as_posix()],cwd=str(root),
                                  stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                                  env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            import time
            deadline=time.monotonic()+args.timeout;pairing_checked=False
            while result.poll() is None:
                progress=(output/'console.log').read_text(errors='replace')
                if 'PACKING_AUDIT_PRE_ROUTE_END' in progress and not pairing_checked:
                    pairing_checked=True
                    try:
                        proof=inspect_actual_placement(progress,'PRE_ROUTE')
                        (output/'packing_gate.json').write_text(json.dumps(proof,indent=2))
                        (output/'packing_gate.pending').write_text('Actual map recorded; awaiting explicit route strategy decision')
                    except Exception as error:
                        (output/'packing_gate.json').write_text(json.dumps(dict(status='FAIL_REQUESTED_LOCAL_PAIRING',error=repr(error)),indent=2))
                        (output/'packing_gate.fail').write_text(str(error))
                approval=output/'route_authorization.json'
                if pairing_checked and approval.exists() and not (output/'packing_gate.fail').exists() and not (output/'packing_gate.pass').exists():
                    permit=json.loads(approval.read_text())
                    if permit.get('status')!='AUTHORIZED_NATIVE_ROUTE_FOR_STRICT_TIMING' or permit.get('authorized_by')!='/root':raise RuntimeError('Explicit root native-route decision required')
                    if permit.get('placement_proof_sha256')!=hashlib.sha256((output/'packing_gate.json').read_bytes()).hexdigest() or permit.get('strategy') not in ('requested_pairing_then_strict_timing','actual_legal_layout_timing_decides'):
                        raise RuntimeError('Route authorization does not bind actual placement')
                    proof=json.loads((output/'packing_gate.json').read_text())
                    if permit['strategy']=='requested_pairing_then_strict_timing' and not proof['requested_pairing_realized']:raise RuntimeError('Authorization falsely claims requested pairing')
                    (output/'packing_gate.pass').write_text('Explicit actual-map strategy decision; final strict timing remains required')
                    report['route_authorization_sha256']=hashlib.sha256(approval.read_bytes()).hexdigest()
                if time.monotonic()>deadline:
                    result.terminate();result.wait(timeout=30);raise RuntimeError('TD timed out')
                time.sleep(1)
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
            inspect_actual_placement(text,'PRE_ROUTE');inspect_actual_placement(text,'FINAL')
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
        if 'result' in locals() and result.poll() is None:
            result.terminate();result.wait(timeout=30)
        report.update(status='FAIL',error=repr(error))
    report['completed_utc']=datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key not in ('source_sha256','warnings')},ensure_ascii=False,indent=2))
    return 0 if report['status'].startswith('PASS_') else 1


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as error:
        print('BUILD_FAIL: '+repr(error));sys.exit(1)
