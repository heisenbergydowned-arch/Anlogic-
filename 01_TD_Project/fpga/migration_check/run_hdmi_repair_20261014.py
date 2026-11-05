"""Retain the failed full build and repair only its routed HDMI placement."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import run_guarded_resume_vm as guard


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = ROOT / 'migration_check/closure_20261014_r1'


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('relocate', 'cluster'), default='cluster')
    parser.add_argument('--attempt', type=int)
    args = parser.parse_args()
    cluster = args.mode == 'cluster'
    attempt = args.attempt if args.attempt is not None else (2 if cluster else 1)
    if not 1 <= attempt <= 100:
        raise RuntimeError('Invalid physical attempt number')
    output = ROOT / ('migration_check/closure_20261014_hdmi_r' + str(attempt))
    script = ROOT / ('migration_check/closure_hdmi_bound_20261014.tcl' if cluster else 'migration_check/closure_hdmi_repair_20261014.tcl')
    pointer = ROOT / 'migration_check/closure_active_20261014.json'
    previous_pointer = None
    if pointer.exists():
        previous_pointer = json.loads(pointer.read_text(encoding='utf-8'))
        if not re.fullmatch(r'migration_check/closure_20261014_hdmi_r[1-9][0-9]*/pipeline.json', previous_pointer.get('pipeline', '')):
            raise RuntimeError('Unknown active build pointer')
        previous_pipeline = json.loads((ROOT / previous_pointer['pipeline']).read_text(encoding='utf-8'))
        if previous_pipeline['status'] != 'FAIL':
            raise RuntimeError('Previous physical attempt has not failed; refusing to replace it')
    original = json.loads((ORIGIN / 'real/validation.json').read_text(encoding='utf-8'))
    test = json.loads((ORIGIN / 'test/validation.json').read_text(encoding='utf-8'))
    if original['status'] != 'FAIL' or original.get('source_changes') or original.get('new_sources'):
        raise RuntimeError('Only the unchanged failed physical build may be repaired')
    if test['status'] != 'PASS' or test.get('release_qualified') is not True:
        raise RuntimeError('Current TEST acceptance is required')
    sources = guard.manifest('cooling_link')
    if sources != original['sources']:
        raise RuntimeError('Full synthesis inputs changed; cannot reuse this checkpoint')
    if any(sources[name] != expected for name, expected in test['sources'].items() if name in sources):
        raise RuntimeError('TEST and REAL shared inputs differ')
    console = (ORIGIN / 'real/console.log').read_text(encoding='utf-8', errors='replace')
    for marker in ('VM_SYNTHESIS_PASS: cooling_link', 'VM_PLACE_PASS: cooling_link',
                   'VM_ROUTE_PASS: cooling_link', 'bitgen blocked'):
        if marker not in console:
            raise RuntimeError('Missing full-build provenance: ' + marker)
    checkpoint = ORIGIN / ('real/gate.db' if cluster else 'real/pr.db')
    checkpoint_hash = checksum(checkpoint)
    physical_sources = {Path(__file__).relative_to(ROOT).as_posix(): checksum(Path(__file__)),
                        script.relative_to(ROOT).as_posix(): checksum(script)}
    output.mkdir(exist_ok=False)
    destination = output / 'real'
    destination.mkdir()
    pipeline = dict(status='RUNNING', test='PASS', real='RUNNING',
                    started_utc=datetime.now(timezone.utc).isoformat(), board_programmed=False,
                    origin_pipeline='migration_check/closure_20261014_r1/pipeline.json',
                    test_source='migration_check/closure_20261014_r1/test',
                    real_source=destination.relative_to(ROOT).as_posix())
    report = dict(status='RUNNING', release_qualified=False, project='cooling_link',
                  started_utc=pipeline['started_utc'], sources=sources, physical_sources=physical_sources,
                  scope=('Unchanged full-SoC gate checkpoint, explicit HDMI floorplan, fresh placement/route/STA/bitgen; no board acceptance'
                         if cluster else 'Unchanged full-SoC synthesis checkpoint, checked HDMI relocation and fresh ECO route/STA/bitgen; no board acceptance'),
                  checkpoint=dict(path=checkpoint.relative_to(ROOT).as_posix(), sha256=checkpoint_hash,
                                  validation_sha256=checksum(ORIGIN / 'real/validation.json')))

    def save():
        (output / 'pipeline.json').write_text(json.dumps(pipeline, indent=2) + '\n', encoding='utf-8')
        (destination / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    save()
    if previous_pointer is not None:
        (output / 'previous_active.json').write_text(json.dumps(previous_pointer) + '\n', encoding='utf-8')
    pointer.write_text(json.dumps(dict(pipeline=(output / 'pipeline.json').relative_to(ROOT).as_posix(),
                                      test=pipeline['test_source'], real=pipeline['real_source'])) + '\n', encoding='utf-8')
    try:
        environment = dict(os.environ, COOLING_REPAIR_CHECKPOINT=checkpoint.as_posix(),
                           COOLING_REPAIR_OUTPUT=destination.as_posix())
        with (destination / 'console.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([r'C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe',
                                     script.as_posix()],
                                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                    env=environment, timeout=43200, creationflags=subprocess.CREATE_NO_WINDOW)
        report['tool_exit_code'] = result.returncode
        final = guard.manifest('cooling_link')
        report['source_changes'] = [name for name, expected in sources.items() if final.get(name) != expected]
        report['new_sources'] = sorted(set(final) - set(sources))
        if report['source_changes'] or report['new_sources'] or checksum(checkpoint) != checkpoint_hash:
            raise RuntimeError('Checkpoint or synthesis inputs changed')
        if any(checksum(ROOT / name) != expected for name, expected in physical_sources.items()):
            raise RuntimeError('Physical repair script changed during execution')
        console = (destination / 'console.log').read_text(encoding='utf-8', errors='replace')
        if result.returncode or 'VM_CHECK_FAILED:' in console:
            raise RuntimeError('Physical repair failed; bitstream not accepted')
        for marker in (('VM_HDMI_BOUND_PASS:' if cluster else 'VM_HDMI_RELOCATION_PASS:'), 'VM_ROUTE_PASS:', 'VM_ROUTED_TIMING_PASS:',
                       'VM_BITGEN_PASS:', 'VM_CHECK_PASS:'):
            if marker not in console:
                raise RuntimeError('Missing completion marker: ' + marker)
        timing = (destination / 'pr.timing').read_text(encoding='utf-8')

        def number(pattern, body):
            matched = re.search(pattern, body)
            if matched is None:
                raise RuntimeError('Missing acceptance field: ' + pattern)
            return float(matched[1])

        setup = number(r'SWNS:\s*(-?[\d.]+)ns', timing)
        hold = number(r'HWNS:\s*(-?[\d.]+)ns', timing)
        period = number(r'Period Check WNS:\s*(-?[\d.]+)ns', timing)
        coverage = number(r'STA coverage\s*:\s*([\d.]+)%', timing)
        if min(setup, hold, period) < 0 or coverage < 99.9 or 'Routed' not in timing or not re.search(r'Check Corner\s*:\s*Both', timing):
            raise RuntimeError('Routed timing/coverage not qualified')
        clocks = {}
        for suffix, expected in (('HP0', 150), ('GP0S', 75), ('GP1S', 150), ('HP1', 150)):
            matched = re.search(r'\n\s*clk\d+:\s*([\d.]+)\s+(\d+)\s+[^\n]*GEN_PL_' + suffix + r'(?:\s|\n)', timing)
            if matched is None or int(matched[2]) < 1 or abs(float(matched[1]) - expected) > 0.1:
                raise RuntimeError('Native PS clock not qualified: ' + suffix)
            clocks[suffix] = float(matched[1])
        area = (destination / 'phy.area').read_text(encoding='utf-8')
        resources = {name: int(number(pattern, area)) for name, pattern in (
            ('slice', r'#slice\*?\s+(\d+)'), ('eram', r'#eram\s+(\d+)'), ('dsp', r'#dsp\s+(\d+)'))}
        if resources['slice'] > 52480 or resources['eram'] > 280 or resources['dsp'] > 240:
            raise RuntimeError('Device capacity exceeded')
        bitstream = destination / 'cooling_link.bit'
        if not bitstream.is_file() or not bitstream.stat().st_size:
            raise RuntimeError('No new nonempty bitstream')
        report.update(status='PASS', release_qualified=True, setup_wns_ns=setup, hold_wns_ns=hold,
                      period_wns_ns=period, sta_coverage_percent=coverage, native_ps_clock_mhz=clocks, resources=resources,
                      artifacts={name: dict(bytes=(destination / name).stat().st_size, sha256=checksum(destination / name))
                                 for name in ('cooling_link.bit', 'pr.timing', 'phy.area', 'console.log')})
        pipeline.update(status='PASS', real='PASS')
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        pipeline.update(status='FAIL', real='FAIL', error=str(error))
    report['completed_utc'] = pipeline['completed_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
