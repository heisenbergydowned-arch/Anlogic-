#!/usr/bin/env python3
"""Offline reviewed REAL archives to existing labelled FRM1 import; never approves a model."""
import argparse
import csv
import json
from pathlib import Path
import sys

from cabinet.capture import CAPTURE_BUILD_IDS, digest, frame_words
from cabinet.protocol import FEATURES, Frame


def export(review_path, output):
    review_path, output = Path(review_path).resolve(), Path(output).resolve()
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if output.exists() or review.get('schema') != 'cabinet-capture-review-v1':
        raise ValueError('Fresh output and reviewed session plan required')
    entries = review.get('sessions')
    if type(entries) is not list or not entries:
        raise ValueError('Explicit reviewed sessions required')
    loaded, sessions, episodes = [], set(), {}
    contract = None
    for entry in entries:
        directory = Path(entry['directory']).resolve()
        summary = json.loads((directory / 'summary.json').read_text())
        session = json.loads((directory / 'session.json').read_text())
        current_contract = json.loads((directory / 'feature_contract.json').read_text())
        if type(current_contract.get('pl_build_id')) is not int or current_contract['pl_build_id'] not in CAPTURE_BUILD_IDS:
            raise ValueError('Explicit reviewed capture PL identity required')
        if session.get('pl_build_id', current_contract['pl_build_id']) != current_contract['pl_build_id']:
            raise ValueError('Session and feature contract PL identity differ')
        if (summary.get('schema') != 'cabinet-capture-status-v1' or summary.get('state') != 'COMPLETED' or
                session.get('capture_mode') != 'REAL' or summary.get('gaps') != 0 or summary.get('accepted', 0) < 1):
            raise ValueError('Only completed, gap-free REAL sessions can be reviewed')
        if set(summary.get('files_sha256', {})) != {'session.json', 'frames.jsonl', 'feature_contract.json'}:
            raise ValueError('Archive hash inventory missing')
        for name, expected in summary['files_sha256'].items():
            if (directory / name).is_symlink() or digest(directory / name) != expected:
                raise ValueError('Archive changed: ' + name)
        identity = session['session_id']
        if identity in sessions or identity != summary['session_id']:
            raise ValueError('Duplicate/mismatched session')
        sessions.add(identity)
        if contract is not None and contract != current_contract:
            raise ValueError('Different feature/calibration contracts require separate datasets')
        contract = current_contract
        if entry.get('label_reviewed') is not True or entry.get('split') not in ('train', 'validation', 'test'):
            raise ValueError('Explicit reviewed label and frozen split required')
        if entry.get('label') not in ('normal', 'imbalance', 'stall', 'clog', 'overheat'):
            raise ValueError('A reviewed five-class label is required')
        for key in ('reviewer', 'fault_episode_id'):
            if type(entry.get(key)) is not str or not entry[key] or len(entry[key]) > 80:
                raise ValueError('Invalid review identity: ' + key)
        episode = session['device_id'], session['installation_id'], entry['fault_episode_id']
        if episodes.setdefault(episode, entry['split']) != entry['split']:
            raise ValueError('Fault episode leaked across splits')
        evidence = {}
        for key in ('label_evidence', 'calibration_evidence', 'bitstream'):
            path = Path(entry[key])
            if not path.is_absolute():
                path = review_path.parent / path
            evidence[key + '_sha256'] = digest(path)
        if (evidence['calibration_evidence_sha256'] != session['calibration_evidence_sha256'] or
                evidence['bitstream_sha256'] != session['bitstream_sha256']):
            raise ValueError('Review evidence does not match capture provenance')
        loaded.append((directory, summary, session, entry, evidence))
    output.mkdir(parents=True)
    count, excluded = 0, 0
    try:
        with (output / 'frames.jsonl').open('x', encoding='utf-8') as stream, \
                (output / 'features.csv').open('x', encoding='utf-8', newline='') as table:
            writer = csv.writer(table)
            writer.writerow(['session_id', 'frame_id', 'label', 'split'] + list(FEATURES))
            for directory, summary, session, entry, evidence in loaded:
                seen, accepted = 0, 0
                with (directory / 'frames.jsonl').open(encoding='utf-8') as source:
                    for line in source:
                        if len(line) > 65536:
                            raise ValueError('Archive row too large')
                        row = json.loads(line)
                        seen += 1
                        if row.get('accepted') is not True:
                            excluded += 1
                            continue
                        frame = Frame.from_words(row['header'], row['feature_words'])
                        if (row.get('schema') != 'cabinet-capture-frame-v1' or row.get('source') != 'REAL_FRM1_DECLARED' or
                                row.get('session_id') != session['session_id'] or row.get('boot_id') != session['boot_id'] or
                                row.get('rejected_reasons') != [] or frame.test or frame.quality):
                            raise ValueError('Accepted row has invalid provenance/quality')
                        if frame.header[26] != current_contract['pl_build_id']:
                            raise ValueError('Accepted row PL identity differs from its contract')
                        status = row.get('status', {})
                        if entry['label'] == 'normal' and (status.get('active') or status.get('latched') or status.get('hard_inhibit')):
                            raise ValueError('Protected/faulted input cannot be reviewed as normal')
                        record = dict(schema='cabinet-labelled-frame-v1', source='REAL_FRM1_DECLARED',
                            split=entry['split'], label=entry['label'], device_id=session['device_id'],
                            installation_id=session['installation_id'], session_id=session['session_id'],
                            boot_id=session['boot_id'], fault_episode_id=entry['fault_episode_id'],
                            label_source='BENCH_REVIEWED', label_reviewed=True, reviewer=entry['reviewer'],
                            header=row['header'], feature_words=frame_words(frame), now_ms=row['now_ms'], **evidence)
                        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n')
                        writer.writerow([session['session_id'], frame.id, entry['label'], entry['split']] + list(frame.values))
                        accepted += 1
                        count += 1
                if seen != summary['frames'] or accepted != summary['accepted']:
                    raise ValueError('Archive counts changed')
        (output / 'feature_contract.json').write_text(json.dumps(contract, indent=2) + '\n')
        report = dict(schema='cabinet-capture-export-v1', status='PASS_REVIEWED_EXPORT_ONLY',
            source='REAL_FRM1_DECLARED', qualified=False, physical_truth_verified=False,
            review_sha256=digest(review_path), sessions=len(loaded), frames=count, excluded_rejected_frames=excluded,
            source_summaries={str(directory): digest(directory / 'summary.json') for directory, *_ in loaded},
            files_sha256={name: digest(output / name) for name in ('frames.jsonl', 'features.csv', 'feature_contract.json')})
        (output / 'export_manifest.json').write_text(json.dumps(report, indent=2) + '\n')
        return report
    except BaseException:
        (output / 'FAILED_NOT_TRAINING_READY').touch()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.review, args.output), indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Capture export rejected: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
