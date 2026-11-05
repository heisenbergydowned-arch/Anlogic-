#!/usr/bin/env python3
"""Read-only Modbus RTU demonstration for the current cabinet FPGA."""
import argparse
import datetime
import json
from pathlib import Path
import struct
import time


def crc16(data):
    value = 0xffff
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xa001 if value & 1 else 0)
    return value


def request(unit=1, start=0, count=16):
    if not 1 <= unit <= 247 or not 0 <= start < 16 or not 1 <= count <= 16-start:
        raise ValueError('Invalid register range or unit')
    body = struct.pack('>BBHH', unit, 3, start, count)
    return body + struct.pack('<H', crc16(body))


def decode(packet, unit=1, start=0, count=16):
    if len(packet) < 5 or crc16(packet) != 0:
        raise ValueError('CRC or packet length error')
    if packet[0] != unit:
        raise ValueError('Wrong slave address')
    if packet[1] == 0x83 and len(packet) == 5:
        raise ValueError('Modbus exception %02X' % packet[2])
    if len(packet) != 5+2*count or packet[1:3] != bytes([3, 2*count]):
        raise ValueError('Wrong function, byte count or packet length')
    registers = dict(enumerate(struct.unpack('>%dH' % count, packet[3:-2]), start))
    result = {'registers': registers}
    if 4 in registers:
        meta = registers[4]
        result.update(mode=(meta >> 2) & 15, alarm_level=meta & 3,
                      fan_action=(meta >> 6) & 7, diagnostic_mode=bool(meta & (1 << 13)))
    if 5 in registers: result['pwm_percent'] = registers[5]/40.
    if 6 in registers: result['rpm_raw'] = registers[6]
    if 7 in registers:
        value = registers[7]
        result['temperature_C'] = (value-65536 if value & 32768 else value)/16.
    for first, name in [(0, 'active_alarm_bits'), (2, 'latched_alarm_bits'),
                        (8, 'current_magnitude_raw'), (10, 'configuration_id')]:
        if first in registers and first+1 in registers:
            result[name] = registers[first] | (registers[first+1] << 16)
    for reg, name in [(12, 'event_sequence_low16'), (13, 'lost_events_low16'),
                      (14, 'transport_bad_frames_low16'), (15, 'transport_busy_drops_low16')]:
        if reg in registers: result[name] = registers[reg]
    return result


def receive(port, unit, count, timeout):
    raw = bytearray()
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        raw.extend(port.read(max(1, min(port.in_waiting, 128))))
        for i in range(max(0, len(raw)-511), len(raw)-2):
            if raw[i] != unit: continue
            size = 5 if raw[i+1] == 0x83 else 5+2*count
            if raw[i+1] not in (3, 0x83) or len(raw)-i < size: continue
            packet = bytes(raw[i:i+size])
            if crc16(packet) == 0 and (packet[1] == 0x83 or packet[2] == 2*count):
                return packet, bytes(raw)
        if len(raw) > 512: del raw[:-512]
    raise ValueError('No valid reply within timeout; RX='+bytes(raw).hex(' '))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list-ports', action='store_true')
    parser.add_argument('--port', help='Explicit RS485 adapter, e.g. COM3 or /dev/cu.usbserial-210')
    parser.add_argument('--count', type=int, default=30, help='Number of requests, 0 runs until Ctrl+C')
    parser.add_argument('--interval', type=float, default=1.)
    parser.add_argument('--timeout', type=float, default=.3)
    parser.add_argument('--stopbits', type=int, choices=[1,2], default=2,
                        help='Current board verified with 8E2; 8E1 retained for diagnosis')
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--register-count', type=int, default=16)
    parser.add_argument('--output', type=Path)
    args=parser.parse_args()
    try:
        import serial
        import serial.tools.list_ports
    except ImportError:
        parser.exit(2,'Install dependency first: python -m pip install pyserial\n')
    if args.list_ports:
        for p in serial.tools.list_ports.comports(): print(p.device, p.description, p.hwid)
        return 0
    if not args.port: parser.error('Choose --port explicitly; use --list-ports first')
    if args.count < 0 or args.interval < .02 or not .02 <= args.timeout <= 5:
        parser.error('Invalid count, interval or timeout')
    if args.output is None:
        args.output=Path('rs485-demo-'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.jsonl')
    packet=request(start=args.start,count=args.register_count)
    print('READ ONLY | %s | 115200 8E%d | slave 1 | Ctrl+C stops' % (args.port,args.stopbits),flush=True)
    print('TX '+packet.hex(' ').upper(),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    total=ok=0
    with serial.Serial(args.port,115200,bytesize=8,parity='E',stopbits=args.stopbits,
                       timeout=.02,write_timeout=1) as port, args.output.open('w',encoding='utf-8') as log:
        time.sleep(.1)
        try:
            while args.count == 0 or total < args.count:
                begin=time.monotonic();total+=1
                row={'sequence':total,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     'port':args.port,'baud':115200,'format':'8E%d'%args.stopbits,'tx':packet.hex(' ')}
                port.reset_input_buffer();port.write(packet);port.flush()
                try:
                    reply,raw=receive(port,1,args.register_count,args.timeout)
                    values=decode(reply,start=args.start,count=args.register_count)
                    row.update(ok=True,rx=reply.hex(' '),raw_rx=raw.hex(' '),values=values,
                               elapsed_ms=round((time.monotonic()-begin)*1000,3))
                    ok+=1
                    print('[%03d] RX %s | CRC OK' % (total,reply.hex(' ').upper()),flush=True)
                    print('      RPM=%s  TEMP=%s C  PWM=%s%%  ALARM_LEVEL=%s  BAD_FRAMES=%s' % (
                        values.get('rpm_raw','--'),values.get('temperature_C','--'),values.get('pwm_percent','--'),
                        values.get('alarm_level','--'),values.get('transport_bad_frames_low16','--')),flush=True)
                except ValueError as error:
                    row.update(ok=False,error=str(error));print('[%03d] %s'%(total,error),flush=True)
                log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
                time.sleep(max(0,args.interval-(time.monotonic()-begin)))
        except KeyboardInterrupt: pass
    print('Valid replies: %d/%d; failures: %d; log: %s'%(ok,total,total-ok,args.output),flush=True)
    return 0 if total and total == ok else 1


if __name__ == '__main__': raise SystemExit(main())
