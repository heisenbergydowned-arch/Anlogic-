"""Authenticated UI bridge to the existing recorder owner, not another collector."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from hmi_daily.cabinet.learning_rpc import request
from hmi_daily.cabinet.learning_web import strict_json


DOWNLOAD_SLOT = threading.BoundedSemaphore(1)
FILES = ('session.json', 'feature_contract.json', 'frames.jsonl', 'summary.json')


class Export:
    def __init__(self, stream):
        self.stream = stream

    def __enter__(self):
        return self.stream

    def read(self, size=-1):
        return self.stream.read(size)

    def __exit__(self, *arguments):
        try:
            self.stream.close()
        finally:
            DOWNLOAD_SLOT.release()


def identity(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError('Canonical session UUID required')
    return value


def file_sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            result.update(block)
    return result.hexdigest()


def verified_session(directory, session_id):
    identity(session_id)
    root = Path(directory)
    folder = root / session_id
    if root.is_symlink() or folder.is_symlink() or not folder.is_dir():
        raise ValueError('Unknown regular session directory')
    paths = [folder / name for name in FILES]
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError('Incomplete or symlink recording')
    if sum(path.stat().st_size for path in paths) > 128 * 1024 * 1024:
        raise ValueError('Recording too large for web export; use reviewed SCP')
    if any((folder / name).stat().st_size > 65536 for name in FILES if name != 'frames.jsonl'):
        raise ValueError('Oversize recording metadata')
    documents = {name: strict_json((folder / name).read_bytes(), limit=65536) for name in FILES if name != 'frames.jsonl'}
    session, summary = documents['session.json'], documents['summary.json']
    if session.get('session_id') != session_id or summary.get('session_id') != session_id:
        raise ValueError('Recording identity mismatch')
    if summary.get('state') not in ('COMPLETED', 'DIAGNOSTIC_SAVED', 'ABORTED'):
        raise ValueError('Recording is not durably finalized')
    if not summary.get('durable_frames') or summary['durable_frames'] != summary.get('frames'):
        raise ValueError('No finalized recorded frames')
    expected = summary.get('files_sha256', {})
    if set(expected) != set(FILES) - {'summary.json'}:
        raise ValueError('Missing recorder checksum index')
    for name, checksum in expected.items():
        if type(checksum) is not str or not re.fullmatch('[0-9a-f]{64}', checksum) or file_sha(folder / name) != checksum:
            raise ValueError('Recorder checksum mismatch')
    return folder, session, summary


def status(service):
    recorder = getattr(service, 'recorder', None)
    if recorder is None:
        return dict(available=False, state='NOT_CONFIGURED', ready=False,
                    reason='Existing collector needs --capture-dir and --capture-contract; do not start a second live collector')
    return dict(recorder.snapshot(), available=True)


def command(service, operation, document):
    recorder = getattr(service, 'recorder', None)
    if recorder is None:
        raise ValueError('RECORDER_NOT_CONFIGURED')
    if operation not in ('start', 'stop') or set(document) != {'request_id', 'payload'}:
        raise ValueError('Invalid recording action')
    identity(document['request_id'])
    result = request(recorder.socket_path, dict(operation=operation, **document))
    if result.get('ok') is not True:
        raise ValueError(result.get('reason', 'Recorder refused request'))
    return result


def archive(service, session_id):
    recorder = getattr(service, 'recorder', None)
    if recorder is None or not DOWNLOAD_SLOT.acquire(False):
        raise OSError('Recorder unavailable or export already in progress')
    output = None
    try:
        folder, session, summary = verified_session(recorder.directory, session_id)
        if shutil.disk_usage(tempfile.gettempdir()).free < 160 * 1024 * 1024:
            raise OSError('Export temporary storage reserve')
        output = tempfile.TemporaryFile()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as package:
            for name in FILES:
                package.write(folder / name, session_id + '/' + name)
            export = dict(schema='cabinet-recording-download-v1', session_id=session_id,
                          capture_mode=session['capture_mode'], state=summary['state'],
                          label_reviewed=False, training_ready=False, controls_changed=False,
                          files_sha256={name: file_sha(folder / name) for name in FILES})
            package.writestr(session_id + '/download.json', json.dumps(export, allow_nan=False))
        output.seek(0, 2)
        size = output.tell()
        output.seek(0)
        return Export(output), size
    except BaseException:
        if output is not None:
            output.close()
        DOWNLOAD_SLOT.release()
        raise
