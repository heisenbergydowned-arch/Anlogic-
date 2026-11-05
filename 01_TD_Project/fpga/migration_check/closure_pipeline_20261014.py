"""Fresh TEST then REAL routed builds; never program hardware or reuse old bitstreams."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'migration_check/closure_20261014_r1'
    output.mkdir(exist_ok=False)
    report = {'status': 'RUNNING', 'test': 'NOT_STARTED', 'real': 'NOT_STARTED',
              'started_utc': datetime.now(timezone.utc).isoformat(), 'board_programmed': False}

    def save():
        (output / 'pipeline.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    save()
    try:
        for variant, project in (('test', 'cooling_link_test'), ('real', 'cooling_link')):
            report[variant] = 'RUNNING'
            save()
            destination = output / variant
            command = [sys.executable, str(root / 'migration_check/run_guarded_resume_vm.py'),
                       '--project', project, '--output', str(destination), '--timeout', '43200',
                       '--td', 'C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe']
            with (output / (variant + '-driver.log')).open('w', encoding='utf-8') as log:
                result = subprocess.run(command, cwd=str(root), stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            validation = json.loads((destination / 'validation.json').read_text(encoding='utf-8'))
            report[variant] = validation['status']
            save()
            if result.returncode or validation['status'] != 'PASS' or not validation.get('release_qualified'):
                raise RuntimeError(variant + ' failed; later variants not started')
        report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', error=str(error))
    finally:
        report['completed_utc'] = datetime.now(timezone.utc).isoformat()
        save()
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
