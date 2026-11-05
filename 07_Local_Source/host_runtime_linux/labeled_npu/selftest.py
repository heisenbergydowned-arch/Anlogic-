"""An old admission permits a fresh hardware probe, never a blind boot start."""
import argparse
import os
from pathlib import Path
import uuid
from normal_npu.boot_recovery import recover
from normal_npu.live import read_state,publish
from .boot_selection import prepare_selftest_selection,require_selftest_selection_unchanged
from v4_runtime.native_lease import NATIVE_LEASE_FILE
from .bundle import Bundle,digest
from .probe import main as probe,validate_report

def main(argv=None):
    p=argparse.ArgumentParser()
    for n in ('bundle','manifest-sha256','library','library-sha256','admission','admission-sha256'): p.add_argument('--'+n,required=True)
    a,selection=prepare_selftest_selection(p.parse_args(argv)); b=Bundle(a.bundle,a.manifest_sha256); b.hardware_model()
    admission=Path(a.admission)
    if digest(admission.read_bytes())!=a.admission_sha256: raise ValueError('ADMISSION_PIN_CHANGED')
    r=read_state(admission); validate_report(r,b.pin,a.library_sha256,r['boot_id'],os.uname().release)
    library=Path(a.library)
    if library.is_symlink() or digest(library.read_bytes())!=a.library_sha256: raise ValueError('ADAPTER_PIN_CHANGED')
    recover()
    if read_state(NATIVE_LEASE_FILE).get('state')!='CLEAN': raise ValueError('NATIVE_OWNER_NOT_CLEAN')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    output=Path('/var/lib/cabinet/npu-diagnostics/labeled-live-selftest')/boot/uuid.uuid4().hex
    result=probe(['--bundle',a.bundle,'--manifest-sha256',b.pin,'--library',a.library,
           '--library-sha256',a.library_sha256,'--output',str(output)])
    if result!=0:raise RuntimeError('CLASSIFIER_SELFTEST_FAILED')
    validate_report(read_state(output/'validation.json'),b.pin,a.library_sha256,boot,os.uname().release)
    if read_state(NATIVE_LEASE_FILE).get('state')!='CLEAN':raise ValueError('SELFTEST_NATIVE_OWNER_NOT_CLEAN')
    require_selftest_selection_unchanged(a,selection['env_sha256'])
    publish(Path('/run/cabinet-labeled-npu/selftest.json'),dict(status='PASS_CURRENT_BOOT_HARDWARE_SELFTEST',
        selection_env_sha256=selection['env_sha256'],selection_action=selection['action'],boot_id=boot,model_sha256=b.pin,
        report=str(output/'validation.json'),report_sha256=digest((output/'validation.json').read_bytes()),
        admission_sha256=a.admission_sha256))

if __name__=='__main__': main()
