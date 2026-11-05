"""Collector-side v4 model adapter; results cannot become formal control evidence."""
from cabinet.input_policy import fault_policy, model_values, semantics, input_state
import math
import socket
import struct
import time
import uuid

from .bundle import Bundle, LABELS, loads
from .frames import binding


class V4Model:
    def __init__(self, config):
        self.config = config
        qualification = config.get('qualification')
        if not qualification and (config.get('qualified') is not False or config.get('evidence') is not None):
            raise ValueError('v4 candidate integration is shadow-only, never qualified')
        self.bundle = Bundle(config['bundle'], config['bundle_manifest_sha256'], config.get('allow_synthetic_replay') is True,
                             qualification=qualification, graph_audit=config.get('graph_audit'))
        if qualification and (config.get('qualified') is not True or config.get('evidence') != qualification['sha256'] or
                              config.get('allow_synthetic_replay') is True):
            raise ValueError('Formal deployment must bind admission and prohibit replay')
        if config['model_id'] != self.bundle.manifest['model_id']:
            raise ValueError('Configured model identity mismatch')
        self.timeout = config.get('timeout_ms', 200)/1000
        if type(config.get('timeout_ms', 200)) is not int or not 0.001 <= self.timeout <= 5:
            raise ValueError('Invalid model deadline')

    def request(self, frame, context):
        if type(context) is not dict:
            raise ValueError('Collector session/boot/generation context required')
        received = context.get('received_at')
        if type(received) not in (float, int) or not math.isfinite(received) or not 0 <= time.monotonic()-received <= 0.5:
            raise ValueError('Stale collector queue entry')
        values = self.bundle.vector(list(frame.values))
        words = list(struct.unpack('<39I', struct.pack('<39f', *values)))
        age = round((time.monotonic()-received)*1000)
        return dict(schema='cabinet-npu-request-v4', request_id=uuid.uuid4().hex,
                    session_id=context['session_id'], boot_id=context['boot_id'], generation=context['generation'],
                    sent_monotonic=time.monotonic(), now_ms=(context['now_ms']+age) & 0xffffffff,
                    model_id=self.config['model_id'], bundle_manifest_sha256=self.bundle.manifest_sha256,
                    header=list(frame.header), feature_words=words)

    def infer(self, frame, context):
        started = time.monotonic()
        request = self.request(frame, context)
        import json
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(self.timeout)
            peer.connect(self.config['socket'])
            peer.sendall(json.dumps(request, allow_nan=False).encode()+b'\n')
            data = b''
            while b'\n' not in data:
                left = self.timeout-(time.monotonic()-started)
                if left <= 0:
                    raise TimeoutError('v4 model deadline')
                peer.settimeout(left)
                part = peer.recv(4096)
                if not part:
                    raise ConnectionError('v4 daemon closed before reply')
                data += part
                if len(data) > 65536:
                    raise ValueError('Oversized model reply')
            line, trailing = data.split(b'\n', 1)
            if trailing.strip():
                raise ValueError('Unexpected second model reply')
            reply = loads(line.decode('utf-8'))
        return self.validate_reply(reply, request, (time.monotonic()-started)*1000)

    def validate_reply(self, reply, request, elapsed_ms):
        if type(reply) is not dict:
            raise ValueError('Invalid model reply')
        if 'error' in reply:
            raise RuntimeError(str(reply['error']))
        if elapsed_ms > self.timeout*1000:
            raise TimeoutError('v4 model result expired')
        expected = binding(request)
        if any(type(reply.get(key)) is not type(value) or reply[key] != value for key, value in expected.items()):
            raise ValueError('Result frame/session/generation/bundle binding mismatch')
        formal = bool(self.bundle.admission)
        if formal:
            pin = self.bundle.admission.assert_current()
            if reply.get('admission_sha256') != pin or reply.get('backend') != 'Alnpu':
                raise ValueError('Formal reply is not bound to active Alnpu admission')
        if (reply.get('schema'), reply.get('mode'), reply.get('formal'), reply.get('qualified'), reply.get('test_backend')) != (
                'cabinet-npu-result-v4', 'FORMAL_DIAGNOSTIC' if formal else 'SHADOW_ONLY', formal, formal, not formal):
            raise ValueError('Unsafe model result qualification')
        if type(reply.get('formal')) is not bool or type(reply.get('qualified')) is not bool or type(reply.get('test_backend')) is not bool:
            raise ValueError('Result qualification must use exact booleans')
        if reply.get('backend') not in ('Alnpu', 'ORT_CPU_REFERENCE'):
            raise ValueError('Unknown or fallback backend')
        if reply.get('backend') != 'Alnpu' and self.config.get('allow_synthetic_replay') is not True:
            raise ValueError('CPU reference results require explicit replay opt-in')
        if self.bundle.hardware_profile and reply.get('hardware_profile') != self.bundle.hardware_profile:
            raise ValueError('Result hardware profile mismatch')
        if self.bundle.ps_softmax and (reply.get('execution_model') != self.bundle.manifest['execution_model'] or reply.get('postprocess') != self.bundle.postprocess['algorithm']):
            raise ValueError('Missing explicit PS Softmax execution identity')
        if type(reply.get('daemon_instance')) is not str or len(reply['daemon_instance']) != 32:
            raise ValueError('Missing daemon instance identity')
        values = struct.unpack('<39f', struct.pack('<39I', *request['feature_words']))
        from cabinet.protocol import Frame
        original = Frame.from_words(request['header'], request['feature_words'])
        unused, encoded = self.bundle.encode(model_values(original, self.bundle.contract))
        if reply.get('input_u8') != encoded:
            raise ValueError('PS preprocessing/quantization mismatch')
        probabilities = self.bundle.decode(reply.get('output_u8'))
        raw = reply.get('probabilities')
        if type(raw) is not list or len(raw) != 5 or any(type(value) not in (float, int) or not math.isfinite(value) or abs(value-expected_value) > 1e-7 for value, expected_value in zip(raw, probabilities)):
            raise ValueError('Probability/UINT8 output mismatch')
        order = sorted(range(5), key=probabilities.__getitem__, reverse=True)
        index, runner_up = order[:2]
        state = 'FORMAL_OBSERVATION' if formal else 'SHADOW_OBSERVATION'
        if probabilities[index] < self.bundle.policy['confidence_min']:
            state = 'REJECTED_CONFIDENCE'
        elif probabilities[index]-probabilities[runner_up] < self.bundle.policy['margin_min']:
            state = 'REJECTED_MARGIN'
        result = dict(expected, backend=reply['backend'], label=LABELS[index], label_id=index,
                    probabilities=probabilities, confidence=probabilities[index], diagnostic_state=state,
                    inference_ms=elapsed_ms, preprocess_ms=reply.get('preprocess_ms'), execute_ms=reply.get('execute_ms'),
                    test=not formal, formal=formal, qualified=formal, policy_qualified=formal)
        result.update(input_state(original, self.bundle.contract))
        if formal:
            result['admission_sha256'] = pin
        if self.bundle.ps_softmax:
            result.update(execution_model=reply['execution_model'], postprocess=reply['postprocess'])
        if self.bundle.hardware_profile:
            result['hardware_profile'] = self.bundle.hardware_profile
        return result
