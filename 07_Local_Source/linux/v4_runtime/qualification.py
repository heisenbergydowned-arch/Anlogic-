"""Detached, externally pinned admission; training candidates remain immutable."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
from .profiles import PL_BUILD_ID


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def pinned_json(path, pin=None):
    from .bundle import loads
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16777216:
        raise ValueError('Unsafe qualification evidence')
    with path.open('rb') as stream:
        data = stream.read(16777217)
    if len(data) > 16777216:
        raise ValueError('Oversized qualification evidence')
    if pin is not None and (not re.fullmatch('[a-f0-9]{64}', str(pin)) or checksum(data) != pin):
        raise ValueError('Qualification evidence pin mismatch')
    return loads(data.decode())


def validate_evidence(directory, pin, manifest, contract, library_sha256=None):
    from .bundle import LABELS
    directory = Path(directory)
    receipt = pinned_json(directory / 'release.json', pin)
    if receipt.get('schema') != 'cabinet-model-admission-v1':
        raise ValueError('Unknown admission schema')
    expected = dict(model_id=manifest['model_id'], bundle_manifest_sha256=manifest['_pin'],
                    hardware_profile=manifest['hardware_profile'], pl_build_id=PL_BUILD_ID)
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError('Admission model/profile identity mismatch')
    if manifest.get('source') != 'REAL_FRM1_DECLARED' or not contract.get('calibration_id'):
        raise ValueError('Synthetic or uncalibrated models cannot be admitted')
    evidence = {}
    hashes = receipt.get('evidence_sha256', {})
    if set(hashes) != {'dataset.json', 'predictions.json', 'graph.json', 'target.json'}:
        raise ValueError('Complete independent evidence required')
    for name, expected_hash in hashes.items():
        evidence[name] = pinned_json(directory / name, expected_hash)
    dataset = evidence['dataset.json']
    train, test = dataset.get('train_sessions'), dataset.get('test_sessions')
    if dataset.get('source') != 'REAL_FRM1_DECLARED' or dataset.get('calibration_id') != contract['calibration_id']:
        raise ValueError('Real data provenance/calibration mismatch')
    if not isinstance(train, list) or not isinstance(test, list) or not train or not test:
        raise ValueError('Session-disjoint train/test split required')
    if any(type(value) is not str or not re.fullmatch('[a-f0-9]{64}', value) for value in train + test):
        raise ValueError('Session artifact SHA256 identities required')
    if len(set(train + test)) != len(train + test):
        raise ValueError('Duplicate or overlapping train/test sessions')
    predictions = evidence['predictions.json']
    if type(predictions) is not list or not 100 <= len(predictions) <= 100000:
        raise ValueError('Independent labeled evaluation required')
    confusion = [[0] * 5 for unused in range(5)]
    identities = set()
    for row in predictions:
        if type(row) is not dict or not re.fullmatch('[a-f0-9]{64}', str(row.get('sample_sha256',''))) or row['sample_sha256'] in identities:
            raise ValueError('Unique held-out sample artifact identities required')
        identities.add(row['sample_sha256'])
        if row.get('session_sha256') not in test or row.get('test') is not False:
            raise ValueError('Non-holdout or TEST evaluation row')
        if row.get('actual') not in LABELS or row.get('predicted') not in LABELS:
            raise ValueError('Unknown diagnosis label')
        confusion[LABELS.index(row['actual'])][LABELS.index(row['predicted'])] += 1
    if any(sum(row) < 20 for row in confusion):
        raise ValueError('At least twenty held-out examples per class required')
    accuracy = sum(confusion[index][index] for index in range(5)) / len(predictions)
    minimum = receipt.get('minimum_accuracy', 0.95)
    if type(minimum) not in (float, int) or not math.isfinite(minimum) or not 0.95 <= minimum <= 1 or accuracy < minimum:
        raise ValueError('Independent classification accuracy gate failed')
    graph = evidence['graph.json']
    model_sha = manifest['artifacts_sha256']['model_logits_u8.onnx']
    if (graph.get('model_sha256'), graph.get('dimensions'), graph.get('transB'), graph.get('forbidden_ops')) != (
            model_sha, [[39, 32], [32, 16], [16, 5]], [1, 1, 1], []):
        raise ValueError('SDK-compatible classifier audit required')
    target = evidence['target.json']
    required = dict(backend='Alnpu', hardware_executed=True, pl_build_id=PL_BUILD_ID,
                    model_sha256=model_sha, hardware_profile=manifest['hardware_profile'])
    if any(type(target.get(key)) is not type(value) or target[key] != value for key, value in required.items()):
        raise ValueError('Actual matching Alnpu execution evidence required')
    if any(not re.fullmatch('[a-f0-9]{64}', str(target.get(key, ''))) for key in ('library_sha256', 'sdk_sha256')):
        raise ValueError('SDK and native adapter identities required')
    if library_sha256 is not None and target['library_sha256'] != library_sha256:
        raise ValueError('Executing native library differs from admission')
    if (type(target.get('cases')) is not int or target['cases'] < 40 or
            type(target.get('class_agreement')) not in (int, float) or target['class_agreement'] != 1):
        raise ValueError('Insufficient target golden coverage')
    if type(target.get('max_probability_lsb_error')) is not int or not 0 <= target['max_probability_lsb_error'] <= 1:
        raise ValueError('Target probability error exceeds gate')
    if type(target.get('p99_ms')) not in (float, int) or not math.isfinite(target['p99_ms']) or target['p99_ms'] <= 0:
        raise ValueError('Actual inference latency required')
    policy = receipt.get('diagnostic_policy', {})
    if set(policy) != {'confidence_min', 'margin_min'} or any(type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 1 for value in policy.values()):
        raise ValueError('Reviewed formal diagnostic policy required')
    return dict(receipt=receipt, accuracy=accuracy, confusion=confusion, model_sha256=model_sha,
                library_sha256=target['library_sha256'], policy=policy)


class Admission:
    def __init__(self, bundle, config):
        if type(config) is not dict or set(config) != {'directory', 'sha256', 'registry'}:
            raise ValueError('Externally pinned release and registry required')
        self.config = dict(config)
        self.bundle = bundle
        manifest = dict(bundle.manifest, _pin=bundle.manifest_sha256)
        self.evidence = validate_evidence(config['directory'], config['sha256'], manifest, bundle.contract)
        self.active = self.check_active()

    def check_active(self):
        registry = Path(self.config['registry'])
        if registry.is_symlink() or registry.stat().st_uid != os.geteuid() or registry.stat().st_mode & 0o022:
            raise ValueError('Private release registry ownership required')
        active = pinned_json(registry / 'active.json')
        if active.get('state') != 'ACTIVE' or active.get('receipt_sha256') != self.config['sha256']:
            raise ValueError('Model release revoked, rolled back or not active')
        if type(active.get('generation')) is not int or active['generation'] < 1:
            raise ValueError('Invalid deployment generation')
        return active

    def assert_current(self, library_sha256=None):
        if self.check_active() != self.active:
            raise ValueError('Active deployment changed; controlled restart required')
        pinned_json(Path(self.config['directory']) / 'release.json', self.config['sha256'])
        if library_sha256 is not None and library_sha256 != self.evidence['library_sha256']:
            raise ValueError('Executing native library differs from admission')
        return self.config['sha256']
