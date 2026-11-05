#!/usr/bin/env python3
"""Default is MOCK. --live explicitly uses the commissioned transport config."""
import argparse
import copy
import json
import os
from pathlib import Path
import signal
import threading
import time
from cabinet.service import Service
from cabinet.model import validate_qualification
from cabinet.web import server
from cabinet.mock import MockController
from cabinet.protocol import Frame

def load_config(path):
    c=json.loads(path.read_text(encoding='utf-8-sig'))
    if c.get('schema')!='cabinet-edge-v1':raise ValueError('Configuration schema mismatch')
    if type(c.get('device_id')) is not str or not 1<=len(c['device_id'])<=80:raise ValueError('device_id required, 1..80 characters')
    for key in ('control','temperature_loop','model','contract','transport','policy','uplink'):
        if type(c.get(key)) is not dict:raise ValueError('Configuration object required: '+key)
    if type(c.get('poll_ms')) is not int or not 10<=c['poll_ms']<=1000:raise ValueError('poll_ms must be 10..1000')
    if c['model'].get('backend') not in ('disabled','mock','command','unix','tcp','onnx','npu_v4'):raise ValueError('Unknown model backend')
    for key in ('control','temperature_loop','model'):
        for flag in ('enabled','qualified'):
            if flag in c[key] and type(c[key][flag]) is not bool:raise ValueError(key+'.'+flag+' must be a boolean')
    validate_qualification(c['model'])
    # Relative deployment paths refer to the package, not the shell's cwd.
    base=Path(__file__).resolve().parent
    for obj,key in [(c,'database'),(c['transport'],'library'),(c['model'],'path'),(c['model'],'bundle'),(c['model'],'socket')]:
        value=obj.get(key)
        if value and not Path(value).is_absolute():obj[key]=str((base/value).resolve())
    paths=[]
    if c.get('fault_grade'):paths.append((c['fault_grade'],'path'))
    if c.get('journal_encryption'):paths.append((c['journal_encryption'],'key_file'))
    if c.get('parameter_control',{}).get('enabled'):paths.append((c['parameter_control'],'profile'))
    if c.get('pressure_calibration',{}).get('enabled'):paths.append((c['pressure_calibration'],'profile'))
    if c['model'].get('qualification'):
        paths.extend((c['model']['qualification'],key) for key in ('directory','registry'))
    if c['model'].get('graph_audit'):paths.append((c['model']['graph_audit'],'path'))
    if c.get('maintenance',{}).get('enabled'):
        paths.append((c['maintenance'],'bank'))
        if c['maintenance'].get('lifetime'):paths.append((c['maintenance']['lifetime'],'path'))
    for obj,key in paths:
        if obj.get(key) and not Path(obj[key]).is_absolute():obj[key]=str((base/obj[key]).resolve())
    return c

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path(__file__).with_name('config.example.json'))
    p.add_argument('--live',action='store_true');p.add_argument('--mock',action='store_true')
    p.add_argument('--database',type=Path);p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8766)
    p.add_argument('--collector',action='store_true',help='Enable event ingestion endpoint for local chain test')
    p.add_argument('--duration',type=float,help='Finite test duration in seconds')
    p.add_argument('--replay',type=Path,help='Replay checked 71-word RTL frames in MOCK mode')
    p.add_argument('--shadow-model-replay',action='store_true',help='MOCK transport only: use the pinned v4 model on explicit TEST replay frames')
    p.add_argument('--diagnostic-test',action='store_true',help='LIVE transport, compile-time TEST frames, actuator ownership disabled')
    p.add_argument('--local-display',action='store_true',help='Publish LVGL state and run web learning from the same collector')
    p.add_argument('--no-http',action='store_true',help='Do not open the optional local web server')
    p.add_argument('--display-output',type=Path,default=Path('/run/cabinet-live'))
    p.add_argument('--learning-config',type=Path,default=Path(__file__).resolve().parent/'hmi_daily/learning_config.json')
    p.add_argument('--learning-db',type=Path,default=Path(__file__).resolve().parent/'hmi_daily/data/baselines.sqlite3')
    p.add_argument('--capture-dir',type=Path,help='Enable bounded read-only session recording')
    p.add_argument('--capture-contract',type=Path,help='Reviewed v4 feature contract; calibration zero is diagnostic-only')
    args=p.parse_args()
    if args.live and args.mock:p.error('Choose mock or live')
    if args.diagnostic_test and not args.live:p.error('--diagnostic-test requires --live')
    if bool(args.capture_dir)!=bool(args.capture_contract):p.error('--capture-dir and --capture-contract are required together')
    if args.capture_dir and not args.local_display:p.error('Capture HDMI requires --local-display')
    c=load_config(args.config)
    if args.shadow_model_replay and (args.live or not args.replay or c['model']['backend']!='npu_v4' or c['model'].get('qualified') is not False or c['model'].get('evidence') is not None):
        p.error('--shadow-model-replay requires MOCK, --replay and an unqualified v4 model')
    if args.database:c['database']=str(args.database.resolve())
    if not args.live:
        if not args.shadow_model_replay:
            c['model']['backend']='mock';c['model']['qualified']=False;c['model']['model_id']='mock-five-class-v1'
        c['control']['enabled']=False;c['temperature_loop']['enabled']=False
    if args.diagnostic_test:
        c['diagnostic_test']=True;c['control']['enabled']=False;c['temperature_loop']['enabled']=False
        c['model']['qualified']=False
        if c['model']['backend']=='disabled':c['model']['backend']='mock';c['model']['model_id']='mock-five-class-v1'
    Path(c['database']).parent.mkdir(parents=True,exist_ok=True)
    controller=None
    if args.replay:
        if args.live:p.error('--replay is MOCK only')
        rows=[[int(x,16) for x in line.split()] for line in args.replay.read_text().splitlines()]
        controller=MockController([Frame.from_words(r[:32],r[32:]) for r in rows])
    observer=None
    recorder=None
    if args.capture_dir:
        from cabinet.capture import CaptureRecorder
        recorder=CaptureRecorder(c,args.capture_dir,args.display_output/'capture.sock',
                                 json.loads(args.capture_contract.read_text(encoding='utf-8')))
    if args.local_display:
        from cabinet.local_display import LocalDisplay
        observer=LocalDisplay(c,args.display_output,args.learning_config,args.learning_db,recorder=recorder)
    service=Service(c,mock=not args.live,controller=controller,observer=observer,recorder=recorder)
    http=None if args.no_http else server(args.host,args.port,service,collector=args.collector,token=os.environ.get('CABINET_HMI_TOKEN'),control_token=os.environ.get('CABINET_CONTROL_TOKEN'))
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    worker=None
    if http is not None:
        worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:
        service.start()
        print('Cabinet %s: %s' % ('LIVE' if args.live else 'MOCK TEST',
                                'local display / no HTTP listener' if http is None else 'http://%s:%d' % (args.host,http.server_address[1])),flush=True)
        begin=time.monotonic()
        while not stop.wait(0.2):
            if args.duration is not None and time.monotonic()-begin>=args.duration:break
    finally:
        if http is not None:
            http.shutdown();http.server_close();worker.join(timeout=2)
        service.close()

if __name__=='__main__':main()
