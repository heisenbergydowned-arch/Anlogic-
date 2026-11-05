#!/usr/bin/env python3
"""Measured inputs -> checked parameters -> standby readback -> explicit trial."""
import argparse,json
from pathlib import Path
from commissioning.fit import initialize,build
from commissioning.deploy import check,apply,arm,disarm
from commissioning.measure import record_point,record_trace,evaluate_trace

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action');sub.required=True
    a=sub.add_parser('init');a.add_argument('directory',type=Path);a.add_argument('--device-id',required=True)
    a=sub.add_parser('point');a.add_argument('directory',type=Path);a.add_argument('--channel',choices=['current','pressure','fg','temperature'],required=True)
    a.add_argument('--reference',type=float,required=True);a.add_argument('--split',choices=['fit','validation'],required=True);a.add_argument('--seconds',type=float,default=5)
    a=sub.add_parser('fit');a.add_argument('directory',type=Path);a.add_argument('--base-config',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    for action in ['check','apply','restore','arm','disarm']:
        a=sub.add_parser(action);a.add_argument('directory',type=Path);a.add_argument('--manifest-sha256',required=True)
        if action=='arm':
            a.add_argument('--start-controlled-trial',action='store_true')
            a.add_argument('--mode',choices=['temperature','speed'],default='temperature');a.add_argument('--target-rpm',type=int)
    a=sub.add_parser('record-control');a.add_argument('output',type=Path);a.add_argument('--seconds',type=float,default=30)
    a=sub.add_parser('evaluate-control');a.add_argument('file',type=Path);a.add_argument('--temperature-tolerance-C',type=float)
    a=p.parse_args()
    if a.action=='init':r=initialize(a.directory,a.device_id)
    elif a.action=='point':r=record_point(a.directory,a.channel,a.reference,a.split,a.seconds)
    elif a.action=='fit':r=build(a.directory,a.base_config,a.output)
    elif a.action=='check':
        _,m,_,_,_=check(a.directory,a.manifest_sha256);r=dict(status='CHECKED_PARAMETERS_NOT_APPLIED',device_id=m['device_id'])
    elif a.action in ('apply','restore'):r=apply(a.directory,a.manifest_sha256)
    elif a.action=='arm':r=arm(a.directory,a.manifest_sha256,a.start_controlled_trial,a.mode,a.target_rpm)
    elif a.action=='disarm':r=disarm(a.directory,a.manifest_sha256)
    elif a.action=='record-control':r=record_trace(a.output,a.seconds)
    else:r=evaluate_trace(a.file,temperature_tolerance_C=a.temperature_tolerance_C)
    print(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()
