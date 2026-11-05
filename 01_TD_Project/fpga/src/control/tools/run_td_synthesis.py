"""Fresh TD gate synthesis in an isolated output folder. No bitstream or P&R.

--scope core estimates the complete new control and UART logic with an I/O wrapper.
--scope acq checks actual subsys_acq including sensor drivers, buttons, debug UART.
--scope soc checks the active system_top project and existing IP, without replacing
the user's existing synthesis/physical outputs. Reports are tied to source hashes.
"""
from pathlib import Path
import argparse, hashlib, json, re, subprocess
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
SOC=ROOT.parent.parent
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--td',type=Path,default=Path('D:/TD_2026/bin/td_commands_prompt.exe'))
    ap.add_argument('--output',type=Path)
    ap.add_argument('--scope',choices=['core','acq','soc'],default='core')
    ap.add_argument('--timeout',type=int,help='Process deadline seconds (core 600, full SoC 1800 by default)')
    args=ap.parse_args();dest=(args.output or ROOT/'sim'/('td_'+args.scope)).resolve();dest.mkdir(parents=True,exist_ok=True)
    (dest/'synthesis.json').write_text(json.dumps({'status':'RUNNING','scope':args.scope,'started_utc':datetime.now(timezone.utc).isoformat()})+'\n',encoding='utf-8')
    for step in ['read_design','opt_rtl','opt_gate']:
        for suffix in ['begin','end','error']:
            p=dest/f'.{step}.{suffix}.f'
            if p.exists():p.unlink()
    if args.scope in ['core','acq']:
        name='cooling_control' if args.scope=='core' else 'cooling_acq'
        top='control_synth_top' if args.scope=='core' else 'subsys_acq'
        sources=[*sorted(ROOT.glob('*.v')),ROOT.parent/'features/feature_udiv.v']
        if args.scope=='core':sources+=[ROOT.parent/'acq/pwm_out.v',ROOT/'sim/control_synth_top.v']
        else:sources+=sorted((ROOT.parent/'acq').glob('*.v'))+[ROOT.parent/'edge/rtl'/n for n in ['edge_csr_mux.v','edge_rs485.v','edge_uart_byte.v']]
        files='\n'.join(f'<File Path="{s.as_posix()}"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="{i+1}"/></FileInfo></File>' for i,s in enumerate(sources))
        project=f'''<?xml version="1.0" encoding="UTF-8"?><Project Version="3" Minor="2"><TD_Encoding>UTF-8</TD_Encoding><TD_Version>6.2.2.200067</TD_Version><Name>{name}</Name><HardWare><Family>DR1</Family><Device>DR1M90GEG400</Device><Speed>-2</Speed></HardWare><Source_Files><Verilog>{files}</Verilog></Source_Files><FileSets><FileSet Name="design_1" Type="DesignFiles"></FileSet><FileSet Name="constraint_1" Type="ConstrainFiles"></FileSet></FileSets><TOP_MODULE><LABEL>{top}</LABEL><MODULE>{top}</MODULE><CREATEINDEX>user</CREATEINDEX></TOP_MODULE><Property></Property><Device_Settings></Device_Settings><Configurations></Configurations></Project>'''
        sdc=dest/'control.sdc';port='clk' if args.scope=='core' else 'I_sysclk'
        sdc.write_text('create_clock -name control_clk -period 10.0 [get_ports '+port+']\n',encoding='ascii')
    else:
        name='soc_prj';top='system_top';sdc=SOC/'src/constraint/top_merge.sdc'
        project=(SOC/'soc_prj.al').read_text('utf-8-sig')
        def absolute(m):
            p=Path(m.group(1));p=p if p.is_absolute() else SOC/p
            return '<File Path="'+p.as_posix()+'"'
        project=re.sub(r'<File Path="([^"]+)"',absolute,project)
        project=re.sub(r'(<Project[^>]*\bPath=")[^"]*',lambda m:m.group(1)+dest.as_posix(),project,count=1)
        sources=[Path(s) for s in re.findall(r'<File Path="([^"]+)"',project)]
        sources+=[SOC/'soc_prj.al',sdc]
        # IP HDL/initialization dependencies can be referenced by generated
        # modules instead of listed in the GUI project. Include their sources.
        for folder in [SOC/'src',SOC/'design_0']:
            sources.extend(p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ['.v','.vh','.mem','.hex']
                           and 'sim' not in p.parts)
        sources=list(dict.fromkeys(sources))
    (dest/(name+'.prj')).write_text(project,encoding='utf-8')
    settings=f'''set SDCList {{"{sdc.as_posix()}"}}
set area_option -packarea
set device_name dr1_90.db
set end_step opt_gate
set package_name DR1M90GEG400
set prj_name {{{name}}}
set run_type syn
set speed 2
set start_step read_design
set top_model_name {{{top}}}
'''
    (dest/'settings.cfg').write_text(settings,encoding='utf-8')
    hashes=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources]
    (dest/'source_manifest.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (dest/'console.log').open('w',encoding='utf-8') as log:
        result=subprocess.run([str(args.td),(args.td.resolve().parents[1]/'scripts/DefaultFlow.tcl').as_posix()],cwd=dest,
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout or (1800 if args.scope=='soc' else 600))
    console=(dest/'console.log').read_text('utf-8',errors='replace')
    if result.returncode or 'ERROR:' in console or not (dest/'.opt_gate.end.f').exists():raise RuntimeError('TD synthesis failed: '+str(dest/'console.log'))
    for item in hashes:
        if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('Source changed during synthesis: '+item['path'])
    area=(dest/(name+'_gate.area')).read_text('utf-8');timing=(dest/(name+'_gate.timing')).read_text('utf-8')
    def number(pattern,text):
        m=re.search(pattern,text)
        if not m:raise RuntimeError('Report field missing: '+pattern)
        return float(m.group(1))
    wns=number(r'SWNS:\s*([\d.-]+)ns',timing)
    report={'run_utc':datetime.now(timezone.utc).isoformat(),'scope':args.scope,'top':top,'device':'DR1M90GEG400 -2',
        'status':'PASS' if wns>=0 else 'TIMING_NOT_MET','gate_setup_wns_ns':wns,
        'sta_coverage_percent':number(r'STA coverage\s*:\s*([\d.]+)%',timing),
        'resources':{k:int(number(pattern,area)) for k,pattern in [('lut',r'#lut\s+(\d+)'),('register',r'#reg\s+(\d+)'),('slice_estimate',r'#slice\*\s+(\d+)'),('eram',r'#eram\s+(\d+)'),('dsp',r'#dsp\s+(\d+)')]},
        'limitations':'Gate synthesis only. No placement/routing, routed Hold, new bitstream or physical acceptance.',
        'warnings':[s.strip() for s in console.splitlines() if 'WARNING:' in s],'sources':hashes}
    (dest/'synthesis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['sources','warnings']},ensure_ascii=False,indent=2),flush=True)
    if wns<0:raise RuntimeError('Gate timing not met; report preserved')

if __name__=='__main__':
    try:main()
    except Exception as e:print('SYNTHESIS FAIL: '+str(e),flush=True);raise SystemExit(1)
