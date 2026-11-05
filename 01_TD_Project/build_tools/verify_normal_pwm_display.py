"""Observe actual NPU/display publications and capture the board framebuffer."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import statistics
import struct
import time
import zlib

p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
p.add_argument('--manifest',required=True)
p.add_argument('--seconds',type=int,default=60)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)

def save(name,value):
    (a.output/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')

def screenshot(name):
    fd=os.open('/dev/fb0',os.O_RDONLY)
    try:
        raw=bytearray(160);fcntl.ioctl(fd,0x4600,raw,True);g=struct.unpack('40I',raw)
        stride=int(Path('/sys/class/graphics/fb0/stride').read_text())
        assert g[:2]==(1280,720) and g[6]==24
        pixels=os.pread(fd,stride*720,stride*g[5])
    finally:os.close(fd)
    (a.output/(name+'.bgr.z')).write_bytes(zlib.compress(pixels))
    save(name+'.geometry.json',dict(width=1280,height=720,stride=stride))

screenshot('hdmi_before')
observations=[];start=time.monotonic()
while time.monotonic()-start<a.seconds:
    now=time.monotonic()
    try:
        state=json.loads(Path('/run/cabinet-normal-npu/state.json').read_text())
        panel=dict(line.split('=',1) for line in Path('/run/cabinet-normal-npu/state.display.txt').read_text().splitlines() if '=' in line)
        now=time.monotonic()
        observations.append(dict(at=now,valid=state.get('valid') is True and
            state.get('model_sha256')==a.manifest and 0<=now-state.get('updated_at',0)<1,
            count=state.get('inference_count'),score=state.get('score'),latency_ms=state.get('execute_ms'),
            advisory=state.get('advisory',{}).get('state'),baseline_eligible=state.get('baseline_eligible'),
            pwm_percent=state.get('applied_pwm_percent'),
            panel_valid=panel.get('panel_nn_valid')=='1' and now*1000<float(panel.get('panel_nn_deadline_ms','0')),
            panel_advisory=panel.get('panel_nn_advisory_state'),panel_reason=panel.get('panel_nn_reason')))
    except Exception as error:observations.append(dict(at=now,valid=False,error=str(error)))
    time.sleep(.1)
screenshot('hdmi_after')
save('observations.json',observations)
good=[o for o in observations if o['valid']]
latencies=sorted(o['latency_ms'] for o in good)
report=dict(seconds=time.monotonic()-start,samples=len(observations),valid_samples=len(good),
    panel_valid_samples=sum(o.get('panel_valid',False) for o in observations),
    warning_samples=sum(o.get('advisory') in ('WARN','RECOVERING') for o in observations),
    normal_samples=sum(o.get('advisory')=='NORMAL' for o in observations),
    first_count=good[0]['count'] if good else None,last_count=good[-1]['count'] if good else None,
    unique_counts=len(set(o['count'] for o in good)),
    latency_p50_ms=statistics.median(latencies) if latencies else None,
    latency_p99_ms=latencies[int((len(latencies)-1)*.99)] if latencies else None,
    max_score=max(o['score'] for o in good) if good else None,
    manifest_sha256=a.manifest)
save('verification.json',report)
print(json.dumps(report),flush=True)
