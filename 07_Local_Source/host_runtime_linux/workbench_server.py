#!/usr/bin/env python3
"""Offline local measurement/fitting UI. No mock measurements, MMIO or actuator owner."""
import argparse,json,os
from pathlib import Path
from cabinet.web import server
from commissioning.workbench import Workbench

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--base-config',type=Path,required=True);p.add_argument('--port',type=int,default=8772);a=p.parse_args()
    read=os.environ.get('CABINET_HMI_TOKEN');write=os.environ.get('CABINET_CONTROL_TOKEN')
    if not read or not write or len(write)<32 or read==write:raise ValueError('Separate session read/control tokens required')
    class Local:
        config=json.loads(a.base_config.read_text())
        def public_state(self):return dict(link='OFFLINE',test=False,local_files_only=True)
    service=Local();service.workbench=Workbench(a.workspace,a.base_config)
    listener=server('127.0.0.1',a.port,service,token=read,control_token=write)
    print('Local workbench: http://127.0.0.1:%d/commissioning'%listener.server_address[1],flush=True)
    try:listener.serve_forever()
    finally:listener.server_close()
if __name__=='__main__':main()
