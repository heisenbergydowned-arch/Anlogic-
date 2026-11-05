import json,time,zlib,os,fcntl,struct,subprocess
from pathlib import Path
rd=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
def npu_state():
 try:return rd('/run/cabinet-normal-npu/state.json')
 except (OSError,ValueError) as e:return dict(status='NO_LIVE_STATE',valid=False,reason=repr(e))
out=Path('/run/p52-temperature-observation');out.mkdir()
deadline=time.monotonic()+15
while not Path('/run/cabinet-live/state.json').exists():
 if time.monotonic()>deadline:raise RuntimeError('Collector did not return')
 time.sleep(.2)
def snap(name):
 fd=os.open('/dev/fb0',os.O_RDONLY);raw=bytearray(160);fcntl.ioctl(fd,0x4600,raw,True);g=struct.unpack('40I',raw);stride=int(Path('/sys/class/graphics/fb0/stride').read_text());assert g[:2]==(1280,720) and g[6]==24
 data=os.pread(fd,stride*720,stride*g[5]);os.close(fd)
 (out/(name+'.bgr.z')).write_bytes(zlib.compress(data));(out/(name+'.geometry.json')).write_text(json.dumps(dict(width=1280,height=720,stride=stride)))
 for suffix,path in [('state','/run/cabinet-live/state.json'),('npu','/run/cabinet-normal-npu/state.json')]:
  try: value=rd(path)
  except Exception as e:value={'snapshot_error':repr(e)}
  (out/(name+'.'+suffix+'.json')).write_text(json.dumps(value,indent=2))
start=time.monotonic();rows=[];errors=[];snap('start');first=npu_state();snap_middle=False
with (out/'samples.jsonl').open('w') as log:
 while time.monotonic()-start<120:
  try:
   now=time.monotonic();o=rd('/run/cabinet-live/state.json')['observation'];c=o['control']['temperature_pwm'];s=o['status'];n=npu_state();temp=c.get('temperature_C');expected=None if temp is None else max(0,min(100,(temp-25)*100/55))
   row=dict(elapsed=now-start,age=now-o['received_at'],state=c['state'],enabled=c['settings']['enabled'],temperature_C=temp,expected=expected,target=c.get('target_pwm_percent'),actual=c.get('actual_pwm_percent'),rpm=c.get('rpm'),faults=c.get('faults'),current_cutoff=c.get('alarm_can_stop_pwm'),npu_valid=n.get('valid'),npu_count=n.get('inference_count'))
   if row['age']>1:errors.append('stale_collector')
   if row['state']!='RUNNING' or not row['enabled']:errors.append('not_running')
   if c.get('fault_latched'):errors.append('hardware_fault_latched')
   if row['current_cutoff'] is not False:errors.append('current_cutoff_metadata')
   rows.append(row);log.write(json.dumps(row)+'\n');log.flush()
  except Exception as e:errors.append(repr(e))
  if not snap_middle and time.monotonic()-start>60:snap('middle');snap_middle=True
  time.sleep(.2)
snap('end');last=npu_state();life=rd('/run/cabinet-fan-life/state.json');settings=rd('/etc/cabinet/temperature-pwm.json')
valid=[r for r in rows if r['expected'] is not None and r['target'] is not None and r['actual'] is not None]
if not valid:raise RuntimeError('No valid control observation samples: '+str(errors))
if any(abs(r['actual']-r['expected'])>2 for r in valid):errors.append('curve_error_above_2_percent')
result=dict(status='PASS_CONTINUOUS_TEMPERATURE_PWM_OBSERVATION' if not errors else 'FAIL',seconds=time.monotonic()-start,samples=len(rows),alarm_samples=sum(bool(x['faults']) for x in rows),observed_alarms=sorted(set(a for x in rows for a in (x['faults'] or []))),temperature_unavailable_samples=sum(x['temperature_C'] is None for x in rows),errors=sorted(set(errors)),temperature_range=[min(r['temperature_C'] for r in valid),max(r['temperature_C'] for r in valid)],actual_pwm_range=[min(r['actual'] for r in valid),max(r['actual'] for r in valid)],max_curve_error_percent=max(abs(r['actual']-r['expected']) for r in valid),npu_first_count=first.get('inference_count'),npu_last_count=last.get('inference_count'),npu_final_status=last.get('status'),npu_valid_samples=sum(1 for row in rows if row.get('npu_valid')),npu_final_reason=last.get('reason'),saved_settings=settings,life=life,display_unit=subprocess.check_output(['systemctl','show','cabinet-local-display','-p','NRestarts','-p','ActiveState']).decode())
(out/'validation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['life','saved_settings']}))
