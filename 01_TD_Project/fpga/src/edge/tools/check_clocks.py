"""Recheck corrected SDC against the existing gate netlist; never claim P&R."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[3]

def main():
    dest=ROOT/'src/edge/sim/clock_recheck';dest.mkdir(parents=True,exist_ok=True)
    db=ROOT/'src/edge/sim/td_link_final/cooling_link_gate.db';sdc=ROOT/'src/edge/constraints/link.sdc'
    report=dict(status='RUNNING',started_utc=datetime.now(timezone.utc).isoformat(),scope='Corrected constraints on existing gate netlist; no resynthesis or routed Hold',
                netlist_sha256=hashlib.sha256(db.read_bytes()).hexdigest(),sdc_sha256=hashlib.sha256(sdc.read_bytes()).hexdigest())
    file=dest/'validation.json'
    def save():file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    script=f'''import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db {{{db.as_posix()}}}
clear_sdc -user
read_sdc {{{sdc.as_posix()}}}
update_timing
report_timing_summary -file corrected_gate.timing
report_timing_exception -file exceptions.timing
check_timing -verbose -file check.timing
puts "CLOCK_RECHECK_COMPLETE"
exit
'''
    (dest/'check.tcl').write_text(script,encoding='utf-8')
    try:
        with (dest/'console.log').open('w',encoding='utf-8') as log:
            p=subprocess.run(['D:/TD_2026/bin/td_commands_prompt.exe',(dest/'check.tcl').as_posix()],cwd=dest,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        text=(dest/'console.log').read_text('utf-8',errors='replace')
        if p.returncode or 'CLOCK_RECHECK_COMPLETE' not in text or 'ERROR:' in text:raise RuntimeError('Clock recheck failed')
        timing=(dest/'corrected_gate.timing').read_text('utf-8')
        report['setup_wns_ns']=float(re.search(r'SWNS:\s*([\d.-]+)ns',timing)[1])
        report['empty_group_fixed']='Clock group is empty' not in text and 'Command set_clock_groups' not in text
        report['warnings']=[line for line in text.splitlines() if 'WARNING:' in line]
        report['ps_native_clock_unresolved']=any('clock pin(s) GEN_PL' in line for line in report['warnings'])
        report['status']='NOT_ACCEPTED' # Full variant failed placement; no routed evidence.
        report['completed_utc']=datetime.now(timezone.utc).isoformat();save();print(json.dumps({k:v for k,v in report.items() if k!='warnings'},indent=2));return 0 if report['empty_group_fixed'] else 1
    except Exception as e:
        report.update(status='FAIL',error=str(e));save();print(e);return 1

if __name__=='__main__':raise SystemExit(main())
