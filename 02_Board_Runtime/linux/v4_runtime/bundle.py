"""Pinned, indivisible model bundles and bit-defined PS preprocessing."""
from cabinet.input_policy import fault_policy, model_values, semantics, input_state
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from .profiles import validate_profile


LABELS = ['normal', 'imbalance', 'stall', 'clog', 'overheat']
FEATURES = ([kind+'_a_'+axis for kind in ('rms', 'pp', 'kurt') for axis in 'xyz']
            + ['banda'+str(index) for index in range(8)]
            + [kind+'_b_'+axis for kind in ('rms', 'pp', 'kurt') for axis in 'xyz']
            + ['bandb'+str(index) for index in range(8)] + ['ratio_ab', 'current', 'temp', 'pressure', 'rpm'])
UNITS = ['g']*6+['1']*11+['g']*6+['1']*12+['A', 'degC', 'kPa', 'RPM']
FILES = {'model_u8_io.onnx', 'normalization.json', 'feature_contract.json', 'label_map.json',
         'training_manifest.json', 'training_validation.json', 'runtime_golden.json'}
FEATURE_ID = 0x2026f400
EDGES = [1, 13, 39, 65, 103, 154, 205, 257, 513]
COEFFICIENT_SHA = 'ce82c6cf263aeaac69fd78fd68831f20b10d58269e8e02a0d22ba9e7814bf1bc'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: '+key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('Non-finite JSON constant: '+value)


def loads(data):
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=reject_constant)


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('A finite non-boolean number is required')
    return value


def fp32(value):
    try:
        result = struct.unpack('<f', struct.pack('<f', number(value)))[0]
    except (OverflowError, struct.error):
        raise ValueError('FP32 overflow')
    if not math.isfinite(result):
        raise ValueError('FP32 overflow')
    return result


class Rejected(ValueError):
    pass


class Bundle:
    def __init__(self, directory, manifest_sha256, allow_synthetic=False, qualification=None, reviewed_admission=None, graph_audit=None):
        self.directory = Path(directory).resolve()
        if not re.fullmatch('[0-9a-f]{64}', manifest_sha256):
            raise ValueError('An externally pinned manifest SHA-256 is required')
        self.manifest_sha256 = manifest_sha256
        manifest_bytes = self.read('runtime_manifest.json', 65536)
        if digest(manifest_bytes) != manifest_sha256:
            raise ValueError('Runtime manifest pin mismatch')
        self.manifest = loads(manifest_bytes.decode('utf-8'))
        manifest = self.manifest
        self.ps_softmax = manifest.get('schema') == 'cabinet-npu-runtime-v2'
        if manifest.get('schema') not in ('cabinet-npu-runtime-v1', 'cabinet-npu-runtime-v2') or manifest.get('mode') != 'SHADOW_ONLY' or manifest.get('qualified') is not False or manifest.get('hardware_verified') is not False:
            raise ValueError('This runtime cannot grant formal deployment qualification')
        if manifest.get('labels') != LABELS or manifest.get('units') != UNITS:
            raise ValueError('Label or unit order mismatch')
        if manifest.get('input_semantics') not in ('STANDARDIZED_PHYSICAL_39','STANDARDIZED_39_FG_UNKNOWN_V1') or (manifest.get('normalization_location'), manifest.get('quantization_rounding')) != ('PS_BEFORE_QUANTIZATION', 'FP32_TIES_TO_EVEN_NO_CLIP'):
            raise ValueError('Preprocessing contract mismatch')
        if (manifest.get('input_shape'), manifest.get('output_shape'), manifest.get('input_dtype'), manifest.get('output_dtype')) != (
                [1, 39], [1, 5], 'uint8', 'uint8'):
            raise ValueError('Tensor contract mismatch')
        expected_abi = 3 if self.ps_softmax else 2
        if any(type(value) is not int for key in ('input_shape', 'output_shape') for value in manifest[key]) or type(manifest.get('native_abi')) is not int or manifest['native_abi'] != expected_abi:
            raise ValueError('Native ABI/shape type mismatch')
        if self.ps_softmax:
            if manifest.get('execution_model') != 'ALNPU_LOGITS_PS_SOFTMAX':
                raise ValueError('Explicit NPU logits / PS Softmax declaration required')
        elif 'execution_model' in manifest:
            raise ValueError('Legacy bundles cannot claim the PS Softmax execution contract')
        self.hardware_profile = None
        self.policy = manifest.get('diagnostic_policy', {})
        if self.policy.get('qualified') is not False or self.policy.get('source') != 'ILLUSTRATIVE_NOT_CALIBRATED':
            raise ValueError('Unqualified shadow policy is required')
        if not 0 < number(self.policy.get('confidence_min')) <= 1 or not 0 <= number(self.policy.get('margin_min')) <= 1:
            raise ValueError('Invalid shadow confidence/margin')
        if manifest.get('source') not in ('SYNTHETIC_ONLY', 'SYNTHETIC_FIXTURE', 'REAL_FRM1_DECLARED'):
            raise ValueError('Unsupported model source')
        self.synthetic = manifest['source'] != 'REAL_FRM1_DECLARED'
        if self.synthetic and not allow_synthetic:
            raise ValueError('Explicit synthetic replay opt-in required')
        if type(manifest.get('model_id')) is not str or not re.fullmatch('[A-Za-z0-9_.-]{1,96}', manifest['model_id']):
            raise ValueError('Invalid model identity')
        hashes = manifest.get('artifacts_sha256')
        expected_files = FILES | {'model_logits_u8.onnx', 'postprocess.json'} if self.ps_softmax else FILES
        if type(hashes) is not dict or set(hashes) != expected_files:
            raise ValueError('Incomplete indivisible runtime bundle')
        self.data = {}
        for name, expected in hashes.items():
            data = self.read(name, 16*1024*1024)
            if digest(data) != expected:
                raise ValueError('Bundle artifact mismatch: '+name)
            self.data[name] = data
        self.contract = self.json('feature_contract.json')
        contract = self.contract
        fault_policy(contract)
        if manifest.get('input_semantics') != semantics(contract):raise ValueError('Model input policy/encoding mismatch')
        for key, expected in {'feature_config_id': FEATURE_ID, 'sample_mode_id': 2, 'profile': 'V4-P800-Q17',
                'coefficient_sha256': COEFFICIENT_SHA, 'fs': 4000, 'adc_fs': 50000,
                'fft_size': 1024, 'hop': 512, 'edges': EDGES, 'feature_names': FEATURES}.items():
            if contract.get(key) != expected or type(contract.get(key)) is not type(expected):
                raise ValueError('Feature contract mismatch: '+key)
        calibration = contract.get('calibration_id')
        if type(calibration) is not int or not 0 <= calibration <= 0xffffffff:
            raise ValueError('Calibration identity mismatch')
        if contract.get('qualified') is not False:
            raise ValueError('Feature contract cannot silently grant qualification')
        if self.json('label_map.json') != {str(index): label for index, label in enumerate(LABELS)}:
            raise ValueError('Label map mismatch')
        origin = self.json('training_manifest.json')
        if manifest.get('training_manifest_sha256') != digest(self.data['training_manifest.json']):
            raise ValueError('Training manifest provenance mismatch')
        training = self.json('training_validation.json')
        if training.get('status') not in ('PASS_SYNTHETIC_TRAIN_EXPORT_QUANTIZE_ONLY', 'PASS_IMPORTED_FRAME_TRAINING_ONLY') or training.get('qualified') is not False:
            raise ValueError('Training origin did not pass its host gates')
        if any(origin.get(key) != manifest.get(key) for key in ('model_id', 'source', 'labels', 'input_semantics', 'normalization_location')):
            raise ValueError('Training/runtime identity mismatch')
        if origin.get('qualified') is not False or origin.get('hardware_verified') is not False:
            raise ValueError('An unqualified training candidate is required')
        for name in ('model_u8_io.onnx', 'normalization.json', 'feature_contract.json', 'label_map.json'):
            if origin.get('artifacts_sha256', {}).get(name) != hashes[name]:
                raise ValueError('Artifact separated from its training origin: '+name)
        self.norm = self.json('normalization.json')
        if self.norm.get('feature_names') != FEATURES or self.norm.get('location') != 'PS_BEFORE_QUANTIZATION' or self.norm.get('training_split_only') is not True:
            raise ValueError('Frozen normalization contract mismatch')
        self.mean = self.vector(self.norm.get('mean'))
        self.scale = self.vector(self.norm.get('scale'))
        if any(value <= 0 for value in self.scale):
            raise ValueError('Normalization scale must be positive')
        self.constants = self.norm.get('constant_features')
        if type(self.constants) is not list or len(set(self.constants)) != len(self.constants) or any(type(index) is not int or not 0 <= index < 39 for index in self.constants):
            raise ValueError('Invalid constant-feature indices')
        quant = manifest.get('io_quantization', {})
        if quant != origin.get('io_quantization'):
            raise ValueError('Quantization separated from training origin')
        self.input_scale = fp32(quant.get('input_scale'))
        self.output_scale = fp32(quant.get('output_scale'))
        self.input_zero = quant.get('input_zero_point')
        self.output_zero = quant.get('output_zero_point')
        if self.input_scale <= 0 or self.output_scale <= 0 or any(type(value) is not int or not 0 <= value <= 255 for value in (self.input_zero, self.output_zero)):
            raise ValueError('Invalid per-tensor UINT8 quantization')
        if self.output_zero != 0 or not math.isclose(self.output_scale, 1/255, rel_tol=1e-6):
            raise ValueError('This probability contract requires UINT8 scale 1/255, zero 0')
        self.postprocess = None
        if self.ps_softmax:
            postprocess = self.json('postprocess.json')
            expected = dict(schema='cabinet-ps-softmax-v1', execution_model='ALNPU_LOGITS_PS_SOFTMAX',
                            algorithm='FP32_STABLE_SOFTMAX_TIES_TO_EVEN_V1', axis=1,
                            logits_shape=[1, 5], logits_dtype='uint8',
                            probability_shape=[1, 5], probability_dtype='uint8',
                            reference_model_sha256=hashes['model_u8_io.onnx'],
                            logits_model_sha256=hashes['model_logits_u8.onnx'])
            if type(postprocess) is not dict or set(postprocess) != set(expected) | {'logits_scale', 'logits_zero_point'}:
                raise ValueError('Incomplete PS Softmax contract')
            if any(type(postprocess[key]) is not type(value) or postprocess[key] != value for key, value in expected.items()):
                raise ValueError('PS Softmax semantics or graph binding mismatch')
            if any(type(value) is not int for value in postprocess['logits_shape'] + postprocess['probability_shape']):
                raise ValueError('PS Softmax shape types must be integers')
            self.logits_scale = fp32(postprocess['logits_scale'])
            self.logits_zero = postprocess['logits_zero_point']
            if self.logits_scale <= 0 or type(self.logits_zero) is not int or not 0 <= self.logits_zero <= 255:
                raise ValueError('Invalid logits quantization')
            self.postprocess = postprocess
        self.admission = None
        admission = qualification or reviewed_admission
        reviewed_sha = None
        if graph_audit:
            from .qualification import pinned_json
            graph = pinned_json(graph_audit['path'], graph_audit['sha256'])
            if graph.get('schema') != 'cabinet-candidate-graph-v1' or graph.get('hardware_profile') != manifest.get('hardware_profile') or graph.get('model_sha256') != hashes.get('model_logits_u8.onnx') or graph.get('dimensions') != [[39, 32], [32, 16], [16, 5]] or graph.get('transB') != [1, 1, 1] or graph.get('forbidden_ops') != [] or graph.get('qualified') is not False:
                raise ValueError('Pinned candidate graph scope mismatch')
            reviewed_sha = graph['model_sha256']
        if admission:
            if training.get('status') != 'PASS_IMPORTED_FRAME_TRAINING_ONLY':
                raise ValueError('Formal admission requires real imported-frame training provenance')
            from .qualification import validate_evidence
            evidence = validate_evidence(admission['directory'], admission['sha256'],
                dict(self.manifest, _pin=self.manifest_sha256), self.contract)
            reviewed_sha = evidence['model_sha256']
        self.hardware_profile = validate_profile(manifest, reviewed_sha)
        if qualification:
            from .qualification import Admission
            self.admission = Admission(self, qualification)
            self.policy = self.admission.evidence['policy']

    def read(self, name, limit):
        file = self.directory/name
        if Path(name).name != name or file.is_symlink() or not file.is_file() or file.stat().st_size > limit:
            raise ValueError('Unsafe, oversized or missing bundle artifact: '+name)
        with file.open('rb') as source:
            data = source.read(limit+1)
        if len(data) > limit:
            raise ValueError('Artifact grew beyond its read limit')
        return data

    def json(self, name):
        return loads(self.data[name].decode('utf-8'))

    @staticmethod
    def vector(values):
        if type(values) is not list or len(values) != 39:
            raise ValueError('Exactly 39 physical values required')
        return tuple(fp32(value) for value in values)

    def encode(self, values):
        values = self.vector(values)
        standardized, encoded = [], []
        for index, value in enumerate(values):
            if index in self.constants and abs(value-self.mean[index]) > 1/65536:
                raise Rejected('CONSTANT_FEATURE_CHANGED')
            normalized = fp32(fp32(value-self.mean[index])/self.scale[index])
            quantized = round(fp32(fp32(normalized/self.input_scale)+self.input_zero))
            if not 0 <= quantized <= 255:
                raise Rejected('QUANTIZATION_INPUT_RANGE')
            standardized.append(normalized)
            encoded.append(quantized)
        return standardized, encoded

    def decode(self, output):
        if type(output) is not list or len(output) != 5 or any(type(value) is not int or not 0 <= value <= 255 for value in output):
            raise ValueError('Native output must be exactly five UINT8 values')
        probabilities = [fp32((value-self.output_zero)*self.output_scale) for value in output]
        if any(not 0 <= value <= 1+1e-7 for value in probabilities) or abs(sum(probabilities)-1) > 5/255:
            raise ValueError('Invalid native class probabilities')
        return probabilities
