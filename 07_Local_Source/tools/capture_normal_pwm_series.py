"""Collect disjoint time segments before training or inspecting holdout scores."""
import subprocess
from pathlib import Path
import sys
import json
import time

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=False)
confirmation=json.loads(Path(sys.argv[2]).read_text())
assert confirmation['condition']=='normal'
assert confirmation['os_boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert confirmation['board_not_before_monotonic_s']<=time.monotonic()
(root/'normal_confirmation.json').write_text(json.dumps(confirmation,ensure_ascii=False,indent=2),encoding='utf-8')
for split in ('train', 'calibration', 'test'):
    print('START_SWEEP ' + split, flush=True)
    command = [sys.executable, '/run/pwm_normal_sweep.py', '--output', str(root / split), '--seconds', '20']
    if split == 'calibration':
        command.append('--descending')
    subprocess.check_call(command)
    print('COMPLETE_SWEEP ' + split, flush=True)
