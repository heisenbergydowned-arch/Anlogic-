"""Standalone TD gate synthesis of the feature engine via a small I/O wrapper.

No edit to the active SoC .al or constraints; no placement/routing/bitstream.
python tools/run_td_synthesis.py --td D:/TD_2026/bin/td_commands_prompt.exe --output scratch
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--td",type=Path,default=Path("D:/TD_2026/bin/td_commands_prompt.exe"))
    parser.add_argument("--output",type=Path,default=ROOT/"sim"/"td_results")
    parser.add_argument("--period-ns",type=float,default=10.)
    args=parser.parse_args()
    if args.period_ns<=0: parser.error("Period must be positive")
    executable=args.td.resolve();flow=executable.parents[1]/"scripts"/"DefaultFlow.tcl"
    if not executable.exists() or not flow.exists(): raise RuntimeError("TD executable/DefaultFlow.tcl missing")
    dest=args.output.resolve();dest.mkdir(parents=True,exist_ok=True)
    for step in ["read_design","opt_rtl","opt_gate"]:
        for suffix in ["begin","end","error"]:
            marker=dest/f".{step}.{suffix}.f"
            if marker.exists(): marker.unlink()
    sources=[*sorted(ROOT.glob("*.v")),ROOT/"sim"/"feature_synth_top.v"]
    files=[]
    for i,source in enumerate(sources):
        path=source.as_posix().replace('"','&quot;')
        files.append(f'''<File Path="{path}"><FileInfo>
<Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&R" Val="true"/>
<Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="{i+1}"/>
</FileInfo></File>''')
    # TD native project format uses the unescaped UsedInP&R attribute name.
    project='''<?xml version="1.0" encoding="UTF-8"?>
<Project Version="3" Minor="2"><Project_Created_Time></Project_Created_Time>
<TD_Encoding>UTF-8</TD_Encoding><TD_Version>6.2.2.200067</TD_Version><Name>feature_extract</Name>
<HardWare><Family>DR1</Family><Device>DR1M90GEG400</Device><Speed>-2</Speed></HardWare>
<Source_Files><Verilog>'''+"\n".join(files)+'''</Verilog></Source_Files>
<FileSets><FileSet Name="design_1" Type="DesignFiles"></FileSet>
<FileSet Name="constraint_1" Type="ConstrainFiles"></FileSet></FileSets>
<TOP_MODULE><LABEL>feature_synth_top</LABEL><MODULE>feature_synth_top</MODULE><CREATEINDEX>user</CREATEINDEX></TOP_MODULE>
<Property></Property><Device_Settings></Device_Settings><Configurations></Configurations></Project>
'''
    (dest/"feature_extract.prj").write_text(project,encoding="utf-8")
    (dest/"feature_extract.sdc").write_text(f"create_clock -name feature_clk -period {args.period_ns:.6f} [get_ports clk]\n",encoding="ascii")
    (dest/"settings.cfg").write_text('''set SDCList {"feature_extract.sdc"}
set area_option -packarea
set device_name dr1_90.db
set end_step opt_gate
set package_name DR1M90GEG400
set prj_name {feature_extract}
set run_type syn
set speed 2
set start_step read_design
set top_model_name {feature_synth_top}
''',encoding="ascii")
    with (dest/"feature_td_console.log").open("w",encoding="utf-8") as log:
        result=subprocess.run([str(executable),flow.as_posix()],cwd=dest,stdin=subprocess.DEVNULL,
                              stdout=log,stderr=subprocess.STDOUT,timeout=180)
    console=(dest/"feature_td_console.log").read_text(encoding="utf-8",errors="replace")
    if result.returncode or "ERROR:" in console or not (dest/".opt_gate.end.f").exists():
        raise RuntimeError("TD synthesis failed; inspect "+str(dest/"feature_td_console.log"))
    area=(dest/"feature_extract_gate.area").read_text(encoding="utf-8")
    timing=(dest/"feature_extract_gate.timing").read_text(encoding="utf-8")
    def number(pattern,text):
        match=re.search(pattern,text)
        if not match: raise RuntimeError("Missing report field "+pattern)
        return float(match.group(1))
    wns=number(r"SWNS:\s*([\d.-]+)ns",timing)
    report={"run_utc":datetime.now(timezone.utc).isoformat(),"device":"DR1M90GEG400 -2",
            "top":"feature_synth_top","scope":"Gate synthesis including small register/I/O wrapper; no P&R, no bitstream, no physical acceptance",
            "clock_period_ns":args.period_ns,"setup_wns_ns":wns,
            "sta_coverage_percent":number(r"STA coverage\s*:\s*([\d.]+)%",timing),
            "resources_including_wrapper":{"lut":int(number(r"#lut\s+(\d+)",area)),
                "register":int(number(r"#reg\s+(\d+)",area)),"slice_estimate":int(number(r"#slice\*\s+(\d+)",area)),
                "eram":int(number(r"#eram\s+(\d+)",area)),"dsp":int(number(r"#dsp\s+(\d+)",area))},
            "warnings":[line.strip() for line in console.splitlines() if "WARNING:" in line],
            "status":"PASS" if wns>=0 else "TIMING_NOT_MET"}
    (dest/"td_synthesis_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if wns<0: raise RuntimeError("Synthesis gate timing estimate misses target; not a timing pass")

if __name__=="__main__": main()
