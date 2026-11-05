#!/usr/bin/env python3
"""Install an admitted real classifier without changing control enable or protection parameters."""
import argparse,copy,json,os,shutil,subprocess,time
from pathlib import Path
from v4_runtime.bundle import Bundle
from v4_runtime.qualification import validate_evidence
from commissioning.fit import sha,save
from commissioning.deploy import atomic,run
from commissioning.measure import observation
from commissioning.runtime import validate_binding
from model_release import transition

def model_config(base,bundle,pin,admission,receipt,registry,model_id):
    result=copy.deepcopy(base)
    result['model']=dict(backend='npu_v4',bundle=str(bundle),bundle_manifest_sha256=pin,model_id=model_id,
        qualified=True,evidence=receipt,allow_synthetic_replay=False,socket='/run/cabinet-npu-formal/npu.sock',timeout_ms=500,
        qualification=dict(directory=str(admission),sha256=receipt,registry=str(registry)))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('bundle','admission','library'):p.add_argument('--'+n,type=Path,required=True)
    for n in ('manifest-sha256','receipt-sha256','library-sha256'):p.add_argument('--'+n,required=True)
    p.add_argument('--activate',action='store_true');a=p.parse_args()
    if os.geteuid()!=0:raise ValueError('Board administrator required')
    review=dict(directory=str(a.admission),sha256=a.receipt_sha256)
    b=Bundle(a.bundle,a.manifest_sha256,reviewed_admission=review)
    validate_evidence(a.admission,a.receipt_sha256,dict(b.manifest,_pin=b.manifest_sha256),b.contract,a.library_sha256)
    if sha(a.library)!=a.library_sha256:raise ValueError('Adapter hash differs')
    target_report=json.loads((a.admission/'target.json').read_text())
    if (sha(target_report['sdk_path'])!=target_report['sdk_sha256'] or target_report['kernel_release']!=os.uname().release
            or target_report['device_id']!='machine:'+Path('/etc/machine-id').read_text().strip()):raise ValueError('Target SDK/kernel/device differs from evaluation')
    edge=Path('/etc/cabinet/edge.json');before=edge.read_bytes();base=json.loads(before)
    d,o,s=observation('/run/cabinet-live/state.json')
    if d['display'].get('capture_state')=='RECORDING':raise ValueError('Finish capture first')
    if not base.get('commissioning'):raise ValueError('Measured parameter package required first')
    validate_binding(base,o['control']['control_words'],o['feature_words'])
    if any(base['contract'].get(k)!=b.contract[k] for k in ('feature_config_id','calibration_id','sample_mode_id')):raise ValueError('Live calibration contract differs')
    if base['contract'].get('input_policy','STABLE_RUN_V1')!=b.contract.get('input_policy','STABLE_RUN_V1'):raise ValueError('Live input policy differs from trained model')
    dest=Path('/opt/cabinet/npu/formal')/a.receipt_sha256;registry=Path('/var/lib/cabinet/model-release')
    settings=model_config(base,dest/'bundle',a.manifest_sha256,dest/'admission',a.receipt_sha256,registry,b.manifest['model_id'])
    if not a.activate:
        print(json.dumps(dict(status='READY_FOR_EXPLICIT_MODEL_ACTIVATION',model_id=b.manifest['model_id'],control_enabled=base['control']['enabled'])));return
    if dest.exists():raise ValueError('Immutable release already exists; use a fresh release/recorded rollback')
    dest.mkdir(parents=True);shutil.copytree(a.bundle,dest/'bundle');shutil.copytree(a.admission,dest/'admission');shutil.copy2(a.library,dest/'adapter.so')
    atomic(dest/'edge.before.json',before);save(dest/'edge.after.json',settings)
    launch=dict(bundle=str(dest/'bundle'),manifest_sha256=a.manifest_sha256,admission=str(dest/'admission'),receipt_sha256=a.receipt_sha256,
        registry=str(registry),library=str(dest/'adapter.so'),library_sha256=a.library_sha256)
    save(dest/'launch.json',launch)
    unit=Path('/etc/systemd/system/cabinet-npu-formal.service');unit_before=unit.read_bytes() if unit.exists() else None
    if unit_before:atomic(dest/'unit.before',unit_before)
    unit_text='''[Unit]
Description=Admitted real Alnpu classifier with startup golden check
After=cabinet-edge.service
Requires=cabinet-edge.service
[Service]
Type=simple
WorkingDirectory=/opt/cabinet/linux
Environment=PYTHONPATH=/opt/cabinet/linux
Environment=LD_LIBRARY_PATH=/opt/cabinet/releases/r45_icm_4khz_20261031/sdk/lib
ExecStart=/usr/bin/python3 /opt/cabinet/linux/formal_start.py --launch %s
Restart=no
KillMode=process
SendSIGKILL=no
TimeoutStopSec=15
UMask=0077
[Install]
WantedBy=multi-user.target
''' % (dest/'launch.json')
    active=registry/'active.json';previous=json.loads(active.read_text()) if active.exists() else {'state':'REVOKED','generation':0}
    save(dest/'registry.before.json',previous)
    units=[n for n in ('cabinet-normal-npu','cabinet-npu-v4-shadow','cabinet-npu-formal') if run(['systemctl','is-active',n],False).stdout.strip()=='active']
    for n in units:run(['systemctl','stop',n])
    if json.loads(Path('/var/lib/cabinet/npu-lease/lease.json').read_text())['state']!='CLEAN':raise ValueError('Retained native owner; activation aborted')
    changed=False
    try:
        release=dict(bundle=str(dest/'bundle'),manifest_sha256=a.manifest_sha256,directory=str(dest/'admission'),sha256=a.receipt_sha256)
        transition(registry,'activate',previous['generation'],release);changed=True
        atomic(unit,unit_text.encode());unit.chmod(0o644);run(['systemctl','daemon-reload'])
        # Restart the collector first. Starting a Type=simple native self-test
        # and immediately restarting its dependency can interrupt its lease.
        atomic(edge,json.dumps(settings,indent=2).encode());run(['systemctl','restart','cabinet-edge','cabinet-local-display'])
        for attempt in range(80):
            try:
                observation('/run/cabinet-live/state.json');break
            except (OSError,ValueError,KeyError):time.sleep(.1)
        else:raise RuntimeError('Collector did not become fresh before native startup')
        run(['systemctl','start','cabinet-npu-formal'])
        good=0;last=None
        for _ in range(120):
            try:
                d,o,s=observation('/run/cabinet-live/state.json');panel=d['display']
                if panel.get('panel_model_valid')=='1' and o.get('model',{}).get('model_id')==b.manifest['model_id']:
                    frame=o['model']['frame_id']
                    if frame!=last:good+=1;last=frame
                    if good>=8:break
            except (OSError,ValueError,KeyError):pass
            time.sleep(.25)
        if good<8:raise RuntimeError('Fresh formal live results did not appear; previous configuration will be restored')
        for n in ('cabinet-normal-npu','cabinet-npu-v4-shadow'):run(['systemctl','disable',n],False)
        run(['systemctl','enable','cabinet-npu-formal'])
        result=dict(status='REAL_CLASSIFIER_INSTALLED_LIVE_VERIFIED',control_enable_unchanged=base['control']['enabled']==settings['control']['enabled'],
            physical_closed_loop_accepted=False,model_id=b.manifest['model_id'],release=str(dest))
        save(dest/'deployment.json',result);print(json.dumps(result,indent=2))
    except BaseException as error:
        run(['systemctl','stop','cabinet-npu-formal'],False)
        atomic(edge,before)
        if changed:
            current=json.loads(active.read_text())
            if previous['state']=='ACTIVE':transition(registry,'rollback',current['generation'],{k:previous[k] for k in ('bundle','manifest_sha256','directory','sha256')})
            else:transition(registry,'revoke',current['generation'])
        if unit_before:atomic(unit,unit_before)
        elif unit.exists():unit.unlink()
        run(['systemctl','daemon-reload']);run(['systemctl','restart','cabinet-edge','cabinet-local-display'])
        clean=json.loads(Path('/var/lib/cabinet/npu-lease/lease.json').read_text())['state']=='CLEAN'
        if clean:
            for n in units:run(['systemctl','start',n],False)
        save(dest/'deployment.json',dict(status='FAILED_PREVIOUS_CONFIGURATION_RESTORED',error=repr(error),native_cleanup_verified=clean));raise
if __name__=='__main__':main()
