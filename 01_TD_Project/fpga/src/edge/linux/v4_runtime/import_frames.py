"""Offline reviewed FRM1 import with explicit fixture provenance and group isolation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from collections import Counter

import numpy as np

from cabinet.protocol import FEATURES as PROTOCOL_FEATURES, Frame, FrameGate
from .bundle import FEATURES, LABELS, COEFFICIENT_SHA, EDGES, FEATURE_ID, digest, loads
from .frames import identity


def validate_contract(contract, fixture):
    for key, value in dict(feature_config_id=FEATURE_ID, sample_mode_id=2, profile='V4-P800-Q17',
            coefficient_sha256=COEFFICIENT_SHA, fs=4000, adc_fs=50000, fft_size=1024, hop=512,
            edges=EDGES, feature_names=FEATURES).items():
        if contract.get(key) != value or type(contract.get(key)) is not type(value):
            raise ValueError('Import contract mismatch: '+key)
    calibration = contract.get('calibration_id')
    if type(calibration) is not int or not 0 <= calibration <= 0xffffffff or (not fixture and calibration == 0):
        raise ValueError('Real import requires a commissioned nonzero calibration identity')
    if contract.get('qualified') is not False or list(PROTOCOL_FEATURES) != FEATURES:
        raise ValueError('Import cannot grant qualification or change feature order')
    build_id = contract.get('pl_build_id')
    if type(build_id) is not int or build_id not in (0x202610f4, 0x202610f5, 0x202610f6, 0x202610f7):
        raise ValueError('Import requires the exact reviewed PL build identity')


def save(file, value):
    file.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def import_records(file, contract_file, output, fixture=False, max_rows=100000):
    file, output = Path(file), Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh dataset directory required')
    contract_bytes = Path(contract_file).read_bytes()
    contract = loads(contract_bytes.decode('utf-8'))
    validate_contract(contract, fixture)
    source = 'SYNTHETIC_FIXTURE' if fixture else 'REAL_FRM1_DECLARED'
    rows = {name: [] for name in ('train', 'validation', 'test')}
    labels = {name: [] for name in rows}
    sessions = {name: [] for name in rows}
    groups, episodes, gates, metadata, rejected = {}, {}, {}, {}, []
    hasher = hashlib.sha256()
    with file.open('rb') as stream:
        for number in range(1, max_rows+2):
            line = stream.readline(65537)
            if not line:
                break
            if number > max_rows or len(line) > 65536:
                raise ValueError('Import row/line bound exceeded')
            hasher.update(line)
            record = loads(line.decode('utf-8'))
            if type(record) is not dict or record.get('schema') != 'cabinet-labelled-frame-v1' or record.get('source') != source:
                raise ValueError('Unknown source/schema; fixture and real records cannot be mixed')
            split, label = record.get('split'), record.get('label')
            if split not in rows or label not in LABELS:
                raise ValueError('Explicit frozen split and known label required')
            names = [identity(record.get(key)) for key in ('device_id', 'installation_id', 'session_id', 'boot_id', 'fault_episode_id')]
            group = tuple(names[:3])
            episode = tuple(names[:2]+[names[4]])
            if groups.setdefault(group, split) != split or episodes.setdefault(episode, split) != split:
                raise ValueError('Session/installation fault episode leaked across splits')
            if fixture:
                if record.get('label_source') != 'SIMULATOR' or record.get('label_reviewed') is not False:
                    raise ValueError('Fixtures may not pretend to have reviewed real labels')
            else:
                if record.get('label_source') != 'BENCH_REVIEWED' or record.get('label_reviewed') is not True:
                    raise ValueError('Real labels require independent bench review')
                identity(record.get('reviewer'))
                for key in ('label_evidence_sha256', 'calibration_evidence_sha256', 'bitstream_sha256'):
                    if type(record.get(key)) is not str or not re.fullmatch('[0-9a-f]{64}', record[key]):
                        raise ValueError('Missing provenance hash: '+key)
            frame = Frame.from_words(record['header'], record['feature_words'])
            now_ms = record.get('now_ms')
            if type(now_ms) is not int or not 0 <= now_ms <= 0xffffffff:
                raise ValueError('Original PL-relative receipt time required')
            key = tuple(names[:4])
            gate = gates.setdefault(key, FrameGate(contract))
            reasons = gate.check(frame, now_ms, diagnostic_test=fixture)
            if frame.header[17] != contract['calibration_id']:
                reasons.append('calibration_identity')
            if frame.header[19] != 3:
                reasons.append('not_stable_run')
            if frame.header[26] != contract['pl_build_id']:
                reasons.append('pl_build_identity')
            if frame.header[20] != contract['fs'] or frame.header[22] != contract['adc_fs']:
                reasons.append('declared_sample_rate')
            if fixture and (not frame.test or frame.quality & ~0x5000):
                reasons.append('fixture_test_or_quality')
            if 'duplicate_or_reordered' in reasons:
                raise ValueError('Duplicate/reordered original frame in one source session')
            if reasons:
                rejected.append(dict(line=number, split=split, session_id=names[2], frame_id=frame.id,
                                     reasons=sorted(set(reasons))))
                continue
            group_name = json.dumps(group, separators=(',', ':'))
            rows[split].append(frame.values)
            labels[split].append(LABELS.index(label))
            sessions[split].append(group_name)
            metadata.setdefault(group_name, dict(device_id=names[0], installation_id=names[1], session_id=names[2],
                split=split, source=source, label_source=record['label_source'],
                label_reviewed=record['label_reviewed'], physical_truth_attested_by_importer=False))
    if not any(rows.values()):
        raise ValueError('No qualified-shape windows survived input gates')
    counts = {split: {label: len({group for group, target in zip(sessions[split], labels[split]) if target == index})
                     for index, label in enumerate(LABELS)} for split in rows}
    ready = all(counts[split][label] >= (2 if split == 'train' else 1) for split in rows for label in LABELS)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(file, output/'source_records.jsonl')
    if digest((output/'source_records.jsonl').read_bytes()) != hasher.hexdigest():
        raise ValueError('Source log changed while importing')
    (output/'original_contract.json').write_bytes(contract_bytes)
    for split in rows:
        np.savez_compressed(output/(split+'.npz'), values=np.asarray(rows[split], dtype=np.float32).reshape(-1, 39),
                            labels=np.asarray(labels[split], dtype=np.int64), sessions=np.asarray(sessions[split], dtype=str))
        save(output/(split+'_sessions.json'), [value for value in metadata.values() if value['split'] == split])
    contract['source'] = source
    save(output/'feature_contract.json', contract)
    save(output/'rejected.json', rejected)
    artifacts = {entry.name: digest(entry.read_bytes()) for entry in output.iterdir() if entry.is_file()}
    manifest = dict(schema='cabinet-imported-frames-v1', status='PASS_FRAME_IMPORT_ONLY', source=source,
        pl_build_id=contract['pl_build_id'],
        train_ready=ready, production_qualified=False, physical_truth_verified=False,
        input_file_sha256=hasher.hexdigest(), declared_source_path=str(file.resolve()),
        original_contract_sha256=digest(contract_bytes), artifacts_sha256=artifacts,
        split_by_source_session_and_episode=True, accepted={split: len(values) for split, values in rows.items()},
        rejected=len(rejected), rejected_reasons=dict(Counter(reason for row in rejected for reason in row['reasons'])),
        independent_sessions_per_class=counts,
        train_readiness_is_not_statistical_sufficiency=True, no_new_filter_applied_to_existing_features=True)
    save(output/'dataset_manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-synthetic-fixture', action='store_true')
    args = parser.parse_args()
    print(json.dumps(import_records(args.input, args.contract, args.output, args.allow_synthetic_fixture), indent=2))


if __name__ == '__main__':
    main()
