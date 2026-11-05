import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SOC = Path(__file__).resolve().parents[3]
EDGE = SOC / 'src/edge'


def main():
    parser = argparse.ArgumentParser(description='SDP810 acquisition, independent windows, protection and frame contract regression')
    parser.add_argument('--iverilog', type=Path, required=True)
    parser.add_argument('--verilator', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = dict(status='RUNNING', started_utc=datetime.now(timezone.utc).isoformat(), tests=[],
                  scope='RTL and host-reader tests only; no real sensor, fan, routed timing, bitstream or board acceptance')
    report_path = output / 'validation.json'

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    save()
    sources = []
    for directory in ('src/acq', 'src/control', 'src/features', 'src/edge/rtl'):
        sources.extend(sorted((SOC / directory).glob('*.v')))
    sources = [source for source in sources if not source.name.startswith('cooling_link')]
    models = [SOC / 'sim/models' / name for name in ('sdp810_model.v', 'aht20_model.v', 'bmp280_model.v')]
    benches = [SOC / 'sim/tb_sdp810_drv.v', SOC / 'sim/tb_i2c_arbiter3.v', SOC / 'sim/tb_sdp810_bus.v',
               EDGE / 'sim/tb_edge_pressure.v', EDGE / 'sim/tb_pressure_convert.v',
               SOC / 'src/control/sim/tb_pressure_safety.v', EDGE / 'sim/tb_edge_features.v']
    readers = [EDGE / 'linux/cabinet/protocol.py', EDGE / 'linux/hmi_daily/cabinet/protocol.py',
               EDGE / 'linux/tests/test_pressure_profile.py', SOC / 'src/features/tools/feature_reference.py', Path(__file__)]
    tracked = sorted(set(sources + models + benches + readers))
    initial_hashes = {str(source): hashlib.sha256(source.read_bytes()).hexdigest() for source in tracked}
    report['sources'] = [dict(path=path, sha256=digest) for path, digest in initial_hashes.items()]
    save()

    def execute(name, command, timeout=120, env=None, marker=None):
        started = time.monotonic()
        result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=timeout, env=env)
        log = result.stdout + result.stderr
        (output / (name + '.log')).write_text(log, encoding='utf-8')
        if result.returncode or marker is not None and marker not in log:
            raise RuntimeError(name + ' failed: ' + log[-1500:])
        return log, round(time.monotonic() - started, 3)

    try:
        runner = args.iverilog.with_name('vvp.exe' if args.iverilog.suffix == '.exe' else 'vvp')
        for bench in benches[:-1]:
            name = bench.stem
            executable = output / (name + '.vvp')
            execute(name + '_compile', [args.iverilog, '-g2012', '-Wall', '-s', name, '-o', executable,
                                       *sources, *models, bench])
            marker = 'all checks passed' if name in ('tb_sdp810_drv', 'tb_i2c_arbiter3') else 'ALL PASS'
            log, seconds = execute(name + '_run', [runner, executable], marker=marker)
            report['tests'].append(dict(test=name, status='PASS', seconds=seconds, marker=marker))
            save()
            print(log.strip().splitlines()[-1], flush=True)

        env = os.environ.copy()
        compiler = args.verilator.resolve()
        prefix = compiler.parent.parent / 'share/verilator'
        if prefix.is_dir():
            env['VERILATOR_ROOT'] = str(prefix)
        executable = output / 'tb_features_sdp810'
        execute('digital_features_compile', [compiler, '--binary', '--timing', '-j', '2', '-Wno-fatal',
                '--top-module', 'tb_edge_features', '-GDIGITAL_PRESSURE=1', '--Mdir', output / 'obj',
                '-o', executable, *sources, benches[-1]], timeout=240, env=env)
        frames_path = output / 'frames_sdp810.hex'
        log, seconds = execute('digital_features_run', [executable, '+OUT=' + str(frames_path)], env=env, marker='ALL PASS')
        print(log.strip(), flush=True)

        import numpy as np
        sys.path.insert(0, str(SOC / 'src/features/tools'))
        from feature_reference import extract, process_convert
        sys.path.insert(0, str(EDGE / 'linux'))
        from cabinet.protocol import Frame, FrameGate
        rows = [[int(word, 16) for word in line.split()] for line in frames_path.read_text().splitlines()]
        if len(rows) != 3:
            raise AssertionError('Expected three independent overlapping digital-pressure frames')
        for index, row in enumerate(rows):
            if len(row) != 71:
                raise AssertionError('39D frame word count changed')
            frame = Frame.from_words(row[:32], row[32:])
            header = frame.header
            if header[18] != 2 or header[15] != 0x5000 or not 24 <= frame.pressure_count <= 26:
                raise AssertionError('Digital source, quality or independent pressure count mismatch')
            if not 12500 <= frame.adc_count <= 13000:
                raise AssertionError('ADC count incorrectly shares pressure count')
            phase = (np.arange(1024) + index * 512) % 40
            axis_x = np.where(phase < 20, 2048, -2048)
            axis_y = np.where((phase < 10) | (phase >= 30), 1024, -1024)
            axis_z = phase * 64 - 1248
            raw = np.array([axis_x, axis_y, axis_z, axis_x // 2, axis_y // 2, axis_z // 2])
            expected = extract(raw, process_convert(16400, 16410, 480, 20000, clk_hz=4000000))
            expected[37] = ((6000 * 65536 * 17896) >> 30) / 65536
            if not np.allclose(frame.values, expected, atol=0.0005, rtol=0.0003):
                raise AssertionError('Full 39D digital-pressure reference mismatch')
            contract = dict(feature_config_id=1, calibration_id=0, sample_mode_id=2)
            if FrameGate(contract).check(frame, header[4], diagnostic_test=True):
                raise AssertionError('Digital diagnostic frame rejected')
        report['tests'].append(dict(test='digital_39D_overlap_vs_numpy', status='PASS', frames=3, features_compared=117, seconds=seconds))
        save()
        print('Digital pressure / three overlapping 39D frames vs NumPy ALL PASS', flush=True)
        env = os.environ.copy()
        env['PYTHONPATH'] = str(EDGE / 'linux')
        execute('reader_profile_tests', [sys.executable, '-m', 'unittest', 'discover', '-s', EDGE / 'linux/tests',
                                        '-p', 'test_pressure_profile.py', '-v'], env=env, marker='OK')
        report['tests'].append(dict(test='reader_profile_tests', status='PASS'))
        changed = [path for path, digest in initial_hashes.items() if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]
        if changed:
            raise RuntimeError('Source changed during pressure regression: ' + str(changed))
        report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', reason=str(error))
        print('PRESSURE REGRESSION FAIL: ' + str(error), file=sys.stderr, flush=True)
    report['completed_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
