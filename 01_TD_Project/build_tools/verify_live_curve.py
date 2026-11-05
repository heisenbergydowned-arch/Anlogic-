"""Bounded five-second output trials using real temperature and the normal HTTP API.

Only temporary curve endpoints vary. Protection limits remain unchanged.
This is not an 80 C heating test or a physical waveform measurement.
"""
import json
from pathlib import Path
import signal
import statistics
import time
from urllib.request import Request,urlopen

def write(path,v):path.write_text(json.dumps(v,indent=2)+'\n')
def main():
    out=Path('/run/p52-curve-verification');out.mkdir()
    env=dict(l.split('=',1) for l in Path('/etc/cabinet/web.env').read_text().splitlines() if l and not l.startswith('#'))
    headers={'Authorization':'Bearer '+env['CABINET_HMI_TOKEN'].strip('\"\''),
        'X-Cabinet-Control-Token':env['CABINET_CONTROL_TOKEN'].strip('\"\''),'Content-Type':'application/json'}
    def api(suffix,body=None):
        raw=None if body is None else json.dumps(body).encode()
        with urlopen(Request('http://127.0.0.1:8766/api/commissioning/temperature-pwm-'+suffix,data=raw,headers=headers),timeout=2) as r:return json.loads(r.read())
    def fresh():
        s=api('status')
        if not s.get('feedback_valid') or s['state']!='RUNNING' or not s.get('hardware_armed'):raise RuntimeError('Real hardware not running: '+str(s))
        if s.get('target_source')!='FPGA_TPW1_READBACK':raise RuntimeError('No verified hardware target')
        return s
    start=fresh();original=start['settings'];last_revision=original['revision']
    assert original['low_C']==25 and original['high_C']==80 and original['enabled']
    assert 10<start['temperature_C']<59 and start['current_threshold_cutoff_enabled'] is False
    result=dict(status='RUNNING',boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        original=original,initial=start,trials=[],waveform_measured=False,physical_80C_heating_test=False)
    def interrupted(signum,frame):
        raise RuntimeError('Output trial interrupted by signal '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    tripped=False
    try:
        for percent in (50,100):
            current=fresh();t=current['temperature_C'];assert 10<t<59
            low,high=(t-5,t+5) if percent==50 else (t-5.5,t-.5)
            response=api('save',dict(expected_revision=last_revision,enabled=True,low_C=low,high_C=high));last_revision=response['revision']
            deadline=time.monotonic()+4
            while True:
                s=api('status')
                if s['settings']['revision']!=last_revision:raise RuntimeError('Settings changed by another operator')
                if s['state'] in ('FAULT_LATCHED','APPLY_FAILED','ARM_REJECTED'):
                    tripped=True;raise RuntimeError('Protected output trial stopped: '+str(s.get('faults')))
                if s['state']=='RUNNING' and s['applied_revision']==last_revision and abs(s['actual_pwm_percent']-percent)<=2:break
                if time.monotonic()>deadline:raise RuntimeError('Requested curve did not reach actual output')
                time.sleep(.05)
            began=time.monotonic();rows=[]
            while time.monotonic()-began<5:
                s=fresh()
                if s['settings']['revision']!=last_revision:raise RuntimeError('Settings changed by another operator')
                if abs(s['actual_pwm_percent']-percent)>2:raise RuntimeError('Actual output left requested band')
                rows.append(dict(elapsed=time.monotonic()-began,temperature_C=s['temperature_C'],rpm=s['rpm'],
                    target_percent=s['target_pwm_percent'],actual_percent=s['actual_pwm_percent'],
                    applied_revision=s['applied_revision'],observed_at=s['observed_at']))
                time.sleep(.05)
            rpms=[r['rpm'] for r in rows if r['elapsed']>=3 and r['rpm'] is not None]
            if not rpms:raise RuntimeError('No fresh FG response')
            result['trials'].append(dict(request_percent=percent,temporary_low_C=low,temporary_high_C=high,
                held_seconds=time.monotonic()-began,rows=rows,final_rpm_median=statistics.median(rpms)))
        result['fg_response_verified']=(result['trials'][1]['final_rpm_median']>result['trials'][0]['final_rpm_median']+150)
        if not result['fg_response_verified']:raise RuntimeError('PWM readback changed but measured FG response was not established')
        result['status']='PASS_REGISTER_AND_FG_RESPONSE_NO_SCOPE_MEASUREMENT'
    except BaseException as error:
        result.update(status='FAILED',error=repr(error))
    finally:
        try:
            current=api('status');tripped=tripped or current['state']=='FAULT_LATCHED'
            if current['settings']['revision']!=last_revision:raise RuntimeError('New operator settings preserved; no overwrite')
            restored=api('save',dict(expected_revision=last_revision,enabled=False if tripped else original['enabled'],
                                     low_C=original['low_C'],high_C=original['high_C']))
            result['restored_revision']=restored['revision'];result['restored_enabled']=not tripped
            limit=time.monotonic()+4
            while True:
                s=api('status')
                expected=0 if tripped else max(0,min(100,(s['temperature_C']-25)*100/55))
                if abs(s['actual_pwm_percent']-expected)<.2 and s['state'] in ('RUNNING','DISABLED') and s['applied_revision']==restored['revision']:break
                if time.monotonic()>limit:raise RuntimeError('Restore output not confirmed')
                time.sleep(.05)
            result['final']=s
        except BaseException as error:result.update(status='FAILED_RESTORE_REQUIRES_REVIEW',restore_error=repr(error))
        write(out/'verification.json',result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('initial','trials','final','original')}))
    if not result['status'].startswith('PASS_'):raise SystemExit(1)

if __name__=='__main__':main()
