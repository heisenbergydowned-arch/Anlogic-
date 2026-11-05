"""Immutable, episode-separated registry of user-labelled real diagnostic captures."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
if __package__:
    from .utf8_io import configure_stdio
else:
    from utf8_io import configure_stdio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'linux'))
from labeled_npu.core import feature_values, INPUT_POLICIES
from v4_runtime.bundle import LABELS, loads

SOURCE = 'REAL_USER_DECLARED_LABELED_DIAGNOSTIC'
SPLITS = ('train', 'validation', 'test')
MIN_EPISODES = {'train': 2, 'validation': 1, 'test': 1}
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()

def save(path, value):
    path = Path(path)
    data = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    with tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False) as f:
        temporary = Path(f.name); f.write(data); f.flush(); os.fsync(f.fileno())
    temporary.chmod(0o600); os.replace(str(temporary), str(path))

def read(path, limit=32*1024*1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('UNSAFE_CAPTURE_FILE: ' + str(path))
    return loads(path.read_text(encoding='utf-8'))

def identity(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value):
        raise ValueError('INVALID_CAPTURE_IDENTITY')
    return value

def common_contract(contract):
    # Controller protection state is a measured class condition, not a new sensor installation.
    return {k: v for k, v in contract.items() if k not in ('controller_mode', 'allowed_controller_modes')}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def load_export(export):
    export = Path(export)
    learning = read(export / 'learning.json', 131072)
    if (learning.get('schema') != 'cabinet-one-click-labeled-learning-v1'
            or learning.get('source') != SOURCE or learning.get('qualified') is not False
            or learning.get('label_source') != 'USER_DECLARES_CURRENT_CONDITION'
            or learning.get('condition_confirmed') is not True
            or learning.get('episode_confirmed') is not True
            or learning.get('raw_capture_qualification_changed') is not False):
        raise ValueError('REAL_USER_LABEL_DECLARATION_REQUIRED')
    label = learning.get('label'); episode = identity(learning.get('episode_id'))
    if label not in LABELS: raise ValueError('UNKNOWN_LABEL')
    if learning.get('episode_split') not in SPLITS: raise ValueError('FROZEN_EPISODE_SPLIT_REQUIRED')
    contract = learning['context']['input_contract']
    if contract.get('input_policy') not in INPUT_POLICIES:
        raise ValueError('EXPLICIT_VERSIONED_INPUT_POLICY_REQUIRED')
    receipts = read(export / 'sessions.json', 262144)
    if set(receipts) != {'episode'}: raise ValueError('EXACTLY_ONE_EPISODE_CAPTURE_REQUIRED')
    p = export / 'captures' / 'episode'
    meta = read(p / 'session.json', 262144); summary = read(p / 'summary.json', 262144)
    receipt = receipts['episode']['status']
    if (receipt.get('state') != 'DIAGNOSTIC_SAVED' or summary.get('state') != 'DIAGNOSTIC_SAVED'
            or meta.get('capture_mode') != 'DIAGNOSTIC' or meta.get('qualified') is not False
            or meta.get('window_policy') != 'INDEPENDENT_LABELED_NPU_WINDOWS'
            or meta.get('label_declared') not in (None, 'unlabelled')
            or meta.get('session_id') != summary.get('session_id')
            or meta.get('session_id') != receipt.get('session_id')):
        raise ValueError('COMPLETE_UNQUALIFIED_REAL_CAPTURE_REQUIRED')
    if meta.get('bitstream_sha256') != learning['context']['bitstream_sha256']:
        raise ValueError('BITSTREAM_PROVENANCE_CHANGED')
    if meta.get('boot_id') != learning['context']['collector_boot']:
        raise ValueError('CAPTURE_BOOT_IDENTITY_CHANGED')
    if (meta.get('device_id') != contract['device_id']
            or meta.get('configuration_words') != contract['configuration_words']):
        raise ValueError('CAPTURE_CONTRACT_CHANGED')
    hashes = summary.get('files_sha256', {})
    if set(hashes) != {'frames.jsonl', 'feature_contract.json', 'session.json'}:
        raise ValueError('CAPTURE_HASH_INVENTORY_CHANGED')
    for name, digest in hashes.items():
        file = p / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 32*1024*1024 or sha(file) != digest:
            raise ValueError('CAPTURE_HASH_CHANGED: ' + name)
    rows = [loads(line) for line in (p / 'frames.jsonl').read_text(encoding='utf-8').splitlines()]
    if not 600 <= len(rows) <= 1000 or len(rows) != summary['frames'] or summary['durable_frames'] != summary['frames']:
        raise ValueError('INSUFFICIENT_COMPLETE_CAPTURE_ROWS')
    values = []; frame_ids = []; last = meta.get('preceding_frame_id'); missing = 0; gaps = 0
    for row in rows:
        if (row.get('schema') != 'cabinet-capture-frame-v1' or row.get('source') != 'REAL_FRM1_DECLARED'
                or row.get('session_id') != meta['session_id'] or row.get('boot_id') != meta['boot_id']
                or row.get('accepted') is not False or 'DIAGNOSTIC_NOT_TRAINING' not in row.get('rejected_reasons',[])):
            raise ValueError('SYNTHETIC_OR_FOREIGN_CAPTURE_REJECTED')
        h = row['header']
        status=row['status']
        protection=dict(mode=status.get('mode'),hard_inhibit=status.get('hard_inhibit'),latched=sorted(status.get('latched',[])))
        if protection!=learning['context'].get('capture_guard'):
            raise ValueError('PROTECTION_PHASE_CHANGED_DURING_CAPTURE')
        if last is not None:
            step = (h[3] - last) & 0xffffffff
            if not 1 <= step <= 8 or row.get('gap_before', 0) != step - 1:
                raise ValueError('REORDERED_DUPLICATE_OR_UNACCOUNTED_FRAME')
            missing += step - 1; gaps += int(step > 1)
        last = h[3]
        values.append(feature_values(h, row['feature_words'], status, contract,
                                    label=label, fg_connected_confirmed=learning.get('fg_connected_confirmed', False)))
        frame_ids.append(h[3])
    if (missing != summary.get('missing_frames', 0) or gaps != summary.get('gaps', 0)
            or missing / max(1, len(rows) + missing) > .02):
        raise ValueError('CAPTURE_GAP_BUDGET_EXCEEDED')
    return learning, meta, summary, values, frame_ids

def coverage(entries):
    counts = {label: {split: len({e['episode_id'] for e in entries if e['label'] == label and e['split'] == split})
                      for split in SPLITS} for label in LABELS}
    missing = {label: {split: max(0, MIN_EPISODES[split] - counts[label][split]) for split in SPLITS}
               for label in LABELS}
    return counts, missing, all(not n for group in missing.values() for n in group.values())

def register(export, registry):
    learning, meta, summary, values, frame_ids = load_export(export)
    export = Path(export).resolve(); registry = Path(registry).resolve(); registry.mkdir(parents=True, exist_ok=True)
    contract = common_contract(learning['context']['input_contract'])
    # Different bitstreams/configurations/physical installations cannot silently enter one corpus.
    binding = dict(device_id=contract['device_id'], input_contract=contract,
                   bitstream_sha256=learning['context']['bitstream_sha256'],
                   config_sha256=learning['context']['config_sha256'])
    corpus_id = hashlib.sha256(canonical(binding)).hexdigest()
    if learning.get('corpus_key') != corpus_id: raise ValueError('BOARD_CORPUS_IDENTITY_CHANGED')
    corpus = registry / corpus_id; corpus.mkdir(exist_ok=True)
    with (registry / 'registry.lock').open('a', encoding='utf-8') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        index = read(corpus / 'index.json') if (corpus / 'index.json').exists() else dict(
            schema='cabinet-real-labeled-registry-v1', source=SOURCE, corpus_id=corpus_id,
            contract_binding=binding, entries=[], qualified=False, control_authority='NONE')
        entries = index['entries']; session = identity(meta['session_id'])
        record = dict(session_id=session, label=learning['label'], episode_id=learning['episode_id'],
            split=learning['episode_split'], rows=len(values), frames_sha256=summary['files_sha256']['frames.jsonl'],
            session_sha256=summary['files_sha256']['session.json'], learning_sha256=sha(export / 'learning.json'),
            controller_mode=learning['context']['input_contract']['controller_mode'],
            first_frame=frame_ids[0], last_frame=frame_ids[-1], boot_id=meta['boot_id'])
        for previous in entries:
            if previous['episode_id'] == record['episode_id'] and (previous['label'], previous['split']) != (record['label'], record['split']):
                raise ValueError('EPISODE_RELABEL_OR_SPLIT_LEAKAGE')
            if previous['session_id'] == session:
                if previous != record: raise ValueError('REGISTERED_SESSION_CHANGED')
                break
            if previous['frames_sha256'] == record['frames_sha256']:
                raise ValueError('DUPLICATE_CAPTURE_CANNOT_INCREASE_DATASET')
        else:
            folder = corpus / 'sessions' / session; folder.parent.mkdir(exist_ok=True)
            if folder.exists():
                raise ValueError('ORPHANED_REGISTRY_SESSION_REQUIRES_REVIEW')
            folder.mkdir()
            (folder/'captures'/'episode').mkdir(parents=True)
            for name in ('learning.json','sessions.json'):
                shutil.copy2(str(export/name),str(folder/name))
            for name in ('session.json','summary.json','feature_contract.json','frames.jsonl'):
                shutil.copy2(str(export/'captures/episode'/name),str(folder/'captures/episode'/name))
            # Verify copied bytes before publication; never trust a moving export.
            copied = load_export(folder)
            if sha(folder / 'learning.json') != record['learning_sha256'] or copied[2]['files_sha256'] != summary['files_sha256']:
                raise ValueError('EXPORT_CHANGED_DURING_REGISTRATION')
            entries.append(record); save(corpus / 'index.json', index)
        counts, missing, ready = coverage(entries)
        modes = sorted({e['controller_mode'] for e in entries})
        input_contract = dict(contract, allowed_controller_modes=modes)
        snapshot = dict(schema='cabinet-real-labeled-dataset-v1', source=SOURCE, corpus_id=corpus_id,
            input_contract=input_contract, bitstream_sha256=binding['bitstream_sha256'], entries=entries,
            independent_episodes=counts, missing_episodes=missing, train_ready=ready,
            qualified=False, control_authority='NONE', registry_index_sha256=sha(corpus / 'index.json'))
        snapshot_id = hashlib.sha256(canonical(snapshot)).hexdigest()
        dataset = corpus / 'datasets' / snapshot_id; dataset.mkdir(parents=True, exist_ok=True)
        snapshot['sessions_root'] = str(corpus / 'sessions')
        if (dataset / 'dataset.json').exists():
            if read(dataset / 'dataset.json') != snapshot: raise ValueError('IMMUTABLE_DATASET_CHANGED')
        else: save(dataset / 'dataset.json', snapshot)
        result = dict(status='READY_TO_TRAIN' if ready else 'WAITING_DATA', source=SOURCE,
            corpus_id=corpus_id, dataset_dir=str(dataset), dataset_sha256=sha(dataset / 'dataset.json'),
            contract_key=corpus_id, corpus_key=corpus_id, coverage=counts, missing=missing,
            independent_episodes=counts, missing_episodes=missing, registered_session=session,
            classified_classes_ready=[l for l in LABELS if all(counts[l][s] >= MIN_EPISODES[s] for s in SPLITS)],
            qualified=False, control_authority='NONE', existing_model_preserved=True)
        save(export / 'corpus.json', result)
        return result

def main():
    configure_stdio()
    p = argparse.ArgumentParser(); p.add_argument('--export', required=True, type=Path); p.add_argument('--registry', required=True, type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args(); result = register(a.export, a.registry)
    if a.output: save(a.output, result)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__': main()
