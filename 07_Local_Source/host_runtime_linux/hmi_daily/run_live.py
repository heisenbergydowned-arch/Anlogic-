"""Exclusive display/reader supervisor; restores the previous tty mode on exit."""
import sys
# Match the immutable source inventory even with historical service units.
sys.dont_write_bytecode = True
import fcntl
import argparse
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge-config', type=Path, default=root.parent / 'config.example.json')
    parser.add_argument('--managed-collector', action='store_true')
    args = parser.parse_args()
    collector = root.parent / 'run_edge.py'
    if args.managed_collector and not collector.is_file():
        raise RuntimeError('Install the complete Linux source tree; no standalone reader fallback is allowed')
    children = []
    stopping = [False]

    def stop(number, frame):
        stopping[0] = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with open('/run/cabinet-live-supervisor.lock', 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                executable = os.readlink(str(entry / 'exe'))
            except OSError:
                continue
            if executable.endswith(('/lvgl_widgets', '/lvgl_bench', '/lvgl_demo', '/lvgl_fps', '/cabinet_dashboard')):
                raise RuntimeError('Another framebuffer application is active: ' + executable)
        terminal = os.open('/dev/tty1', os.O_RDWR | os.O_NOCTTY)
        mode = bytearray(4)
        fcntl.ioctl(terminal, 0x4b3b, mode, True)
        old_mode = struct.unpack('I', mode)[0]
        output = Path('/run/cabinet-live')
        output.mkdir(exist_ok=True)
        try:
            if args.managed_collector:
                children.append(subprocess.Popen([sys.executable, str(collector), '--live', '--no-http', '--local-display',
                                                  '--config', str(args.edge_config), '--learning-config', str(root / 'learning_config.json'),
                                                  '--learning-db', str(root / 'data/baselines.sqlite3')], cwd=str(root.parent)))
            env=dict(os.environ)
            config_path=Path(env.get('CABINET_CONFIG',str(args.edge_config)))
            configuration=json.loads(config_path.read_text())
            socket=configuration.get('parameter_control',{}).get('local_socket')
            if socket:env['CABINET_OPERATOR_SOCKET']=socket
            else:env.pop('CABINET_OPERATOR_SOCKET',None)
            children.append(subprocess.Popen([str(root / 'cabinet_dashboard')], cwd=str(root),env=env))
            while not stopping[0]:
                for child in children:
                    result = child.poll()
                    if result is not None:
                        if args.managed_collector and child is children[0] and children[-1].poll() is None:
                            time.sleep(2.1)
                        raise RuntimeError('Display/reader process exited with code %d' % result)
                time.sleep(0.2)
            return 0
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
            for child in children:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            fcntl.ioctl(terminal, 0x4b3a, old_mode)
            os.close(terminal)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
