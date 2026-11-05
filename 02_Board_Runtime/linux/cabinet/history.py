"""Bounded historical queries and lossless, device-scoped WAV1 replay."""
import csv
import io
import json
import math
import re
import time
from .waveform import checksum, validate_record
from .freshness import aged_ms


def finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite ' + name + ' required')
    return value


def signed16(value):
    value &= 65535
    return value - 65536 if value & 32768 else value


def replay(record):
    validate_record(record)
    header = record['header']
    clock = header[38]
    origin = min((row[2] | row[3] << 32 for rows in record['samples'] for row in rows), default=0)
    streams = []
    for rows in record['samples']:
        points = []
        previous = None
        for row in rows:
            ticks = row[2] | row[3] << 32
            delta = (ticks - origin) & 0xffffffffffffffff
            delta = delta - (1 << 64) if delta & (1 << 63) else delta
            points.append(dict(time_ms=delta * 1000 / clock,
                ticks=str(ticks), sequence=row[1] >> 16, quality=row[4],
                xyz=[signed16(row[0]), signed16(row[0] >> 16), signed16(row[1])],
                gap=previous is not None and ((row[1] >> 16) - previous) & 65535 != 1))
            previous = row[1] >> 16
        streams.append(points)
    return dict(schema='cabinet-waveform-replay-v1', raw=record, streams=streams,
                units='signed16_raw_counts', qualified=False, test=record['test'],
                alignment='independent_saved_64bit_ticks_no_resampling', sha256=checksum(record))


def csv_replay(document):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['sensor', 'time_ms', 'ticks', 'sequence', 'x_raw', 'y_raw', 'z_raw', 'quality', 'test'])
    for sensor, points in zip(['A', 'B'], document['streams']):
        for point in points:
            writer.writerow([sensor, point['time_ms'], point['ticks'], point['sequence']] + point['xyz'] + [point['quality'], document['test']])
    return stream.getvalue()


class History:
    def __init__(self, store, initialize=True):
        self.store = store
        if not initialize:
            return
        with store.transaction() as database:
            database.executescript('''
                CREATE TABLE IF NOT EXISTS history_samples(
                    id INTEGER PRIMARY KEY,device TEXT NOT NULL,recorded REAL NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS history_device_time ON history_samples(device,recorded,id);
                CREATE TABLE IF NOT EXISTS waveform_index(
                    id INTEGER PRIMARY KEY,device TEXT NOT NULL,boot TEXT NOT NULL,event_id INTEGER NOT NULL,
                    recorded REAL NOT NULL,record_id TEXT NOT NULL UNIQUE);
                CREATE INDEX IF NOT EXISTS waveform_device_time ON waveform_index(device,recorded,id);
            ''')

    def record(self, device, state, recorded=None):
        from .store import encode
        recorded = time.time() if recorded is None else finite(recorded, 'recording time')
        frame = state.get('frame') or {}
        status = state.get('status') or {}
        now=time.monotonic()
        frame_age=aged_ms(state,'frame_age_ms',now=now)
        status_age=aged_ms(state,'status_age_ms',now=now)
        valid = (state.get('link') == 'ONLINE' and state.get('test') is not True and
                 frame.get('test') is not True and type(frame.get('calibration_id')) is int and
                 frame['calibration_id'] > 0 and type(frame.get('quality')) is int and frame['quality'] == 0 and
                 type(frame_age) in (int, float) and math.isfinite(frame_age) and 0 <= frame_age <= 1000)
        status_fresh = (valid and type(status_age) in (int, float) and math.isfinite(status_age) and
                        0 <= status_age <= 1000)
        input_validity = status.get('input_validity') or {}
        temperature_age=aged_ms(dict(state,temp_age_ms=status.get('temp_age_ms')),'temp_age_ms',now=now)
        measurement_validity = dict(
            rpm=status_fresh and input_validity.get('rpm') is True,
            target_rpm=status_fresh,
            temperature=status_fresh and input_validity.get('temperature') is True and
                type(temperature_age) in (int, float) and math.isfinite(temperature_age) and 0 <= temperature_age <= 2000,
            current=valid, pressure=valid)
        values = frame.get('values') or {}
        metrics = dict(rpm=status.get('measured_rpm'), target_rpm=status.get('requested_rpm'),
                       temperature=(status['temp_raw_1_16_C'] / 16 if type(status.get('temp_raw_1_16_C')) is int else None),
                       current=values.get('current'), pressure=values.get('pressure'))
        measurement_validity = {key: bool(measurement_validity[key] and type(value) in (float, int) and math.isfinite(value))
                                for key, value in metrics.items()}
        metrics = {key: value if measurement_validity[key] else None
                   for key, value in metrics.items()}
        document = dict(recorded=recorded,recording_clock='PS_WALL_CLOCK_UNVERIFIED', boot_id=state.get('boot_id'), frame_id=frame.get('frame_id'),
                        calibration_id=frame.get('calibration_id'), quality=frame.get('quality'),
                        valid=any(measurement_validity.values()), frame_valid=valid,
                        test=state.get('test') is True, link=state.get('link'), values=metrics,
                        measurement_validity=measurement_validity,
                        measurement_source={key: 'FRM1_WINDOW' if key in ('current', 'pressure') else 'PL_STATUS' for key in metrics},
                        measurement_time_ms={key: frame.get('end_ms') if key in ('current', 'pressure') else status.get('uptime_ms') for key in metrics},
                        invalid_reasons={key: 'INVALID_OR_STALE_FRAME' if not valid else
                            'INVALID_STALE_OR_MISSING_MEASUREMENT' for key in metrics if not measurement_validity[key]})
        if self.store.storage_health()['state'] != 'OK':
            return False
        with self.store.transaction() as database:
            sequence = database.execute('INSERT INTO history_samples(device,recorded,payload) VALUES(?,?,?)',
                                        (device, recorded, '')).lastrowid
            database.execute('UPDATE history_samples SET payload=? WHERE id=?',
                             (self.store.pack(document,'history_samples',sequence),sequence))
            if sequence % 1000 == 0:
                database.execute('DELETE FROM history_samples WHERE id IN (SELECT id FROM history_samples WHERE device=? ORDER BY id DESC LIMIT -1 OFFSET 100000)', (device,))
        return True

    @staticmethod
    def window(start, end, after, limit):
        finite(start, 'start'); finite(end, 'end')
        if start > end or type(after) is not int or not 0 <= after < 2 ** 63 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Invalid history window or pagination')

    def query(self, device, start, end, after=0, limit=200, waveforms=False):
        self.window(start, end, after, limit)
        with self.store.lock:
            statement = ('SELECT i.id,i.device,i.boot,i.event_id,i.recorded,i.record_id FROM waveform_index i JOIN waveforms w ON i.record_id=w.record_id WHERE i.device=? AND i.recorded>=? AND i.recorded<=? AND i.id>? ORDER BY i.id LIMIT ?'
                         if waveforms else 'SELECT * FROM history_samples WHERE device=? AND recorded>=? AND recorded<=? AND id>? ORDER BY id LIMIT ?')
            rows = self.store.db.execute(statement,
                                        (device, start, end, after, limit + 1)).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for row in rows:
            if waveforms:
                document = dict(id=row[0], boot_id=row[2], event_id=row[3], recorded=row[4], record_id=row[5])
            else:
                document = dict(self.store.unpack(row[3],'history_samples',row[0]), id=row[0])
                if 'measurement_validity' not in document:
                    original_values = document.get('values') or {}
                    document.update(valid=False, frame_valid=None, legacy_validity_unverified=True,
                        unverified_legacy_values=original_values, values={name: None for name in original_values},
                        measurement_validity={name: False for name in original_values},
                        invalid_reasons={name: 'LEGACY_MEASUREMENT_VALIDITY_UNVERIFIED' for name in original_values})
            items.append(document)
        return dict(items=items, next_after=rows[-1][0] if more and rows else None, device_id=device)

    def get_waveform(self, device, identity):
        if type(identity) is not str or not re.fullmatch('[a-f0-9]{64}', identity):
            raise ValueError('Waveform SHA256 identity required')
        with self.store.lock:
            row = self.store.db.execute('SELECT w.payload FROM waveforms w JOIN waveform_index i ON w.record_id=i.record_id WHERE i.device=? AND i.record_id=?',
                                        (device, identity)).fetchone()
        if row is None:
            raise KeyError(identity)
        record = self.store.unpack(row[0],'waveforms',identity)
        if checksum(record) != identity:
            raise ValueError('Stored waveform checksum mismatch')
        return replay(record)

    def index_waveform(self, device, identity, record):
        validate_record(record)
        if checksum(record) != identity:
            raise ValueError('Waveform index checksum mismatch')
        with self.store.transaction() as database:
            old=database.execute('SELECT device FROM waveform_index WHERE record_id=?',(identity,)).fetchone()
            if old and old[0] != device:
                raise ValueError('Waveform belongs to another device')
            database.execute('INSERT OR IGNORE INTO waveform_index(device,boot,event_id,recorded,record_id) VALUES(?,?,?,?,?)',
                             (device,record['boot_id'],record['event_id'],time.time(),identity))
