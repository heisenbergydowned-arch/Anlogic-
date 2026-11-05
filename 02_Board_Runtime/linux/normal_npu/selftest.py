"""Repeat the admitted real-vector hardware probe before every live-service start."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid
from .bundle import Bundle,digest
from .live import read_state,publish
from .probe import main as run_probe
from .start_gate import validate_report
from v4_runtime.native_lease import NATIVE_LEASE_FILE
from .boot_recovery import recover
from .boot_selection import prepare_selftest_selection,require_selftest_selection_unchanged

def main(argv=None):
    p=argparse.ArgumentParser()
    for n in ('bundle','manifest-sha256','library','library-sha256','admission','admission-sha256'):
        p.add_argument('--'+n,required=True)
    a,selection=prepare_selftest_selection(p.parse_args(argv))
    print('NORMAL_NPU_BOOT_SELECTION '+json.dumps(selection),flush=True)
    b=Bundle(a.bundle,a.manifest_sha256);b.hardware_model()
    admission_path=Path(a.admission);admission=read_state(admission_path)
    if digest(admission_path.read_bytes())!=a.admission_sha256:raise ValueError('Admission report pin differs')
    # A prior successful physical probe admits this exact immutable model and
    # adapter. It never substitutes for the fresh hardware probe below.
    validate_report(admission,b.pin,a.library_sha256,admission['boot_id'],os.uname().release)
    library=Path(a.library)
    if library.is_symlink() or digest(library.read_bytes())!=a.library_sha256:raise ValueError('Adapter pin differs')
    # A reboot resets the reviewed driver. Recover only a different boot's
    # persisted owner after checking loaded modules, IRQs and device owners.
    # Dirty leases from this boot still require manual recovery.
    recovery= recover()
    print('NORMAL_NPU_BOOT_LEASE '+json.dumps(recovery),flush=True)
    lease=read_state(NATIVE_LEASE_FILE)
    if lease.get('schema')!='cabinet-native-lease-v1' or lease.get('state')!='CLEAN':
        raise ValueError('Native lease is not CLEAN; manual verified recovery required')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    target=Path('/var/lib/cabinet/npu-diagnostics/normal-live-selftest')/boot/uuid.uuid4().hex
    arguments=['--bundle',a.bundle,'--manifest-sha256',a.manifest_sha256,
        '--library',a.library,'--library-sha256',a.library_sha256,'--output',str(target),'--saved-startup']
    if run_probe(arguments)!=0:raise RuntimeError('Fresh hardware selftest failed')
    report=read_state(target/'validation.json')
    validate_report(report,b.pin,a.library_sha256,boot,os.uname().release)
    if read_state(NATIVE_LEASE_FILE).get('state')!='CLEAN':raise RuntimeError('Selftest did not release native owner')
    require_selftest_selection_unchanged(a,selection['env_sha256'])
    publish(Path('/run/cabinet-normal-npu/selftest.json'),dict(status='PASS_CURRENT_BOOT_HARDWARE_SELFTEST',
        selection_env_sha256=selection['env_sha256'],selection_action=selection['action'],
        boot_id=boot,model_sha256=b.pin,report=str(target/'validation.json'),
        report_sha256=digest((target/'validation.json').read_bytes()),
        admission_sha256=a.admission_sha256,updated_at=time.monotonic()))
    print('PASS_CURRENT_BOOT_HARDWARE_SELFTEST')

if __name__=='__main__':main()
