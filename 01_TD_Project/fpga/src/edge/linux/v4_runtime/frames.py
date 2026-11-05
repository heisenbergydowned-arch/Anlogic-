"""Frame provenance, generation and sequence gates for local shadow inference."""
import math
import re
import struct
import time

from cabinet.protocol import Frame, FrameGate
from .bundle import digest


def uint32(value):
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError('Expected uint32 frame identity')
    return value


def identity(value):
    if type(value) is not str or not re.fullmatch('[A-Za-z0-9_./:-]{1,160}', value):
        raise ValueError('Invalid session/request/boot identity')
    return value


def binding(request):
    header, words = request['header'], request['feature_words']
    return dict(request_id=request['request_id'], session_id=request['session_id'], boot_id=request['boot_id'],
                generation=request['generation'], frame_id=header[3], frame_end_ms=header[4],
                feature_config_id=header[16], calibration_id=header[17], sample_mode_id=header[18],
                model_id=request['model_id'], bundle_manifest_sha256=request['bundle_manifest_sha256'],
                input_sha256=digest(struct.pack('<71I', *(header+words))))


class FrameValidator:
    def __init__(self, bundle, max_sessions=64):
        self.bundle, self.max_sessions = bundle, max_sessions
        self.sessions = {}

    def check(self, request):
        if type(request) is not dict or request.get('schema') != 'cabinet-npu-request-v4':
            raise ValueError('Unknown request schema')
        for key in ('session_id', 'request_id', 'boot_id'):
            identity(request.get(key))
        generation = uint32(request.get('generation'))
        if request.get('model_id') != self.bundle.manifest['model_id'] or request.get('bundle_manifest_sha256') != self.bundle.manifest_sha256:
            raise ValueError('Model/bundle identity mismatch')
        sent = request.get('sent_monotonic')
        if type(sent) not in (int, float) or not math.isfinite(sent) or not -0.005 <= time.monotonic()-sent <= 1:
            raise ValueError('Expired local IPC request')
        now_ms = uint32(request.get('now_ms'))
        if type(request.get('header')) is not list or type(request.get('feature_words')) is not list:
            raise ValueError('Original FRM1 words are required')
        frame = Frame.from_words(request['header'], request['feature_words'])
        contract = self.bundle.contract
        if frame.header[17] != contract['calibration_id']:
            raise ValueError('Calibration identity mismatch')
        if frame.header[19] != 3:
            raise ValueError('Only stable RUN windows may enter this model')
        if frame.header[26] not in self.bundle.manifest['compatible_pl_build_ids']:
            raise ValueError('PL build identity mismatch')
        if frame.header[20] != contract['fs'] or frame.header[22] != contract['adc_fs']:
            raise ValueError('Declared vibration/ADC sample-rate contract mismatch')
        if self.bundle.synthetic:
            if not frame.test or frame.quality & ~0x5000:
                raise ValueError('Synthetic candidate requires explicit TEST replay, not real frames')
        elif frame.test:
            raise ValueError('Real shadow model refuses TEST frames')
        session = self.sessions.get(request['session_id'])
        if session is None:
            if len(self.sessions) >= self.max_sessions:
                raise ValueError('Session capacity reached; inspect collector restarts')
            session = dict(generation=generation, boot_id=request['boot_id'], gate=FrameGate(contract))
            self.sessions[request['session_id']] = session
        elif generation < session['generation']:
            raise ValueError('Old collector generation')
        elif generation == session['generation'] and request['boot_id'] != session['boot_id']:
            raise ValueError('Boot changed without collector generation change')
        elif generation > session['generation']:
            session.update(generation=generation, boot_id=request['boot_id'], gate=FrameGate(contract))
        reasons = session['gate'].check(frame, now_ms, diagnostic_test=self.bundle.synthetic)
        if reasons:
            raise ValueError('Frame rejected: '+','.join(reasons))
        return frame, binding(request)


def synthetic_frame(values, sequence, end_ms, contract, build_id=0x202610f4):
    header = [0]*32
    header[:5] = [0x46524d31, 0x10000, 284, sequence, end_ms]
    header[9:13] = [25575000, 25575000, 1024, 1024]
    header[13:22] = [(25<<16)|12800, 128, 0x5000, contract['feature_config_id'],
                     contract['calibration_id'], 2, 3, 0, 100000000]
    header[26:28] = [uint32(build_id), 1]
    header[20], header[22] = 4000, 50000
    words = list(struct.unpack('<39I', struct.pack('<39f', *values)))
    return Frame.from_words(header, words)
