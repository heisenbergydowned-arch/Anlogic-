"""Explicit key provisioning, offline journal migration and private report export."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from cabinet.journal_crypto import configure, create_key, migrate


def export_report(database, output, encryption, acknowledge_plaintext=False):
    if acknowledge_plaintext is not True:
        raise ValueError('Explicit acknowledgement required for a decrypted maintenance report')
    if Path(database).is_symlink() or not Path(database).is_file():
        raise ValueError('Existing regular event journal required')
    connection=sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        cipher=configure(connection,encryption,readonly=True)
        connection.execute('BEGIN')
        descriptor=os.open(str(output),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        count=0
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow(['event_id','revision','device_id','wall_time','wall_time_valid','source','code','state','severity_peak','acknowledged','grade','remaining_life_s','qualification_note'])
            for identity,revision,payload in connection.execute('SELECT event_id,revision,payload FROM events ORDER BY rowid'):
                event=cipher.open(payload,'events',identity,revision) if cipher else json.loads(payload)
                grade=event.get('fault_grade') or {};maintenance=event.get('maintenance') or {}
                values=[identity,revision,event.get('device_id'),event.get('wall_time'),event.get('wall_time_valid',False),event.get('source'),event.get('code'),event.get('state'),event.get('severity_peak'),event.get('acknowledged',False),grade.get('grade') if grade.get('qualified') is True else None,maintenance.get('remaining_life_s'),'EXPORT_DOES_NOT_GRANT_MODEL_OR_LIFETIME_QUALIFICATION']
                writer.writerow([("'"+value if value[:1] in '=+-@\t\r\n' else value) if type(value) is str else value for value in values]);count+=1
            stream.flush();os.fsync(stream.fileno())
        return dict(status='PASS_EXPLICIT_PRIVATE_PLAINTEXT_REPORT',rows=count,sha256=hashlib.sha256(Path(output).read_bytes()).hexdigest(),qualification_granted=False)
    finally:
        connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['keygen','migrate','report'])
    parser.add_argument('--key-file',required=True,type=Path)
    parser.add_argument('--database',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--ack-plaintext-export',action='store_true')
    parser.add_argument('--provider',choices=['cryptography','openssl-evp'],default='cryptography')
    parser.add_argument('--library');parser.add_argument('--library-sha256')
    arguments=parser.parse_args()
    if arguments.action=='keygen':
        create_key(arguments.key_file);print(json.dumps(dict(status='KEY_CREATED_KEEP_SEPARATE_DO_NOT_PACKAGE')));return
    if not arguments.database or not arguments.output:parser.error('--database and --output required')
    encryption=dict(enabled=True,key_file=str(arguments.key_file),provider=arguments.provider)
    if arguments.provider=='openssl-evp':
        if not arguments.library or not arguments.library_sha256:parser.error('Pinned EVP native library required')
        encryption.update(library=arguments.library,library_sha256=arguments.library_sha256)
    result=migrate(arguments.database,arguments.output,encryption) if arguments.action=='migrate' else export_report(arguments.database,arguments.output,encryption,arguments.ack_plaintext_export)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
