"""Sensor compatibility + Linux host C/SDK syntax + actual Linux service tests.

SDK headers remain in sim/sdk_headers, excluded from delivery. ARM linking,
Alnpu execution, native timing and physical sensor behavior are not claimed.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]
DEST=ROOT/'src/edge/sim/support_final'

def main():
    DEST.mkdir(parents=True,exist_ok=True);r=dict(status='RUNNING',started_utc=datetime.now(timezone.utc).isoformat(),checks=[])
    file=DEST/'validation.json'
    def save():file.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    def run(name,args,timeout=120,marker=None,cwd=None):
        p=subprocess.run(list(map(str,args)),cwd=cwd,capture_output=True,timeout=timeout)
        output=p.stdout.decode('utf-8',errors='replace')+p.stderr.decode('utf-8',errors='replace').replace('\x00','')
        (DEST/(name+'.log')).write_text(output,encoding='utf-8')
        if p.returncode or marker and marker not in output:raise RuntimeError(name+' failed: '+output[-1000:])
        r['checks'].append(dict(name=name,status='PASS',command=list(map(str,args)),marker=marker));save();print(name+' PASS',flush=True)
    try:
        iv=Path.home()/'AppData/Local/Programs/iverilog-v14/bin/iverilog.exe';vvp=iv.with_name('vvp.exe')
        for bench in ('tb_sns_sync','tb_sns_timeout'):
            extra=['-Ptb_sns_sync.CLK_FREQ=25000000','-Ptb_sns_sync.SPI_DIV_TEST=2'] if bench=='tb_sns_sync' else []
            exe=DEST/(bench+'.vvp')
            run(bench+'_compile',[iv,'-g2005','-s',bench,*extra,'-o',exe,ROOT/'src/acq/sns_sync.v',ROOT/'sim/models/icm20602_model.v',ROOT/'sim'/(bench+'.v')])
            run(bench,[vvp,exe],timeout=300,marker='ALL PASS')
        mount='/mnt/d/Desktop/FU_Code/soc_merge/soc_merge';sdk=mount+'/src/edge/sim/sdk_headers'
        run('alnpu_sdk_syntax',['wsl.exe','-d','Ubuntu','--exec','g++','-std=c++17','-Wall','-Wextra','-Werror','-fsyntax-only','-I'+sdk,mount+'/src/edge/linux/npu/edge_npu.cpp'])
        library=mount+'/src/edge/sim/libedge_mmio_host.so'
        run('mmio_host_compile',['wsl.exe','-d','Ubuntu','--exec','gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-o',library,mount+'/src/edge/linux/native/mmio.c'])
        code=f"import sys,unittest;sys.path.insert(0,{(mount+'/src/edge/linux')!r});r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover({(mount+'/src/edge/linux/tests')!r}));sys.exit(not r.wasSuccessful())"
        run('linux_service_tests',['wsl.exe','-d','Ubuntu','--exec','env','EDGE_TEST_MMIO_LIB='+library,'python3','-c',code],marker='OK')
        files=[ROOT/'sim/tb_sns_sync.v',ROOT/'sim/tb_sns_timeout.v',ROOT/'sim/models/icm20602_model.v',ROOT/'src/acq/sns_sync.v']
        files += [p for p in (ROOT/'src/edge/linux').rglob('*') if p.is_file() and p.suffix in ('.py','.c','.cpp','.html','.json') and not any(n in p.parts for n in ('runtime','__pycache__'))]
        r.update(status='PASS',completed_utc=datetime.now(timezone.utc).isoformat(),limitations='Linux x86 host C and mock model tests; SDK syntax only, not ARM link/NPU/board',
                 sources=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]);save();return 0
    except Exception as e:
        r.update(status='FAIL',error=type(e).__name__+': '+str(e));save();print(r['error'],flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
