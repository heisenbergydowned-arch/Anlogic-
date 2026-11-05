"""SQLite event journal + durable outbox. I/O runs outside the PL control loop."""
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time

def encode(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))

class Store:
    def __init__(self,path,storage=None,encryption=None):
        self.path=Path(path)
        policy=dict(min_free_bytes=64*1024*1024,max_database_bytes=512*1024*1024,max_waveforms=10000)
        if storage is not None:
            if type(storage) is not dict or set(storage)-set(policy):raise ValueError('Unknown storage policy')
            policy.update(storage)
        if any(type(value) is not int or value<1 for value in policy.values()):raise ValueError('Positive integer storage limits required')
        self.storage_policy=policy
        self.lock=threading.RLock();self.db=sqlite3.connect(str(path),check_same_thread=False,timeout=1)
        from .journal_crypto import configure
        try:self.cipher=configure(self.db,encryption)
        except BaseException:self.db.close();raise
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS events(
            event_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(
            event_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,next_retry REAL NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(event_id,revision));
            CREATE TABLE IF NOT EXISTS receipts(
            event_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots(device_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fifo_records(record_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS diagnostics(id INTEGER PRIMARY KEY,created REAL,code TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS waveforms(record_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,payload TEXT NOT NULL);
        ''')
        if 'priority' not in [r[1] for r in self.db.execute('PRAGMA table_info(outbox)')]:
            self.db.execute('ALTER TABLE outbox ADD COLUMN priority INTEGER NOT NULL DEFAULT 0')
        self.db.commit()
        from .history import History
        self.history = History(self)
    def pack(self,value,table,identity,revision=None):
        return self.cipher.seal(value,table,identity,revision) if self.cipher else encode(value)
    def unpack(self,payload,table,identity,revision=None):
        return self.cipher.open(payload,table,identity,revision) if self.cipher else json.loads(payload)
    @contextmanager
    def transaction(self):
        with self.lock:
            try:yield self.db;self.db.commit()
            except BaseException:self.db.rollback();raise
    def snapshot(self,device_id,state):
        with self.transaction() as db:db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?)',(device_id,self.pack(state,'snapshots',device_id)))
    def get_snapshot(self,device_id):
        with self.lock:row=self.db.execute('SELECT payload FROM snapshots WHERE device_id=?',(device_id,)).fetchone()
        return self.unpack(row[0],'snapshots',device_id) if row else None
    def storage_health(self):
        free=shutil.disk_usage(str(self.path.resolve().parent)).free
        size=sum(file.stat().st_size for file in (self.path,Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm')) if file.is_file())
        with self.lock:
            page_size=self.db.execute('PRAGMA page_size').fetchone()[0]
            used=(self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0])*page_size
            counts={table:self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                    for table in ('events','outbox','fifo_records','waveforms')}
        reasons=[]
        if free<self.storage_policy['min_free_bytes']:reasons.append('LOW_DISK_SPACE')
        if used>=self.storage_policy['max_database_bytes']:reasons.append('DATABASE_HIGH_WATER')
        if counts['waveforms']>=self.storage_policy['max_waveforms']:reasons.append('WAVEFORM_CAPACITY')
        return dict(state='ARCHIVE_REQUIRED' if reasons else 'OK',reasons=reasons,free_bytes=free,
                    database_bytes=size,used_database_bytes=used,counts=counts,automatic_deletion=False)
    def waveform(self,identity,record,device_id=None):
        from .waveform import validate_record,checksum
        validate_record(record)
        if checksum(record)!=identity:raise ValueError('WAV1 archive digest mismatch')
        payload=self.pack(record,'waveforms',identity)
        with self.lock:
            old=self.db.execute('SELECT sha256,payload FROM waveforms WHERE record_id=?',(identity,)).fetchone()
            if old:
                if old[0]!=identity or self.unpack(old[1],'waveforms',identity)!=record:raise ValueError('WAV1 archive content conflict')
                if device_id:
                    with self.transaction() as db:db.execute('INSERT OR IGNORE INTO waveform_index(device,boot,event_id,recorded,record_id) VALUES(?,?,?,?,?)',
                        (device_id,record['boot_id'],record['event_id'],time.time(),identity))
                return identity
            health=self.storage_health()
            if health['state']!='OK':raise OSError('WAV1 retained in PL: '+','.join(health['reasons']))
            if health['free_bytes']-len(payload.encode('utf-8'))<self.storage_policy['min_free_bytes']:
                raise OSError('WAV1 would consume the event reserve')
            if health['used_database_bytes']+len(payload.encode('utf-8'))*2>=self.storage_policy['max_database_bytes']:
                raise OSError('WAV1 would exceed database high water')
            with self.transaction() as db:
                db.execute('INSERT INTO waveforms VALUES(?,?,?)',(identity,identity,payload))
                if device_id:db.execute('INSERT INTO waveform_index(device,boot,event_id,recorded,record_id) VALUES(?,?,?,?,?)',
                    (device_id,record['boot_id'],record['event_id'],time.time(),identity))
        return identity
    def get_event(self,identity):
        with self.lock:row=self.db.execute('SELECT revision,payload FROM events WHERE event_id=?',(identity,)).fetchone()
        return self.unpack(row[1],'events',identity,row[0]) if row else None
    def event(self,event):
        """Commit journal and send queue atomically before a PL FIFO is popped."""
        e=dict(event);identity=e['event_id'];e['event_revision']=int(e['event_revision'])
        if e['event_revision']<1:raise ValueError('Event revision')
        with self.transaction() as db:
            old=db.execute('SELECT revision FROM events WHERE event_id=?',(identity,)).fetchone()
            if old and old[0]>=e['event_revision']:return False
            payload=self.pack(e,'events',identity,e['event_revision'])
            db.execute('INSERT OR REPLACE INTO events VALUES(?,?,?)',(identity,e['event_revision'],payload))
            if e.get('notify',True):db.execute('INSERT OR IGNORE INTO outbox(event_id,revision,payload,priority) VALUES(?,?,?,?)',
                                             (identity,e['event_revision'],self.pack(e,'outbox',identity,e['event_revision']),int(e.get('severity_peak',0))))
        return True
    def acknowledge(self,identity):
        with self.lock:
            row=self.db.execute('SELECT revision,payload FROM events WHERE event_id=?',(identity,)).fetchone()
            if not row:raise KeyError(identity)
            event=self.unpack(row[1],'events',identity,row[0])
            if event.get('acknowledged') is True:return event
            event['acknowledged']=True;event['event_revision']+=1
            self.event(event);return event
    def fifo(self,identity,words,event=None):
        # Raw hardware evidence and its historical event share one durable
        # transaction. A short fault between PS polls must still be uploadable.
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO fifo_records VALUES(?,?)',(identity,self.pack(words,'fifo_records',identity)))
            if event:
                payload=self.pack(event,'events',event['event_id'],1)
                inserted=db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?)',
                                    (event['event_id'],1,payload)).rowcount
                if inserted and event['notify']:
                    db.execute('INSERT OR IGNORE INTO outbox(event_id,revision,payload,priority) VALUES(?,?,?,?)',
                               (event['event_id'],1,self.pack(event,'outbox',event['event_id'],1),event['severity_peak']))
    def events(self,limit=100):
        with self.lock:rows=self.db.execute('SELECT event_id,revision,payload FROM events ORDER BY rowid DESC LIMIT ?',(min(1000,limit),)).fetchall()
        return [self.unpack(row[2],'events',row[0],row[1]) for row in rows]
    def active_events(self,device_id,boot_id):
        result=[]
        with self.lock:
            cursor=self.db.execute('SELECT event_id,revision,payload FROM events ORDER BY rowid')
            while True:
                rows=cursor.fetchmany(128)
                if not rows:break
                for row in rows:
                    event=self.unpack(row[2],'events',row[0],row[1])
                    if event.get('device_id')==device_id and event.get('boot_id')==boot_id and event.get('state') in ('ACTIVE','OBSERVING'):
                        result.append(event)
        return result
    def pending(self,limit=16):
        with self.lock:rows=self.db.execute('SELECT event_id,revision,payload,attempts FROM outbox WHERE next_retry<=? ORDER BY priority DESC,rowid LIMIT ?',
                                         (time.monotonic(),limit)).fetchall()
        return [dict(event_id=row[0],revision=row[1],payload=self.unpack(row[2],'outbox',row[0],row[1]),attempts=row[3]) for row in rows]
    def delivered(self,identity,revision):
        with self.transaction() as db:db.execute('DELETE FROM outbox WHERE event_id=? AND revision=?',(identity,revision))
    def retry(self,identity,revision,attempts):
        # Stored retry uses wall time? Monotonic timestamps cannot survive reboot.
        # We deliberately reset deadlines to zero at service startup below.
        delay=min(60,2**min(attempts,6))
        with self.transaction() as db:db.execute('UPDATE outbox SET attempts=attempts+1,next_retry=? WHERE event_id=? AND revision=?',
                                               (time.monotonic()+delay,identity,revision))
    def reset_retry_clock(self):
        with self.transaction() as db:db.execute('UPDATE outbox SET next_retry=0')
    def receive(self,event):
        """Platform idempotency: old/repeated revisions cannot overwrite current."""
        identity=event['event_id'];revision=event['event_revision']
        if type(identity) is not str or not identity or len(identity)>200 or type(revision) is not int or revision<1:
            raise ValueError('Event identity/revision')
        with self.transaction() as db:
            old=db.execute('SELECT revision FROM receipts WHERE event_id=?',(identity,)).fetchone()
            if not old or revision>old[0]:db.execute('INSERT OR REPLACE INTO receipts VALUES(?,?,?)',(identity,revision,self.pack(event,'receipts',identity,revision)))
        return dict(event_id=identity,event_revision=revision,accepted=True)
    def received(self):
        with self.lock:rows=self.db.execute('SELECT event_id,revision,payload FROM receipts ORDER BY rowid DESC LIMIT 100').fetchall()
        return [self.unpack(row[2],'receipts',row[0],row[1]) for row in rows]
    def diagnostic(self,code,payload):
        with self.transaction() as db:
            identity=db.execute('INSERT INTO diagnostics(created,code,payload) VALUES(?,?,?)',(time.time(),'ENCRYPTED' if self.cipher else code,'')).lastrowid
            value=dict(code=code,payload=payload) if self.cipher else payload
            db.execute('UPDATE diagnostics SET payload=? WHERE id=?',(self.pack(value,'diagnostics',identity),identity))
            db.execute('DELETE FROM diagnostics WHERE id<(SELECT COALESCE(MAX(id),0)-1000 FROM diagnostics)')
    def close(self):
        with self.lock:self.db.close()

class EventTracker:
    def __init__(self,store,device_id,boot_id):
        self.store=store;self.device=device_id;self.boot=boot_id
        self.active={event['source']+':'+event['code']:event for event in store.active_events(device_id,boot_id)}
    def update(self,code,severity,active,status,*,notify=True,source='PL'):
        with self.store.lock:
            return self.update_locked(code,severity,active,status,notify=notify,source=source)
    def update_locked(self,code,severity,active,status,*,notify=True,source='PL'):
        key=source+':'+code;old=self.active.get(key)
        if not active and old is None:return
        desired=('OBSERVING' if source in ('MODEL','PREDICTION') and not notify else 'ACTIVE') if active else 'RECOVERED'
        changed=old is None or old['severity_current']!=severity or old['state']!=desired or old.get('confirmed',old.get('notify'))!=notify
        if source=='MODEL' and old and old.get('evidence_state','UNKNOWN')!=status.get('model_evidence_state','UNKNOWN'):changed=True
        if source=='MODEL' and old:
            previous_grade=old.get('fault_grade') or {};current_grade=status.get('fault_grade') or {}
            if any(previous_grade.get(key)!=current_grade.get(key) for key in ('state','grade','qualified','model_sha256')):changed=True
        if not changed:return
        now=time.monotonic();wall=datetime.now(timezone.utc).isoformat()
        if old is None:
            identity=hashlib.sha256(f'{self.device}/{self.boot}/{key}/{now}'.encode()).hexdigest()[:32]
            event=dict(event_id=identity,event_revision=0,device_id=self.device,boot_id=self.boot,code=code,source=source,
                       first_seen_mono=now,acknowledged=False,severity_peak=severity)
        else:
            # Preserve a website ACK and its newer revision across later
            # recovery/upgrade; never overwrite it with an older cache entry.
            event=self.store.get_event(old['event_id']) or dict(old)
        # A candidate becomes a publishable event when confirmation arrives;
        # recovery of a previously published event must also reach the site.
        publish=notify or bool(old and old.get('notify'))
        event.update(event_revision=event['event_revision']+1,severity_current=severity,
                     severity_peak=max(event['severity_peak'],severity),state=desired,
                     last_seen_mono=now,wall_time=wall,wall_time_valid=bool(status.get('wall_time_valid',False)),notify=publish,confirmed=notify,
                     actual_action=dict(fan_action=status.get('fan_action'),
                     pwm_counts=status.get('applied_pwm_counts'),load_receipt=status.get('load_receipt')),
                     protection_latched=bool(status.get('latched')),maintenance_test_flag=bool(status.get('test_mode')),
                     config_id=status.get('configuration_id'),frame_id=status.get('frame_id'),
                     sensor_quality=status.get('sensor_quality'),values_with_units=status.get('values_with_units'),
                     calibration_id=status.get('calibration_id'),model_id=status.get('model_id'),
                     bitstream_id=status.get('bitstream_id'))
        if not active:event['recovered_at_mono']=now
        if source=='MODEL':event['evidence_state']=status.get('model_evidence_state','UNKNOWN')
        if source=='MODEL' and status.get('model_admission_sha256'):
            event['model_admission_sha256']=status['model_admission_sha256']
        if source=='MODEL':event['fault_grade']=status.get('fault_grade')
        if source=='PREDICTION':event['maintenance']=status.get('maintenance')
        self.store.event(event)
        if active:self.active[key]=event
        else:self.active.pop(key,None)
