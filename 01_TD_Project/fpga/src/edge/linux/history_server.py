"""Read-only UI for an independently verified archived event database."""
import argparse
from pathlib import Path
import sqlite3
import threading
from urllib.parse import quote
from cabinet.history import History
from cabinet.web import server


class ArchiveStore:
    def __init__(self, path, encryption=None):
        self.lock = threading.RLock()
        self.db = sqlite3.connect('file:' + quote(str(Path(path).resolve())) + '?mode=ro', uri=True, check_same_thread=False)
        self.db.execute('PRAGMA query_only=ON')
        from cabinet.journal_crypto import configure
        try:self.cipher=configure(self.db,encryption,readonly=True)
        except BaseException:self.db.close();raise
        tables={row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'history_samples','waveform_index','waveforms'} <= tables:
            self.db.close()
            raise ValueError('Archive predates R31 history indexing; no timestamps will be invented')
        self.history=History(self,initialize=False)

    def events(self):
        with self.lock:
            return [self.unpack(row[2],'events',row[0],row[1]) for row in self.db.execute('SELECT event_id,revision,payload FROM events ORDER BY rowid DESC LIMIT 100')]

    def unpack(self,payload,table,identity,revision=None):
        import json
        return self.cipher.open(payload,table,identity,revision) if self.cipher else json.loads(payload)

    def acknowledge(self, unused):
        raise ValueError('Read-only archive')

    def close(self):
        self.db.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--device',required=True)
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--key-file',type=Path)
    parser.add_argument('--provider',choices=['cryptography','openssl-evp'],default='cryptography')
    parser.add_argument('--library');parser.add_argument('--library-sha256')
    args=parser.parse_args()
    encryption=dict(enabled=True,key_file=str(args.key_file),provider=args.provider) if args.key_file else None
    if args.provider=='openssl-evp':
        if not encryption or not args.library or not args.library_sha256:parser.error('Key and pinned EVP native library required')
        encryption.update(library=args.library,library_sha256=args.library_sha256)
    archive=ArchiveStore(args.database,encryption)
    class Service:
        store=archive
        config=dict(device_id=args.device)
        def public_state(self):
            return dict(link='OFFLINE',archive_only=True)
    listener=server('127.0.0.1',args.port,Service())
    try:listener.serve_forever()
    finally:listener.server_close();archive.close()
