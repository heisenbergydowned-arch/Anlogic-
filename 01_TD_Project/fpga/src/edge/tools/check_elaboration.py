"""Check the final full top after declaration cleanup; no placement claim."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[3]

def main():
    dest=ROOT/'src/edge/sim/top_elaboration_final';dest.mkdir(parents=True,exist_ok=True)
    project=ROOT/'src/edge/sim/td_link_final/cooling_link.prj'
    report=dict(status='RUNNING',started_utc=datetime.now(timezone.utc).isoformat(),scope='Final full-top TD elaboration; no full-chip timing or bitstream qualification')
    file=dest/'validation.json'
    def save():file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    (dest/'check.tcl').write_text(f'''import_device dr1_90.db -package DR1M90GEG400 -speed 2
open_project {{{project.as_posix()}}}
elaborate -top cooling_link_top
export_db top_elaborate.db
puts "FINAL_ELABORATION_COMPLETE"
exit
''',encoding='utf-8')
    try:
        with (dest/'console.log').open('w',encoding='utf-8') as log:
            p=subprocess.run(['D:/TD_2026/bin/td_commands_prompt.exe',(dest/'check.tcl').as_posix()],cwd=dest,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        text=(dest/'console.log').read_text('utf-8',errors='replace')
        if p.returncode or 'ERROR:' in text or 'FINAL_ELABORATION_COMPLETE' not in text:raise RuntimeError('Final top elaboration failed')
        if any('edge_gp0_' in line and 'WARNING:' in line for line in text.splitlines()):raise RuntimeError('GP0 declaration warning remains')
        report['warnings']=[line.strip() for line in text.splitlines() if 'WARNING:' in line]
        paths=[ROOT/'design_0/hdl/design_0.v',ROOT/'src/system_top.v',ROOT/'src/acq/subsys_acq.v',ROOT/'src/edge/constraints/link.sdc']
        report.update(status='PASS',completed_utc=datetime.now(timezone.utc).isoformat(),sources=[dict(path=str(x),sha256=hashlib.sha256(x.read_bytes()).hexdigest()) for x in paths]);save();print('Final full top elaboration PASS',flush=True);return 0
    except Exception as e:
        report.update(status='FAIL',error=str(e));save();print(e);return 1

if __name__=='__main__':raise SystemExit(main())
