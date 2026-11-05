"""Make a self-contained Linux source package and smoke-test an extracted copy.

No SDK redistribution, old bitstream, runtime database, credential or SD writes.
The current TD project remains in the original engineering tree.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
ROOT=Path(__file__).resolve().parents[3]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S');base=ROOT/'deliveries';base.mkdir(exist_ok=True)
    folder=base/('cabinet_edge_linux_'+stamp);folder.mkdir()
    src=ROOT/'src/edge/linux'
    allowed={'.py','.c','.cpp','.h','.html','.json','.dtsi','.service','.sh','.cmd','.md'}
    for p in src.rglob('*'):
        if p.is_file() and not any(n in p.parts for n in ('runtime','__pycache__')) and (p.suffix in allowed or p.name=='Makefile'):
            out=folder/'linux'/p.relative_to(src);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out)
    shutil.copy2(ROOT/'src/edge/README.md',folder/'README.md')
    (folder/'docs').mkdir()
    for name,rel in [('control_README.md','src/control/README.md'),('features_README.md','src/features/README.md'),
                     ('control_unqualified.template.json','src/control/config_unqualified.template.json')]:
        shutil.copy2(ROOT/rel,folder/'docs'/name)
    readme=(folder/'README.md').read_text('utf-8').replace('../control/README.md','docs/control_README.md').replace('../features/README.md','docs/features_README.md')
    readme=readme.replace('..\\sim\\results\\frames.hex','..\\samples\\frames.hex')
    readme+='\n\n交付包内回放文件位于 `samples/frames.hex`；TD工程、RTL和工程树内回归命令需在原工程目录运行。电脑快速启动以 `START_HERE.md` 为准。\n'
    (folder/'README.md').write_text(readme,encoding='utf-8')
    (folder/'samples').mkdir();shutil.copy2(ROOT/'src/edge/sim/results/frames.hex',folder/'samples/frames.hex')
    (folder/'evidence').mkdir()
    evidence={'link':'src/edge/sim/results/validation.json','features':'src/edge/sim/features_compat_final/regression_report.json',
              'support':'src/edge/sim/support_final/validation.json','feature_gate':'src/edge/sim/td_feature_final/validation.json',
              'full_chip':'src/edge/sim/td_link_final/validation.json','clock_recheck':'src/edge/sim/clock_recheck/validation.json',
              'top_elaboration':'src/edge/sim/top_elaboration_final/validation.json',
              'control':'src/control/sim/results/validation.json','hmi':'src/edge/sim/hmi_browser_review.json'}
    states={}
    for key,rel in evidence.items():
        path=ROOT/rel
        if not path.exists():raise RuntimeError('Missing evidence '+rel)
        data=json.loads(path.read_text('utf-8'));states[key]=data['status'];shutil.copy2(path,folder/'evidence'/(key+'.json'))
    for key in ('link','features','support','top_elaboration','control','hmi'):
        if states[key]!='PASS':raise RuntimeError('Required code validation not PASS: '+key)
    if states['full_chip']=='RUNNING' or states['clock_recheck']=='RUNNING':raise RuntimeError('Wait for hardware evaluation to finish')
    # Package README contains useful whole-project references. Give a portable
    # entry page so the Linux teammate does not need the original D: tree.
    (folder/'START_HERE.md').write_text('''# Linux链路联调包

这是应用源码/模拟联调包，不是SD镜像或可烧录位流。

电脑：双击 linux/start_mock.cmd，打开 http://127.0.0.1:8766。
也可在linux目录运行：python run_edge.py --mock --collector --replay ../samples/frames.hex。
结果必须显示TEST/MOCK；真实自动控制/模型资格默认关闭。

板端：先阅读README.md及linux配置，核对新FPGA ABI/UIO/DTB；make -C native；install.sh只安装不启动服务。
NPU需要板卡原SDK及实际39→5模型，包内仅含适配源码。x86测试不能代替ARM/NPU/实板验收。

evidence保存各层结果；full_chip不是PASS时没有发布位流，不能把此包视为整机已烧录通过。
manifest.json可核对所有交付文件；smoke_validation.json是从独立副本运行得到的模拟链路证据。
''',encoding='utf-8')
    manifest=dict(schema='cabinet-delivery-v1',created_utc=datetime.now(timezone.utc).isoformat(),
                  hardware_release_qualified=False,validation=states,
                  exclusions=['vendor SDK','bitstream/BOOT.bin','runtime databases','credentials'],files=[])
    for p in sorted(folder.rglob('*')):
        if p.is_file():manifest['files'].append(dict(path=p.relative_to(folder).as_posix(),sha256=digest(p),bytes=p.stat().st_size))
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Test outside the source-tree layout, with no original repo PYTHONPATH.
    smoke=ROOT/'src/edge/sim'/('package_smoke_'+stamp);smoke.mkdir()
    archive=base/(folder.name+'.zip')
    def archive_files():
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for p in folder.rglob('*'):
                if p.is_file():z.write(p,p.relative_to(folder))
    archive_files()
    with zipfile.ZipFile(archive) as z:z.extractall(smoke) # Only our just-created whitelist archive.
    for m in manifest['files']:
        if digest(smoke/m['path'])!=m['sha256']:raise RuntimeError('Extracted checksum mismatch: '+m['path'])
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    config=json.loads((smoke/'linux/config.example.json').read_text('utf-8'))
    config['database']=str(smoke/'smoke.sqlite3');config['uplink'].update(url=f'http://127.0.0.1:{port}/v1/devices/events',loopback_test=True)
    conf=smoke/'smoke_config.json';conf.write_text(json.dumps(config),encoding='utf-8')
    command=[sys.executable,str(smoke/'linux/run_edge.py'),'--mock','--collector','--config',str(conf),'--replay',str(smoke/'samples/frames.hex'),
             '--port',str(port),'--duration','8']
    process=subprocess.Popen(command,cwd=smoke/'linux',stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    result=dict(status='RUNNING',test_only=True,command=command)
    try:
        state=received=model_state=None;deadline=time.monotonic()+7
        while time.monotonic()<deadline and process.poll() is None:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=.5) as response:state=json.load(response)
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/received',timeout=.5) as response:received=json.load(response)
                if state.get('model') and state['model'].get('backend')=='MOCK':model_state=state
                # The replay has only three checked frames. Preserve the valid
                # inference observation before its TTL expires, then wait for
                # the later physical-test event to reach the collector.
                if model_state and received:break
            except OSError:pass
            time.sleep(.05)
        if not model_state or model_state['link']!='ONLINE' or not model_state['test']:raise RuntimeError('Independent mock chain did not run')
        if len(model_state['frame']['values'])!=39 or not received:raise RuntimeError('Frame/model/event/collector chain incomplete')
        if model_state['model']['frame_id']!=model_state['frame']['frame_id']:raise RuntimeError('Model is not paired with its replayed frame')
        if not all(e.get('maintenance_test_flag') for e in received):raise RuntimeError('Mock collector event lost TEST marker')
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=1) as response:
            if '机柜风冷'.encode() not in response.read():raise RuntimeError('HMI missing')
        out,err=process.communicate(timeout=12)
        if process.returncode:raise RuntimeError(out+err)
        result.update(status='PASS',frame_id=model_state['frame']['frame_id'],features=39,backend='MOCK',events_received=len(received),
                      model_observation=model_state['model'],collector_event_ids=[e['event_id'] for e in received],
                      last_state=state,
                      source_package_manifest_sha256=digest(folder/'manifest.json'),output=out+err,completed_utc=datetime.now(timezone.utc).isoformat())
    except BaseException as e:
        if process.poll() is None:process.terminate()
        out,err=process.communicate(timeout=5);result.update(status='FAIL',error=str(e),output=out+err,last_state=state)
    (folder/'smoke_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive_files()
    (base/'LATEST.json').write_text(json.dumps(dict(folder=str(folder),archive=str(archive),sha256=digest(archive),smoke=result['status']),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(folder=str(folder),zip=str(archive),sha256=digest(archive),smoke=result['status']),ensure_ascii=False,indent=2),flush=True)
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
