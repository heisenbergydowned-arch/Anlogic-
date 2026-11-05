"""Relative vibration alarms from real FRM1 windows; never owns PWM output."""
import json
import math
from pathlib import Path

CONFIG = Path('/etc/cabinet/vibration-monitor.json')


class VibrationMonitor:
    def __init__(self, device_id, path=CONFIG):
        self.config = None
        self.error = None
        self.last_key = None
        self.deadline = 0
        self.held_until = 0
        self.held_level = 0
        self.events = 0
        self.last = {}
        try:
            c = json.loads(path.read_text(encoding='utf-8'))
            if c.get('schema') != 'cabinet-vibration-monitor-v1' or c.get('device_id') != device_id:
                raise ValueError('VIBRATION_CONFIG_IDENTITY')
            if c.get('enabled') is not True:
                return
            for name in ('a', 'b'):
                thresholds = c['thresholds'][name]
                low, high = thresholds['warning_rms'], thresholds['alarm_rms']
                if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high))
                        or not 0 < low < high <= 16):
                    raise ValueError('VIBRATION_THRESHOLD_INVALID')
            self.config = c
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.error = str(e)

    def observe(self, frame, status, diagnostics, now, context):
        base = dict(schema='cabinet-vibration-monitor-live-v1', enabled=self.config is not None,
                    source='REAL_FRM1_RELATIVE_RMS', control_authority='NONE',
                    alarm_can_stop_pwm=False, collector_boot=context, event_count=self.events)
        if self.config is None:
            return dict(base, valid=False, state='DISABLED', reason=self.error, deadline_ms=0)
        if frame is None:
            if now < self.deadline:
                return dict(self.last)
            return dict(base, valid=False, state='UNKNOWN', reason='WAITING_FRESH_VIBRATION_WINDOW', deadline_ms=0)
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        h = frame.header
        from .icm_diagnostics import age_diagnostics
        if isinstance(diagnostics, dict) and '_monotonic' in diagnostics:
            diagnostics = age_diagnostics(diagnostics, now)
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        sensors = diagnostics.get('sensors', [])
        age = ((status.get('uptime_ms', 0)-h[4]) & 0xffffffff) / 1000.
        good_pair = (diagnostics.get('state') == 'DIAGNOSTIC_ONLY' and diagnostics.get('test') is False
                     and isinstance(diagnostics.get('boot_id'), str) and context.startswith(diagnostics['boot_id']+'/')
                     and len(sensors) == 2 and {s.get('channel') for s in sensors} == {'A', 'B'}
                     and all(s.get('fresh') is True and s.get('error') is False
                             and s.get('config_verified') is True and s.get('config_bad_mask') == 0
                             for s in sensors)
                     and 0 <= diagnostics.get('snapshot_age_ms', 1e9) <= 1500)
        good = (not frame.test and h[11:13] == (1024, 1024) and h[21] == 100000000
                and not h[15] & ~0x3f00 and 0 <= age < 1 and good_pair
                and all(span > 0 and 3880 <= 1023*h[21]/span <= 4120 for span in h[9:11]))
        values = [frame.values[i] for i in (0, 1, 2, 17, 18, 19)]
        if not good or not all(math.isfinite(v) and 0 <= v <= 16 for v in values):
            return dict(base, valid=False, state='UNKNOWN', reason='VIBRATION_INPUT_INVALID', deadline_ms=0)
        key = (context, h[3])
        if key == self.last_key:
            return dict(self.last) if now < self.deadline else dict(base, valid=False, state='UNKNOWN', deadline_ms=0)
        if self.last_key is not None and self.last_key[0] != context:
            self.held_level = 0
            self.held_until = 0
        self.last_key = key
        self.deadline = now + 1-age
        rms = dict(a=math.sqrt(sum(v*v for v in values[:3])), b=math.sqrt(sum(v*v for v in values[3:])))
        level = max(2 if rms[k] >= self.config['thresholds'][k]['alarm_rms'] else
                    1 if rms[k] >= self.config['thresholds'][k]['warning_rms'] else 0 for k in rms)
        if level:
            if now >= self.held_until:
                self.events += 1
            self.held_level = max(level, self.held_level if now < self.held_until else 0)
            self.held_until = now+2
        elif now >= self.held_until:
            self.held_level = 0
        state = ('CLEAR', 'WARN', 'ALARM')[self.held_level]
        self.last = dict(base, valid=True, state=state, raw_level=level, frame_id=h[3],
                         deadline_ms=int(self.deadline*1000), event_count=self.events, rms=rms,
                         thresholds=self.config['thresholds'], reference=self.config['reference'],
                         process_quality_flags=h[15] & 0x0f00,
                         qualification='RELATIVE_BASELINE_ALARM_NOT_SENSOR_GAIN_CALIBRATION')
        return dict(self.last)


def panel_fields(document, now):
    if not isinstance(document, dict) or document.get('enabled') is not True:
        return {}
    valid = document.get('valid') is True and now*1000 < document.get('deadline_ms', 0)
    return dict(panel_pl_vib=document.get('state', 'UNKNOWN') if valid else 'UNKNOWN',
                panel_pl_vib_readiness='RELATIVE_MONITOR_ENABLED',
                panel_vibration_monitor_enabled='1',
                panel_vibration_monitor_source='REAL_FRM1_RELATIVE_RMS',
                panel_vibration_monitor_valid='1' if valid else '0',
                panel_vibration_monitor_deadline_ms=str(document.get('deadline_ms',0)) if valid else '0')
