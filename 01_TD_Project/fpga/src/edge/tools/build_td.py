"""Isolated TD gate/P&R build. Source hashes and failures are always recorded.

Never replaces the user's old bitstream. --end bitgen is an explicit release
build; negative timing is reported as failure even if TD produced a bit file.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[3]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=ROOT/'cooling_link.al')
    p.add_argument('--td',type=Path,default=Path('D:/TD_2026/bin/td_commands_prompt.exe'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--end',choices=['opt_gate','opt_route','bitgen'],default='opt_gate')
    p.add_argument('--timeout',type=int,default=2400)
    args=p.parse_args();dest=args.output.resolve();dest.mkdir(parents=True,exist_ok=True)
    report={'status':'RUNNING','started_utc':datetime.now(timezone.utc).isoformat(),'end_step':args.end,'project':str(args.project)}
    reportfile=dest/'validation.json'
    def save():reportfile.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        text=args.project.read_text('utf-8-sig')
        # TD .al is XML-like: legacy files contain raw ampersands and invalid
        # XML property names. Read only the exact required structural fields.
        name=re.search(r'<Name>([^<]+)</Name>',text).group(1)
        top=re.search(r'<TOP_MODULE>.*?<MODULE>([^<]+)</MODULE>',text,re.S).group(1)
        sdc=ROOT/re.search(r'<SDC_FILE>\s*<File Path="([^"]+)"',text).group(1)
        adc_match=re.search(r'<ADC_FILE>\s*<File Path="([^"]+)"',text)
        adc=ROOT/adc_match.group(1) if adc_match else None
        def absolute(m):return '<File Path="'+(ROOT/m.group(1)).resolve().as_posix()+'"'
        text=re.sub(r'<File Path="([^"]+)"',absolute,text)
        text=re.sub(r'(<Project[^>]*\bPath=")[^"]*',lambda m:m.group(1)+dest.as_posix(),text,count=1)
        (dest/(name+'.prj')).write_text(text,encoding='utf-8')
        report.update(top=top,name=name,sdc=str(sdc))
        dependencies=[args.project,sdc]+([adc] if adc else [])
        dependencies += [p for folder in [ROOT/'src',ROOT/'design_0'] for p in folder.rglob('*')
                         if p.is_file() and p.suffix.lower() in ('.v','.vh','.mem','.hex') and 'sim' not in p.parts]
        manifest=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(set(dependencies))]
        report['sources']=manifest;save()
        settings=f'''set SDCList {{"{sdc.as_posix()}"}}
set ADCList {{{('"'+adc.as_posix()+'"') if adc else ''}}}
set area_option -packarea
set device_name dr1_90.db
set end_step {args.end}
set package_name DR1M90GEG400
set prj_name {{{name}}}
set run_type syn
set speed 2
set start_step read_design
set top_model_name {{{top}}}
'''
        (dest/'settings.cfg').write_text(settings,encoding='utf-8')
        with (dest/'console.log').open('w',encoding='utf-8') as log:
            result=subprocess.run([str(args.td),(args.td.parents[1]/'scripts/DefaultFlow.tcl').as_posix()],cwd=dest,
                                  stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout)
        log=(dest/'console.log').read_text('utf-8',errors='replace')
        if result.returncode or 'ERROR:' in log or not (dest/f'.{args.end}.end.f').exists():raise RuntimeError('TD flow failed: '+str(dest/'console.log'))
        changed=[m['path'] for m in manifest if hashlib.sha256(Path(m['path']).read_bytes()).hexdigest()!=m['sha256']]
        if changed:report['changed_sources']=changed;raise RuntimeError('RTL changed during build; rerun required')
        suffix='gate' if args.end=='opt_gate' else 'pr'
        timing=(dest/f'{name}_{suffix}.timing').read_text('utf-8')
        area=(dest/(f'{name}_'+('gate' if args.end=='opt_gate' else 'phy')+'.area')).read_text('utf-8')
        def num(pattern,body):
            m=re.search(pattern,body)
            if not m:raise RuntimeError('Missing report field '+pattern)
            return float(m.group(1))
        report['setup_wns_ns']=num(r'SWNS:\s*([\d.-]+)ns',timing)
        report['sta_coverage_percent']=num(r'STA coverage\s*:\s*([\d.]+)%',timing)
        report['resources']={k:int(num(v,area)) for k,v in [('lut',r'#lut\s+(\d+)'),('register',r'#reg\s+(\d+)'),('slice_estimate',r'#slice\*?\s+(\d+)'),('eram',r'#eram\s+(\d+)'),('dsp',r'#dsp\s+(\d+)')]}
        if args.end!='opt_gate':report['hold_wns_ns']=num(r'HWNS:\s*([\d.-]+)ns',timing)
        report['status']='PASS' if report['setup_wns_ns']>=0 and report.get('hold_wns_ns',0)>=0 and report['resources']['slice_estimate']<=52480 else 'NOT_ACCEPTED'
        report['limitations']='Gate only; no routed Hold/bitstream/board acceptance.' if args.end=='opt_gate' else 'No physical-board acceptance. Review coverage, clocks and unconstrained I/O before release.'
        report['warnings']=[line.strip() for line in log.splitlines() if 'WARNING:' in line]
        report['completed_utc']=datetime.now(timezone.utc).isoformat();save()
        print(json.dumps({k:v for k,v in report.items() if k not in ('sources','warnings')},ensure_ascii=False,indent=2),flush=True)
        return 0 if report['status']=='PASS' else 1
    except Exception as e:
        report.update(status='FAIL',error=str(e),completed_utc=datetime.now(timezone.utc).isoformat())
        report['failed_stage']=[p.name for p in dest.glob('.*.error.f')]
        report['release_qualified']=False
        save();print('TD FAIL:',e,flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
