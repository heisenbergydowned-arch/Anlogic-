"""Root/local-owner Unix RPC; commands are executed by the sole frame collector."""
import json
import os
from pathlib import Path
import queue
import socket
import struct
import threading
import time

from .learning_web import strict_json
from .baseline import LearningOwnershipError


class LearningRPC:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        if os.path.lexists(str(self.path)):
            raise LearningOwnershipError('Learning socket already exists; inspect the collector owner before recovery')
        self.queue = queue.Queue(maxsize=8)
        self.stopping = threading.Event()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.path))
        info = self.path.lstat()
        self.socket_identity = info.st_dev, info.st_ino
        self.path.chmod(0o600)
        self.listener.listen(4)
        self.listener.settimeout(0.2)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.stopping.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(0.5)
                try:
                    if hasattr(socket, 'SO_PEERCRED'):
                        _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid != os.geteuid():
                            raise ValueError('LOCAL_OWNER_REQUIRED')
                    payload = bytearray()
                    deadline = time.monotonic() + 0.5
                    while b'\n' not in payload:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ValueError('REQUEST_TIMEOUT')
                        connection.settimeout(remaining)
                        part = connection.recv(1024)
                        if not part or len(payload) + len(part) > 4096:
                            raise ValueError('INVALID_REQUEST_SIZE')
                        payload.extend(part)
                    line, trailing = bytes(payload).split(b'\n', 1)
                    if trailing.strip():
                        raise ValueError('ONE_REQUEST_PER_CONNECTION')
                    request = strict_json(line)
                    if not isinstance(request, dict):
                        raise ValueError('INVALID_REQUEST')
                    complete = threading.Event()
                    result = {}
                    self.queue.put_nowait((request, result, complete, time.monotonic() + 0.75))
                    if not complete.wait(2.0):
                        response = {'ok': False, 'reason': 'COLLECTOR_TIMEOUT'}
                    else:
                        response = result
                except (ValueError, OSError, queue.Full, RecursionError):
                    response = {'ok': False, 'reason': 'RPC_REJECTED'}
                try:
                    connection.sendall((json.dumps(response, allow_nan=False) + '\n').encode('utf-8'))
                except OSError:
                    pass

    def poll(self, learner, now, web_control=None):
        started = time.monotonic()
        for _ in range(8):
            try:
                request, result, complete, deadline = self.queue.get_nowait()
            except queue.Empty:
                break
            try:
                if time.monotonic() > deadline:
                    result.update(ok=False, reason='REQUEST_EXPIRED')
                elif 'schema' in request or 'view' in request:
                    if web_control is None:
                        result.update(ok=False, reason='WEB_SERVICE_UNAVAILABLE')
                    elif 'schema' in request:
                        result.update(web_control.execute(request, now + time.monotonic() - started))
                    else:
                        result.update(web_control.query(request, now + time.monotonic() - started))
                elif web_control is not None and request.get('operation') != 'status':
                    result.update(ok=False, reason='LOCAL_MUTATION_DISABLED_USE_WEB')
                else:
                    result.update(learner.command(request, now + time.monotonic() - started))
            except (ValueError, OSError) as error:
                result.update(ok=False, reason='REQUEST_REJECTED', detail=str(error)[:160])
            finally:
                complete.set()

    def close(self):
        self.stopping.set()
        self.listener.close()
        self.thread.join(timeout=2.5)
        if self.thread.is_alive():
            raise RuntimeError('Learning RPC owner failed to stop; keep the socket for inspection')
        try:
            info = self.path.lstat()
            if (info.st_dev, info.st_ino) == self.socket_identity:
                self.path.unlink()
        except FileNotFoundError:
            pass


def request(path, payload):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3.0)
        connection.connect(str(path))
        connection.sendall((json.dumps(payload, allow_nan=False) + '\n').encode('utf-8'))
        response = bytearray()
        while b'\n' not in response:
            part = connection.recv(2048)
            if not part or len(response) + len(part) > 65536:
                raise RuntimeError('Invalid learning RPC response')
            response.extend(part)
        return strict_json(bytes(response).split(b'\n', 1)[0], limit=65536)
