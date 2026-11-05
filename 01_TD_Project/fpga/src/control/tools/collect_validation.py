"""Collect existing reports and check their source hashes. Does not rerun tools."""
from pathlib import Path
import hashlib
import json
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def collect(name, path):
    data = json.loads(path.read_text('utf-8'))
    changed = []
    for source in data.get('sources', []):
        p = Path(source['path'])
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != source['sha256']:
            changed.append(str(p))
    if not data.get('sources'):
        raise RuntimeError('Report lacks source hashes: ' + str(path))
    return {'name': name, 'report': str(path), 'run_utc': data.get('run_utc'),
            'reported_status': data['status'], 'matches_current_sources': not changed,
            'changed_since_report': changed, 'tests': data.get('tests'),
            'gate_setup_wns_ns': data.get('gate_setup_wns_ns'),
            'sta_coverage_percent': data.get('sta_coverage_percent'),
            'resources': data.get('resources')}


def main():
    required = [collect('control_regression', ROOT/'sim/results/validation.json'),
                collect('final_control_core', ROOT/'sim/td_control_final/synthesis.json'),
                collect('final_real_acquisition_top', ROOT/'sim/td_acq_release/synthesis.json')]
    if any(r['reported_status'] != 'PASS' or not r['matches_current_sources'] for r in required):
        raise RuntimeError('Final source regression/core/acquisition evidence missing or stale')
    snapshot = collect('full_soc_budget_snapshot_before_final_mode_format_fixes', ROOT/'sim/td_soc_release/synthesis.json')
    result = {'generated_utc': datetime.now(timezone.utc).isoformat(),
              'control_source_gate': 'PASS', 'hardware_release_ready': False,
              'scope': 'Implemented PL control/protection/alarm logic, connected to original acquisition top',
              'current_source_evidence': required, 'integration_assessment_snapshot': snapshot,
              'remaining': [
                  'Full-chip synthesis must be refreshed after the final mode/format fixes; latest budget snapshot nearly fills slices and has negative global Setup.',
                  'No new whole-chip P&R, routed Hold, bitstream or physical acceptance.',
                  'Fan PWM/FG/PPR, sensor thresholds, fallback, PI and buzzer/heat-load executor need physical calibration and acceptance.',
                  'Existing ICM initialization and actual sampling rate must be closed before vibration production qualification.',
                  'Full 39D overlapping window and PS/AXI data path remain separate unfinished integration.',
                  'Optional same-domain AXI adapter is verified but not connected to PS; no website/model/local-persistence completion claim.'
              ]}
    dest = ROOT/'sim/implementation_validation.json'
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('CONTROL SOURCE GATE PASS: regression and final core/acquisition reports match current RTL.')
    print('HARDWARE RELEASE: PENDING. Full-chip report is an assessment snapshot, not final RTL timing/bitstream evidence.')
    print(dest)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('EVIDENCE FAIL: ' + str(e)); raise SystemExit(1)
