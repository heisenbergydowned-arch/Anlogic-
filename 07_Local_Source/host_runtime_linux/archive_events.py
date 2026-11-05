"""Manually export event evidence; optional prune retains active/pending/unacknowledged data."""
import argparse
import json
from pathlib import Path

from cabinet.maintenance import archive_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--prune-verified-history', action='store_true')
    parser.add_argument('--keep-latest', type=int, default=1000)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--provider',choices=['cryptography','openssl-evp'],default='cryptography')
    parser.add_argument('--library');parser.add_argument('--library-sha256')
    args = parser.parse_args()
    encryption=dict(enabled=True,key_file=str(args.key_file),provider=args.provider) if args.key_file else None
    if args.provider=='openssl-evp':
        if not encryption or not args.library or not args.library_sha256:parser.error('Key and pinned EVP native library required')
        encryption.update(library=args.library,library_sha256=args.library_sha256)
    result = archive_database(args.database, args.output, args.prune_verified_history, args.keep_latest, encryption)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
