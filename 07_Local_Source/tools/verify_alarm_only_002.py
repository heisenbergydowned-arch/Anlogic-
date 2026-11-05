"""Real-output alarm test and three-second monitor outage; no fake sensor values."""
import json,time,subprocess,sys,os,zlib,fcntl,struct,signal
from pathlib import Path
from urllib.request import Request,urlopen
os.chdir('/opt/cabinet/linux')
sys.path.insert(0,'/opt/cabinet/linux')
from cabinet.io import open_controller
out=Path('/run/p52-alarm-verification-002');out.mkdir()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
write=lambda n,v:(out/n).write_text(json.dumps(v,indent=2)+'\n')
env=dict(l.split('=',1) for l in Path('/etc/cabinet/web.env').read_text().splitlines() if l and not l.startswith('#'))
headers={'Authorization':'Bearer '+env['CABINET_HMI_TOKEN'].strip('\"\''),'X-Cabinet-Control-Token':env['CABINET_CONTROL_TOKEN'].strip('\"\''),'Content-Type':'application/json'}
def api(name,body=None):
 with urlopen(Request('http://127.0.0.1:8766/api/commissioning/'+name,headers=headers,data=None if body is None else json.dumps(body).encode()),timeout=3) as r:return json.load(r)
def status():return api('temperature-pwm-status')
def save(s,low,high):return api('temperature-pwm-save',dict(expected_revision=s['revision'],enabled=True,low_C=low,high_C=high))
def wait_running(revision,seconds=15):
 deadline=time.monotonic()+seconds
 while True:
  try:
   s=status()
   if s['state']=='RUNNING' and s['applied_revision']==revision and s['feedback_valid']:return s
  except (OSError,ValueError):pass
  if time.monotonic()>deadline:raise RuntimeError('Temperature output did not resume')
  time.sleep(.1)
def snap(name):
 fd=os.open('/dev/fb0',os.O_RDONLY);raw=bytearray(160);fcntl.ioctl(fd,0x4600,raw,True);g=struct.unpack('40I',raw);stride=int(Path('/sys/class/graphics/fb0/stride').read_text());assert g[:2]==(1280,720) and g[6]==24
 data=os.pread(fd,stride*720,stride*g[5]);os.close(fd);(out/(name+'.bgr.z')).write_bytes(zlib.compress(data));write(name+'.geometry.json',dict(width=1280,height=720,stride=stride))
 write(name+'.state.json',read('/run/cabinet-live/state.json'))
initial=status();original=initial['settings'];revision=original['revision']
assert original['enabled'] and original['low_C']==25 and original['high_C']==80
assert initial['alarm_can_stop_pwm'] is False and initial['feedback_valid']
result=dict(status='RUNNING',boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),original=original,alarm_rows=[],outage_rows=[],waveform_measured=False,audible_sound_recorded=False)
stopped=False;controller=None;curve_changed=False;paused_pid=None
try:
 r={'settings':original}
 if initial['actual_pwm_percent']<=10:
  t=initial['temperature_C'];assert 10<t<59
  r=save(original,t-5,t+5);revision=r['revision'];curve_changed=True
  wait_running(revision);time.sleep(2)
 result['temporary_curve_used']=curve_changed
 assert status()['actual_pwm_percent']>10
 api('alarm-test',{'duration_s':5});started=time.monotonic();shot=False
 while time.monotonic()-started<5.5:
  s=status();o=read('/run/cabinet-live/state.json')['observation'];st=o['status'];age=time.monotonic()-o['received_at']
  row=dict(elapsed=time.monotonic()-started,pwm=s['actual_pwm_percent'],target=s['target_pwm_percent'],temperature_C=s['temperature_C'],state=s['state'],alarms=s.get('alarm_causes'),buzzer_requested=s.get('buzzer_requested'),hardware_alarm_level=st['alarm_level'],soft_word=st['raw_words'][31],feedback_age=age,rpm=s.get('rpm'))
  if not s.get('feedback_valid') or s['state']=='STALE_FEEDBACK':
   result.setdefault('unavailable_api_samples',[]).append(row);time.sleep(.1);continue
  assert s['state']=='RUNNING' and s['hardware_armed'] and s['actual_pwm_percent']>0,row
  if s['temperature_C'] is not None:
   expected=max(0,min(100,(s['temperature_C']-r['settings']['low_C'])*100/(r['settings']['high_C']-r['settings']['low_C'])))
   assert abs(s['actual_pwm_percent']-expected)<2,row
  result['alarm_rows'].append(row)
  if not shot and time.monotonic()-started>1:snap('alarm');shot=True
  time.sleep(.1)
 audible=[x for x in result['alarm_rows'] if x['feedback_age']<1 and x['buzzer_requested'] and x['hardware_alarm_level']>=2 and x['soft_word']>>16==0x52 and x['soft_word']&4]
 assert len(audible)>=6 and audible[-1]['elapsed']-audible[0]['elapsed']>=2, 'No sustained physical-alarm request readback'
 result['alarm_with_nonzero_pwm_samples']=len(audible)
 # NPU stays running; a temporary input gap must not require stopping the fan to restart its selftest.
 paused_pid=int(subprocess.check_output(['systemctl','show','cabinet-edge','-p','MainPID','--value']));assert paused_pid>1
 os.kill(paused_pid,signal.SIGSTOP);stopped=True;started=time.monotonic()
 capture=subprocess.run(['/run/tpw_readonly'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
 result['outage_rows']=[json.loads(line) for line in capture.stdout.splitlines() if line.strip()]
 assert capture.returncode==0 and len(result['outage_rows'])>=60, (capture.returncode,capture.stderr,result['outage_rows'][-1:])
 assert result['outage_rows'][-1]['elapsed']>=3
 os.kill(paused_pid,signal.SIGCONT);stopped=False
 result['monitor_pause_method']='SIGSTOP/SIGCONT with independent volatile read-only MMIO samples'
 resumed=wait_running(revision,25);assert resumed['actual_pwm_percent']>10
 result['status']='PASS_ALARM_AND_MONITOR_OUTAGE_DO_NOT_CUT_PWM'
except BaseException as e:result.update(status='FAILED',error=repr(e))
finally:
 if controller is not None:controller.close()
 if stopped:os.kill(paused_pid,signal.SIGCONT)
 try:
  s=wait_running(revision,25)
  assert s['settings']['revision']==revision, 'Another operator changed settings; preserve them'
  if curve_changed:
   restored=save(s['settings'],original['low_C'],original['high_C']);result['restored']=wait_running(restored['revision'])
  else:result['restored']=s
  assert result['restored']['settings']['enabled']
  snap('restored')
  subprocess.run(['systemctl','start','--no-block','cabinet-normal-npu'])
 except BaseException as e:result.update(status='FAILED_RESTORE_REQUIRES_REVIEW',restore_error=repr(e))
 write('verification.json',result)
 print(json.dumps({k:v for k,v in result.items() if k not in ('alarm_rows','outage_rows','original','restored')}))
if not result['status'].startswith('PASS'):raise SystemExit(1)
