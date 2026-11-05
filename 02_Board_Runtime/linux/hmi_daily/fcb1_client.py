"""FCB1 register client, 115200 8N1. No serial access unless --port is supplied.

One client owns the command staging registers at a time. Status/events are
native ADC/DS/FG units; this tool does not turn uncalibrated codes into amperes.
"""
import argparse
import json
import struct
import time
from pathlib import Path

ERRORS = {0: 'OK', 1: 'address/format', 2: 'configuration/range',
          3: 'local permission required', 4: 'sequence mismatch',
          5: 'critical input invalid', 6: 'latched protection',
          7: 'heartbeat expired', 8: 'local manual lease owns actuator'}
FAULTS = ['OC_HARD', 'CURRENT_HIGH', 'TEMP_WARN', 'TEMP_HARD',
          'CURRENT_PROTECTION_LOST', 'TEMP_LOSS', 'FG_LOSS', 'START_FAIL',
          'STALL_CORROBORATED', 'OVERSPEED', 'VIB_WARN', 'VIB_HARD',
          'PS_LOSS', 'CMD_EXPIRED', 'DIAG_LOSS', 'AUX_LOSS',
          'CONFIG_UNQUALIFIED', 'TRACK_ERROR', 'STOP_UNCONFIRMED',
          'SOFT_PS', 'SOFT_EXPIRED']
MODES = ['BOOT', 'READY_OFF', 'STARTING', 'RUN', 'TRANSIENT',
         'STOPPING', 'MAINTENANCE', 'LOCKED', 'FALLBACK']
FAN_ACTIONS = ['PI', 'BOOST', 'LIMIT', 'INHIBIT', 'FALLBACK', 'OFF', 'MANUAL', 'STARTUP']


def crc16(data):
    c = 0xffff
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ (0x1021 if c & 0x8000 else 0)) & 0xffff
    return c


def request_packet(op, seq, addr, value=0):
    if op not in (0, 1) or not 0 <= seq <= 0xffff or not 0 <= addr <= 0xffff or addr % 4:
        raise ValueError('Invalid aligned FCB1 request')
    if not 0 <= value <= 0xffffffff:
        raise ValueError('Register value must be uint32')
    body = struct.pack('<BBBBHHI', 0xc3, 0x51, 1, op, seq, addr, value)
    return body + struct.pack('<H', crc16(body))


def extract_reply(buffer, seq, addr, op):
    """Consume a stream containing legacy debug frames and corrupt replies."""
    while True:
        i = buffer.find(b'\xc3\x52')
        if i < 0:
            if len(buffer) > 1:
                del buffer[:-1]
            return None
        if i:
            del buffer[:i]
        if len(buffer) < 16:
            return None
        frame = bytes(buffer[:16])
        if crc16(frame[:14]) != struct.unpack_from('<H', frame, 14)[0]:
            del buffer[0]
            continue
        del buffer[:16]
        _, _, version, error, got_seq, got_addr, data, echo_op, reserved = struct.unpack('<BBBBHHIBB', frame[:14])
        if version == 1 and reserved == 0 and (got_seq, got_addr, echo_op) == (seq, addr, op):
            return data, error


class Client:
    def __init__(self, port, timeout=0.8):
        try:
            import serial
        except ImportError as e:
            raise RuntimeError('Install pyserial in this Python environment before using --port') from e
        self.serial = serial.Serial(port, 115200, timeout=0.03, write_timeout=1,
                                    bytesize=8, parity='N', stopbits=1, rtscts=False, dsrdtr=False)
        self.seq = 0
        self.timeout = timeout
        self.buffer = bytearray()
        self.command_id = None

    def close(self):
        self.serial.close()

    def transaction(self, op, addr, data=0):
        self.seq = (self.seq + 1) & 0xffff
        packet = request_packet(op, self.seq, addr, data)
        # An identical execute retry retains the same staged command ID/payload;
        # the RTL caches its result and must not extend a lease or pop again.
        for _ in range(3):
            self.serial.write(packet)
            self.serial.flush()
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                reply = extract_reply(self.buffer, self.seq, addr, op)
                if reply is not None:
                    value, error = reply
                    if error:
                        raise RuntimeError(f'CSR 0x{addr:04x}: {error} {ERRORS.get(error, "unknown")}')
                    return value
                # Read available bytes, or wait for the first byte. Waiting for
                # a full 256-byte read would add the port timeout to each tiny
                # transaction and could itself consume short command leases.
                self.buffer.extend(self.serial.read(max(1, min(self.serial.in_waiting, 256))))
        raise TimeoutError(f'No valid FCB1 reply for 0x{addr:04x}; check FPGA build/UART wiring')

    def read(self, addr):
        return self.transaction(0, addr)

    def write(self, addr, value):
        return self.transaction(1, addr, value)

    def identify(self):
        if self.read(0) != 0x46434231 or self.read(4) != 0x00010000:
            raise RuntimeError('FPGA does not implement FCB1 version 1')

    def command(self, opcode, payload=0):
        if self.command_id is None:
            self.command_id = self.read(0x20)
        self.command_id = (self.command_id + 1) & 0xffffffff
        self.write(0x0c, self.command_id)
        self.write(0x10, payload)
        return self.write(0x14, opcode)

    def status(self):
        self.command(7)
        return decode_status([self.read(0x700 + i * 4) for i in range(32)])


def names(mask):
    return [name for i, name in enumerate(FAULTS) if mask & (1 << i)]


def decode_status(words):
    meta = words[2]
    mode = (meta >> 2) & 15
    signed_temp = (words[23] & 0xffff) - (0x10000 if words[23] & 0x8000 else 0)
    return {'uptime_ms': words[1], 'mode': MODES[mode] if mode < len(MODES) else mode,
            'alarm_level': meta & 3, 'fan_action': FAN_ACTIONS[(meta >> 6) & 7],
            'reserved_meta_bits': (meta >> 9) & 3,
            'test_mode': bool(meta & 0x2000), 'silenced': bool(meta & 0x800),
            'acknowledged': bool(meta & 0x1000), 'active': names(words[3]), 'latched': names(words[4]),
            'seen_since_boot': names(words[5]), 'applied_pwm_counts': words[7] & 0xffff,
            'requested_rpm': words[8] >> 16, 'measured_rpm': words[8] & 0xffff,
            'ramped_rpm': words[9] >> 16, 'configuration_id': words[18],
            'event_sequence': words[15], 'lost_events': words[16], 'event_count': words[17],
            'current_distance_raw_code': words[21], 'temp_raw_1_16_C': signed_temp,
            'adc_age_ms': words[10], 'temp_age_ms': words[11], 'rpm_age_ms': words[12],
            'heartbeat_age_ms': words[13], 'target_age_ms': words[14],
            'uart_bad_frames': words[28], 'uart_busy_drops': words[29], 'raw_words': words}


def pack_config(config):
    if config.get('schema') != 'FCB1-config-v1':
        raise ValueError('Configuration schema must be FCB1-config-v1')
    qualifiers = config['qualifications']
    if set(qualifiers) != {'current', 'temperature', 'actuator', 'pi', 'vibration'}:
        raise ValueError('Qualification keys must match the FCB1 template exactly')
    flags = sum((1 << i) for i, key in enumerate(['current', 'temperature', 'actuator', 'pi', 'vibration'])
                if qualifiers[key] is True)
    if any(type(v) is not bool for v in qualifiers.values()):
        raise ValueError('Qualification flags must be booleans')
    if flags and (config.get('calibration_confirmed') is not True or not config.get('calibration_evidence')):
        raise ValueError('Qualified rules require calibration_confirmed=true and calibration_evidence')
    def field(name, bits=16, signed=False, required=True):
        x = config.get(name)
        if x is None and not required:
            x = 0
        low = -(1 << (bits - 1)) if signed else 0
        high = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
        if type(x) is not int or not low <= x <= high:
            raise ValueError(f'{name} requires an integer in [{low}, {high}]')
        return x & ((1 << bits) - 1)
    def pair(lo, hi, lo_signed=False, hi_signed=False, required=True):
        return field(lo, signed=lo_signed, required=required) | (field(hi, signed=hi_signed, required=required) << 16)
    cfg_id = field('config_id', 32)
    if cfg_id == 0:
        raise ValueError('Use a new, nonzero configuration ID')
    result = [flags, cfg_id, pair('startup_duty', 'fallback_duty'), pair('boost_duty', 'limit_duty'),
              pair('duty_min', 'duty_max'), pair('rpm_min', 'rpm_max'),
              pair('kp_q8', 'ki_q8', required=bool(flags & 8)),
              pair('current_zero', 'current_high', lo_signed=True, required=bool(flags & 1)),
              pair('current_hard', 'current_recover', required=bool(flags & 1)),
              pair('temp_warning', 'temp_hard', lo_signed=True, hi_signed=True, required=bool(flags & 2)),
              field('temp_recover', signed=True, required=bool(flags & 2)) |
              (field('vibration_limit', required=bool(flags & 16)) << 16),
              field('vibration_hard', required=bool(flags & 16)) | (field('fg_pulses_per_revolution', 8) << 16)]
    for lo, hi in [('target_slew', 'tracking_error'), ('adc_age_ms', 'temp_age_ms'),
                   ('fg_age_ms', 'recovery_ms'), ('startup_ms', 'transient_ms'),
                   ('stop_ms', 'manual_lease_ms'), ('heartbeat_ms', 'target_lease_ms'),
                   ('current_confirm_ms', 'temp_confirm_ms'), ('tracking_confirm_ms', 'vibration_confirm_ms'),
                   ('silence_ms', 'soft_lease_ms')]:
        result.append(pair(lo, hi))
    result.extend([field('fg_period_min_clocks', 32), field('fg_period_max_clocks', 32),
                   field('overspeed_hard_rpm', required=bool(flags & 4))])
    assert len(result) == 24
    return result


def selftest():
    assert crc16(b'123456789') == 0x29b1
    assert len(request_packet(0, 0x1234, 0)) == 14
    body = struct.pack('<BBBBHHIBB', 0xc3, 0x52, 1, 0, 0x1234, 0, 0x46434231, 0, 0)
    reply = body + struct.pack('<H', crc16(body))
    stream = bytearray(b'\x55\xa5' + bytes(75) + reply[:-1])
    assert extract_reply(stream, 0x1234, 0, 0) is None
    stream.extend(reply[-1:])
    assert extract_reply(stream, 0x1234, 0, 0) == (0x46434231, 0)
    # Lost response: transport retry must keep exactly the same packet. It must
    # not increment a command ID or replace the command payload on retransmit.
    class LostReplyPort:
        def __init__(self): self.writes=[];self.rx=bytearray()
        @property
        def in_waiting(self): return len(self.rx)
        def write(self, data):
            self.writes.append(data)
            if len(self.writes)==2:
                _,_,ver,op,seq,addr,value=struct.unpack('<BBBBHHI',data[:12])
                b=struct.pack('<BBBBHHIBB',0xc3,0x52,ver,0,seq,addr,value,op,0)
                self.rx.extend(b+struct.pack('<H',crc16(b)))
        def flush(self): pass
        def read(self, n):
            data=bytes(self.rx[:n]);del self.rx[:n];return data
    client=object.__new__(Client);client.serial=LostReplyPort();client.seq=0;client.timeout=0.005;client.buffer=bytearray()
    assert client.transaction(1,0x14,3)==3
    assert len(client.serial.writes)==2 and client.serial.writes[0]==client.serial.writes[1]
    corrupt = bytearray(reply); corrupt[8] ^= 1
    stream = corrupt + reply
    assert extract_reply(stream, 0x1234, 0, 0) == (0x46434231, 0)
    template = json.loads((Path(__file__).parents[1] / 'config_unqualified.template.json').read_text('utf-8'))
    template['config_id'] = 1
    words = pack_config(template)
    assert words[0] == 0 and words[2] == 0x07d007d0 and words[17] == 0x03e803e8
    template['qualifications']['current'] = True
    try:
        pack_config(template)
    except ValueError:
        pass
    else:
        raise AssertionError('Uncalibrated protection must not be marked qualified')
    print('ALL PASS control_cli CRC/stream/lost-reply retry/configuration selftest (no serial access)')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', help='Actual PL debug UART port, e.g. COM6; only this option enables serial access')
    sub = ap.add_subparsers(dest='action', required=True)
    sub.add_parser('selftest'); sub.add_parser('status'); sub.add_parser('heartbeat')
    p = sub.add_parser('read'); p.add_argument('address', type=lambda x: int(x, 0))
    p = sub.add_parser('packet'); p.add_argument('address', type=lambda x: int(x, 0)); p.add_argument('--write', type=lambda x: int(x, 0))
    p = sub.add_parser('configure'); p.add_argument('file', type=Path)
    p = sub.add_parser('target'); p.add_argument('rpm', type=int); p.add_argument('--hold-seconds', type=float, default=0)
    sub.add_parser('stop'); sub.add_parser('ack'); sub.add_parser('events')
    args = ap.parse_args()
    if args.action == 'selftest':
        selftest(); return
    if args.action == 'packet':
        print(request_packet(int(args.write is not None), 1, args.address, args.write or 0).hex(' ')); return
    config_words = pack_config(json.loads(args.file.read_text('utf-8-sig'))) if args.action == 'configure' else None
    if not args.port:
        raise ValueError('--port is required; no SD card or FPGA programming is performed by this tool')
    client = Client(args.port)
    try:
        client.identify()
        if args.action == 'status':
            result = client.status()
        elif args.action == 'read':
            result = {'address': hex(args.address), 'value': hex(client.read(args.address))}
        elif args.action == 'configure':
            for i, word in enumerate(config_words):
                client.write(0x300 + i * 4, word)
            client.write(0x18, 0x434f4d54)
            actual = [client.read(0x500 + i * 4) for i in range(24)]
            if actual != config_words:
                raise RuntimeError('Committed configuration readback mismatch')
            result = {'committed_id': actual[1], 'qualification_flags': actual[0]}
        elif args.action in ('heartbeat', 'stop', 'target'):
            if args.action == 'target' and (not 1 <= args.rpm <= 65535 or args.hold_seconds < 0):
                raise ValueError('Target must be uint16 > 0 and hold duration nonnegative')
            client.command(3)
            if args.action == 'stop': client.command(2)
            if args.action == 'target':
                leases = client.read(0x544)
                lease = min(leases & 0xffff, leases >> 16)
                if args.hold_seconds and lease < 100:
                    raise ValueError('UART continuous control requires both leases >=100 ms; use AXI for shorter leases')
                client.command(1, args.rpm)
                until = time.monotonic() + args.hold_seconds
                while time.monotonic() < until:
                    time.sleep(min(lease / 4000, max(0, until - time.monotonic())))
                    if time.monotonic() >= until: break
                    client.command(3); client.command(1, args.rpm)
            result = client.status()
            if args.action == 'target':
                result['after_exit'] = 'No further target/heartbeat renewal: PL lease timeout selects fallback'
        elif args.action == 'ack':
            client.command(4, client.read(0x13c)); result = client.status()
        else:
            count = client.read(0x144); result = []
            for _ in range(count):
                words = [client.read(0x80 + i * 4) for i in range(8)]
                result.append({'sequence': words[0], 'uptime_ms': words[1],
                               'active': names(words[2]), 'latched': names(words[3]), 'words': words})
                client.command(8, words[0])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        client.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('FCB1 ERROR: ' + str(e)); raise SystemExit(1)
