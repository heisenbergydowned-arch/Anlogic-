"""Allow startup only after a pinned, same-boot hardware probe and clean ownership."""
import argparse
import os
from pathlib import Path
import re
from .bundle import Bundle,digest
from .core import finite,live_input
from .numerical import review_extended_rows
from .live import read_state
from v4_runtime.native_lease import NATIVE_LEASE_FILE
from v4_runtime.bundle import loads
import time

def validate_report(r,model_pin,adapter_pin,boot,kernel):
    if (r.get('status')!='PASS_REAL_NORMAL_CAPTURE_ALNPU_RECONSTRUCTION_ONLY' or
            r.get('npu_executed') is not True or r.get('native_cleanup_verified') is not True or
            r.get('qualified') is not False or r.get('fault_classes_trained')!=[] or
            r.get('source')!='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC'):
        raise ValueError('Actual normal-only NPU probe with verified cleanup required')
    if r.get('model_sha256')!=model_pin or r.get('adapter_sha256')!=adapter_pin:
        raise ValueError('Probe artifact pins differ')
    if r.get('boot_id')!=boot or r.get('kernel_release')!=kernel:
        raise ValueError('Fresh probe on the current boot/kernel required')
    audit=r.get('backend_audit',{})
    if audit.get('assigned_backends')!=['Alnpu'] or audit.get('backend_assignment_verified') is not True:
        raise ValueError('Alnpu-only graph evidence required')
    if r.get('vectors')!=128 or r.get('irq_delta')!={'HARD_NPU_IRQ':384,'SOFT_NPU_IRQ':0}:
        raise ValueError('128-vector hardware interrupt evidence required')
    review=review_extended_rows(r)
    if r.get('max_quantized_error',0)>3 and r.get('numerical_review')!=review:
        raise ValueError('Calibration rounding evidence changed')
    for key,limit in [('normal_holdout_alarm_rate',.05)]:
        if not finite(r.get(key)) or not 0<=r[key]<=limit:raise ValueError('Probe numerical gate failed: '+key)
    latency=r.get('execute_ms',{}).get('p99')
    if not finite(latency) or not 0<latency<128:raise ValueError('Probe latency gate failed')

def main():
    p=argparse.ArgumentParser()
    for name in ('bundle','manifest-sha256','library','library-sha256','acceptance','acceptance-sha256'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args()
    b=Bundle(a.bundle,a.manifest_sha256)
    library=Path(a.library)
    if library.is_symlink() or digest(library.read_bytes())!=a.library_sha256:raise ValueError('Adapter pin differs')
    if not re.fullmatch('[0-9a-f]{64}',a.acceptance_sha256):raise ValueError('Pending board acceptance is not an enable authorization')
    path=Path(a.acceptance)
    # Same private regular-file requirements as the live collector.
    report=read_state(path)
    if digest(path.read_bytes())!=a.acceptance_sha256:raise ValueError('Hardware acceptance report pin differs')
    validate_report(report,b.pin,a.library_sha256,Path('/proc/sys/kernel/random/boot_id').read_text().strip(),os.uname().release)
    lease=read_state(NATIVE_LEASE_FILE)
    if lease.get('schema')!='cabinet-native-lease-v1' or lease.get('state')!='CLEAN':
        raise ValueError('Native ownership not CLEAN; verify recovery, never erase the lease automatically')
    for unused in range(40):
        try:live_input(read_state(Path('/run/cabinet-live/state.json')),time.monotonic(),b.expected);break
        except (OSError,ValueError):time.sleep(.05)
    else:raise ValueError('No current matching real input')
    print('PASS_SAME_BOOT_REAL_NORMAL_NPU_START_GATE')

if __name__=='__main__':main()
