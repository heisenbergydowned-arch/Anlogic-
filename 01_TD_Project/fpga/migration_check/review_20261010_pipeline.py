"""Guest driver: qualify TEST first, then REAL, without any programming."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, json, re, subprocess, sys
root=Path(__file__).resolve().parents[1]
m=root/'migration_check'
td='C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--attempt',default='r4')
args=parser.parse_args()
assert re.fullmatch(r'r[1-9][0-9]*',args.attempt), 'Invalid attempt label'
status=m/('round4_vector_pipeline_'+args.attempt+'.json')
assert not status.exists(), 'Fresh pipeline required'
report={'status':'RUNNING','started_utc':datetime.now(timezone.utc).isoformat(),
        'test':'NOT_STARTED','real':'NOT_STARTED','board_programmed':False}
def save():status.write_text(json.dumps(report,indent=2)+'\n')
save()
try:
    for name,project in [('test','cooling_link_test'),('real','cooling_link')]:
        out='migration_check/round4_'+name+'_vector_'+args.attempt
        report[name]='RUNNING';save()
        with (m/('round4_'+name+'_driver_'+args.attempt+'.log')).open('w') as log:
            p=subprocess.run([sys.executable,str(m/'run_guarded_resume_vm.py'),'--project',project,
                              '--output',out,'--td',td,'--timeout','43200'],cwd=root,stdin=subprocess.DEVNULL,
                              stdout=log,stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        j=json.loads((root/out/'validation.json').read_text())
        report[name]=j['status'];save()
        if p.returncode or j['status']!='PASS' or not j.get('release_qualified'):
            raise RuntimeError(name+' failed guarded full build; later variants not started')
    report['status']='PASS'
except Exception as e:
    report.update(status='FAIL',error=str(e))
finally:
    report['completed_utc']=datetime.now(timezone.utc).isoformat();save()
raise SystemExit(0 if report['status']=='PASS' else 1)
