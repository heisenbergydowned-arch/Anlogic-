from pathlib import Path
import json,subprocess,hashlib,shutil,traceback
from eco_review import parse_cell
ROOT=Path(__file__).resolve().parents[1]
parent=ROOT/'build_008';out=ROOT/'saved_route_check';out.mkdir()
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(parent/'eco_plan.json')
lines=['import_device dr1_90.db -package DR1M90GEG400 -speed 2','import_db '+(parent/'alarm_only.pr.db').as_posix()]
for name in plan['physical_changes']:
 lines+=['puts {RELOAD_CELL '+name+'}', 'report_cells [get_cells {'+name+'}] -attributes -connection -pin_loc','puts RELOAD_END']
lines+=['report_nets [get_nets {O_led4_alm_dup_3}] -connection -pin_display_limit 1000','bitgen -bit reloaded.bit','puts RELOAD_COMPLETE','exit 0']
(out/'reload.tcl').write_text('\n'.join(lines)+'\n')
r={'status':'RUNNING','source_db_sha256':sha(parent/'alarm_only.pr.db')};(out/'validation.json').write_text(json.dumps(r))
try:
 with (out/'console.log').open('w') as f:
  p=subprocess.run(['C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe',(out/'reload.tcl').as_posix()],cwd=out,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=240)
 text=(out/'console.log').read_text(errors='replace');assert p.returncode==0 and 'RELOAD_COMPLETE' in text and 'ERROR:' not in text and 'coredump' not in text
 for name,v in plan['physical_changes'].items():
  block=text.split('RELOAD_CELL '+name+'\n')[1].split('RELOAD_END')[0]
  assert json.loads(json.dumps(parse_cell(block)))==v['after'],name
 assert 'O_led_red_syn_1.doq[0]' in text and 'O_led4_alm_syn_4.doq[0]' in text
 a=(parent/'cooling_link.bit').read_bytes().split(b'\n\n',1)[1];b=(out/'reloaded.bit').read_bytes().split(b'\n\n',1)[1]
 assert a==b,'Saved database did not reproduce the accepted bitstream payload'
 r.update(status='PASS_RELOADED_DB_REPRODUCES_ALL_LOGIC_AND_BITSTREAM_PAYLOAD',bit_sha256=sha(parent/'cooling_link.bit'),reloaded_bit_sha256=sha(out/'reloaded.bit'),payload_sha256=hashlib.sha256(a).hexdigest(),payload_bytes=len(a))
except BaseException as e:r.update(status='FAIL',error=repr(e),traceback=traceback.format_exc())
(out/'validation.json').write_text(json.dumps(r,indent=2)+'\n')
m=Path('//Mac/Home/Documents/Codex/2026-11-01/kan/work/r46_alarm_only_pwm_p52_20261103/reports/saved_route_check');m.mkdir(exist_ok=True)
for p in out.iterdir():
 if p.is_file() and p.suffix!='.bit':shutil.copy2(p,m/p.name)
print(json.dumps(r))
