#!/usr/bin/env python3
"""Explicit commissioning tool; no device is opened without --live.

Stop cabinet-edge before using this tool: there is one command/config owner.
Configuration is committed only with the FPGA's local maintenance permission.
Use UART for configuration error recovery; an MMIO SLVERR can become SIGBUS.
"""
import argparse
import json
from pathlib import Path
import time
from run_edge import load_config
from cabinet.io import open_controller,FCB1

def pack_feature(c):
    if c.get('schema')!='EDG1-config-v1':raise ValueError('Feature configuration schema')
    if type(c.get('qualified')) is not bool:raise ValueError('qualified must be a boolean')
    if c.get('qualified') and (c.get('qualified') is not True or not c.get('evidence')):raise ValueError('Calibration evidence required')
    fields=['feature_config_id','calibration_id','current_zero_q16','pressure_zero_q16','current_gain_q30','pressure_gain_q30','ppr']
    if any(type(c.get(k)) is not int for k in fields):raise ValueError('Integer feature/calibration words required')
    if not 0<c['feature_config_id']<=0xffffffff or not 0<=c['calibration_id']<=0xffffffff:raise ValueError('Configuration ID range')
    if c.get('qualified') and c['calibration_id']==0:raise ValueError('Qualified calibration ID must be nonzero')
    if not 1<=c['ppr']<=8:raise ValueError('PPR range')
    for key in fields[2:6]:
        if not -0x80000000<=c[key]<=0x7fffffff:raise ValueError('Signed coefficient range: '+key)
    if not c['current_gain_q30'] or not c['pressure_gain_q30']:raise ValueError('Zero gain')
    edges=c['edges']
    if len(edges)!=9 or any(type(e) is not int for e in edges) or edges[0]!=1 or edges[-1]!=513 or any(a>=b for a,b in zip(edges,edges[1:])):
        raise ValueError('Nine strictly increasing edges from 1 to 513 required')
    return [c['feature_config_id'],c['calibration_id'],int(bool(c.get('qualified'))),*[c[k]&0xffffffff for k in fields[2:6]],c['ppr'],*edges]

def commit_feature(controller,words,timeout=3):
    if controller.io.read(0x1020)==words[0]:raise ValueError('Use a NEW feature configuration ID for each changed contract')
    for i,word in enumerate(words):controller.io.write(0x1300+4*i,word)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if not controller.io.read(0x1008)&0x18:
            try:controller.io.write(0x1040,0x45434d54)
            except RuntimeError as e:
                if '5 ' not in str(e):raise
                continue # busy raced an idle check; old active configuration stays intact
            if (controller.io.read(0x1020),controller.io.read(0x1024))!=(words[0],words[1]):raise RuntimeError('Commit readback mismatch')
            return
        time.sleep(.005)
    raise TimeoutError('Feature engine did not provide an idle commit interval')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path(__file__).with_name('config.example.json'));p.add_argument('--live',action='store_true')
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('status');sub.add_parser('frame')
    f=sub.add_parser('feature-config');f.add_argument('file',type=Path)
    f=sub.add_parser('control-config');f.add_argument('file',type=Path)
    f=sub.add_parser('command');f.add_argument('opcode',type=int,choices=range(1,9));f.add_argument('payload',type=lambda s:int(s,0),default=0,nargs='?')
    args=p.parse_args();c=load_config(args.config);words=None
    if args.action=='feature-config':words=pack_feature(json.loads(args.file.read_text('utf-8-sig')))
    elif args.action=='control-config':words=FCB1.pack_config(json.loads(args.file.read_text('utf-8-sig')))
    if not args.live:
        print(json.dumps(dict(dry_run=True,action=args.action,words=words),ensure_ascii=False,indent=2));return
    ctrl=open_controller(c)
    try:
        if args.action=='status':result=ctrl.status()
        elif args.action=='frame':
            frame=ctrl.frame();result=frame.as_dict() if frame else {'frame':'EMPTY'}
        elif args.action=='feature-config':commit_feature(ctrl,words);result={'feature_config_id':words[0],'calibration_id':words[1]}
        elif args.action=='control-config':
            for i,word in enumerate(words):ctrl.io.write(0x300+4*i,word)
            ctrl.io.write(0x18,0x434f4d54)
            result={'commit_status':ctrl.io.read(8)}
            if result['commit_status']>>8&255:raise RuntimeError('Control configuration rejected: '+str(result))
            if [ctrl.io.read(0x500+4*i) for i in range(24)]!=words:raise RuntimeError('Control configuration readback mismatch')
        else:ctrl.command(args.opcode,args.payload);result={'accepted':True,'opcode':args.opcode}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:ctrl.close()

if __name__=='__main__':main()
