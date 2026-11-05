#!/usr/bin/env python3
"""Run durable, explicitly confirmed commissioning transactions outside HTTP."""
import argparse,signal,threading
from pathlib import Path
from commissioning.control_jobs import run_manager

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True,type=Path);parser.add_argument('--config',required=True,type=Path)
    args=parser.parse_args();stop=threading.Event()
    for number in (signal.SIGINT,signal.SIGTERM):signal.signal(number,lambda *_:stop.set())
    run_manager(args.directory,args.config,stop)
if __name__=='__main__':main()
