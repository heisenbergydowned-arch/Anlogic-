"""Real-output alarm test and three-second monitor outage; no fake sensor values."""
import json,time,subprocess,sys,os,zlib,fcntl,struct
from pathlib import Path
from urllib.request import Request,urlopen
os.chdir('/opt/cabinet/linux')
sys.path.insert(0,'/opt/cabinet/linux')
from cabinet.io import open_controller
out=Path('/run/p52-alarm-verification');out.mkdir()
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
assert initial['alarm_can_stop_pwm'] is False and 10<initial['temperature_C']<59
result=dict(status='RUNNING',boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),original=original,alarm_rows=[],outage_rows=[],waveform_measured=False,audible_sound_recorded=False)
stopped=False;controller=None
try:
 t=initial['temperature_C'];r=save(original,t-5,t+5);revision=r['revision'];wait_running(revision);time.sleep(2)
 assert status()['actual_pwm_percent']>10
 api('alarm-test',{'duration_s':5});started=time.monotonic();shot=False
 while time.monotonic()-started<5.5:
  s=status();o=read('/run/cabinet-live/state.json')['observation'];st=o['status'];age=time.monotonic()-o['received_at']
  row=dict(elapsed=time.monotonic()-started,pwm=s['actual_pwm_percent'],target=s['target_pwm_percent'],temperature_C=s['temperature_C'],state=s['state'],alarms=s.get('alarm_causes'),buzzer_requested=s.get('buzzer_requested'),hardware_alarm_level=st['alarm_level'],soft_word=st['raw_words'][31],feedback_age=age,rpm=s.get('rpm'))
  assert s['state']=='RUNNING' and s['hardware_armed'] and s['actual_pwm_percent']>10 and age<1,row
  if s['temperature_C'] is not None:
   expected=max(0,min(100,(s['temperature_C']-r['settings']['low_C'])*100/(r['settings']['high_C']-r['settings']['low_C'])))
   assert abs(s['actual_pwm_percent']-expected)<2,row
  result['alarm_rows'].append(row)
  if not shot and time.monotonic()-started>1:snap('alarm');shot=True
  time.sleep(.1)
 audible=[x for x in result['alarm_rows'] if x['buzzer_requested'] and x['hardware_alarm_level']>=2 and x['soft_word']>>16==0x52 and x['soft_word']&4]
 assert len(audible)>=20, 'No sustained physical-alarm request readback'
 result['alarm_with_nonzero_pwm_samples']=len(audible)
 # NPU stays running; a temporary input gap must not require stopping the fan to restart its selftest.
 subprocess.check_call(['systemctl','stop','cabinet-edge']);stopped=True
 cfg=read('/etc/cabinet/edge.json');controller=open_controller(cfg);started=time.monotonic()
 while time.monotonic()-started<3:
  flags=controller.io.read(0x0a08);pair=controller.io.read(0x0a28)
  row=dict(elapsed=time.monotonic()-started,flags=flags,target=pair>>16,duty=pair&65535)
  assert flags&1 and not flags&2 and 400<row['duty']<=4000,row
  result['outage_rows'].append(row);time.sleep(.05)
 controller.close();controller=None
 subprocess.check_call(['systemctl','start','cabinet-edge','cabinet-commissioning-manager','cabinet-fan-life','cabinet-local-display']);stopped=False
 resumed=wait_running(revision,25);assert resumed['actual_pwm_percent']>10
 result['status']='PASS_ALARM_AND_MONITOR_OUTAGE_DO_NOT_CUT_PWM'
except BaseException as e:result.update(status='FAILED',error=repr(e))
finally:
 if controller is not None:controller.close()
 if stopped:subprocess.run(['systemctl','start','cabinet-edge','cabinet-commissioning-manager','cabinet-fan-life','cabinet-local-display'])
 try:
  s=wait_running(revision,25)
  assert s['settings']['revision']==revision, 'Another operator changed settings; preserve them'
  restored=save(s['settings'],original['low_C'],original['high_C']);result['restored']=wait_running(restored['revision'])
  assert result['restored']['settings']['enabled']
  snap('restored')
  subprocess.run(['systemctl','start','--no-block','cabinet-normal-npu'])
 except BaseException as e:result.update(status='FAILED_RESTORE_REQUIRES_REVIEW',restore_error=repr(e))
 write('verification.json',result)
 print(json.dumps({k:v for k,v in result.items() if k not in ('alarm_rows','outage_rows','original','restored')}))
if not result['status'].startswith('PASS'):raise SystemExit(1)
