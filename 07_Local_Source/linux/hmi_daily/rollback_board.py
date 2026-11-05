"""Restore the pre-install display without changing firmware or learning evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


root = Path('/home/uisrc/lvgl_demo')
backup = Path('/root/cabinet_daily_learning_backup_20261013')
manifest = json.loads((backup / 'files.json').read_text(encoding='utf-8'))
for name, expected in manifest['old_hashes'].items():
    if hashlib.sha256((backup / name).read_bytes()).hexdigest() != expected:
        raise RuntimeError('Backup checksum mismatch: ' + name)
subprocess.run(['systemctl', 'stop', 'cabinet-live-display.service'], check=True)
for name in manifest['previous']:
    shutil.copy2(str(backup / name), str(root / name))
for name in manifest['created']:
    if (root / name).exists():
        (root / name).unlink()
Path('/run/cabinet-live/ui_view').write_text('overview\n', encoding='utf-8')
os.sync()
subprocess.run(['systemctl', 'reset-failed', 'cabinet-live-display.service'], check=True)
subprocess.run(['systemctl', 'start', 'cabinet-live-display.service'], check=True)
print('Restored previous display; learning evidence database is preserved.')
