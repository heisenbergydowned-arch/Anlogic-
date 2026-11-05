"""Two-level speed notices from fresh FG samples; never owns the fan output."""
import math


def validate_policy(policy, alarm_rpm):
    fields = {'warning_rpm', 'warning_hold_ms', 'warning_clear_rpm', 'recovery_ms', 'source'}
    if type(policy) is not dict or set(policy) != fields:
        raise ValueError('SPEED_ALARM_POLICY_SCHEMA')
    if (any(type(policy[k]) is not int for k in fields - {'source'}) or
            not 0 < policy['warning_clear_rpm'] < policy['warning_rpm'] < alarm_rpm or
            not 250 <= policy['warning_hold_ms'] <= 600000 or
            not 250 <= policy['recovery_ms'] <= 10000 or
            type(policy['source']) is not str or not 1 <= len(policy['source']) <= 160):
        raise ValueError('SPEED_ALARM_POLICY_INVALID')
    return dict(policy)


class SpeedAlarm:
    def __init__(self):
        self.identity = None
        self.last_stamp = self.last_received = None
        self.high_since = self.low_since = self.alarm_clear_since = None
        self.warning = self.alarm = False
        self.value = {'state': 'DISABLED'}

    def reset_evidence(self):
        self.high_since = self.low_since = self.alarm_clear_since = None
        self.warning = self.alarm = False

    def observe(self, status, now, policy, alarm_rpm, context):
        if policy is None:
            self.reset_evidence()
            self.identity = None
            self.value = {'state': 'DISABLED'}
            return dict(self.value)
        identity = (context, alarm_rpm, tuple(sorted(policy.items())))
        if identity != self.identity:
            self.identity = identity
            self.last_stamp = self.last_received = None
            self.reset_evidence()
        base = dict(policy=policy, alarm_rpm=alarm_rpm, pwm_changed=False)
        rpm, stamp = status.get('measured_rpm'), status.get('uptime_ms')
        valid = (status.get('input_validity', {}).get('rpm') is True and
                 type(rpm) is int and 0 <= rpm <= 32767 and
                 type(stamp) is int and 0 <= stamp <= 0xffffffff and
                 type(now) in (int, float) and math.isfinite(now))
        if not valid:
            self.reset_evidence()
            self.last_stamp = self.last_received = None
            self.value = dict(base, state='UNKNOWN', rpm=None, elapsed_ms=0)
            return dict(self.value)
        if self.last_stamp is not None:
            delta = (stamp - self.last_stamp) & 0xffffffff
            age = now - self.last_received
            if delta == 0 and 0 <= age <= 1:
                # Re-reading one FPGA sample cannot supply hold-time evidence.
                return dict(self.value)
            if delta == 0 or delta > 1000 or not 0 <= age <= 1:
                self.reset_evidence()
                if delta == 0:
                    self.value = dict(base, state='UNKNOWN', rpm=None, elapsed_ms=0)
                    return dict(self.value)
        self.last_stamp, self.last_received = stamp, now
        # Once 4500 RPM starts confirmation, allow normal FG jitter inside
        # the configured 100 RPM hysteresis band. A single 4499 sample must
        # not postpone a sustained full-speed notice forever.
        confirming = self.high_since is not None and rpm >= policy['warning_clear_rpm']
        if rpm >= policy['warning_rpm'] or confirming:
            self.low_since = None
            if self.high_since is None:
                self.high_since = now
            if (now - self.high_since) * 1000 >= policy['warning_hold_ms']:
                self.warning = True
        else:
            self.high_since = None
            if self.warning and rpm < policy['warning_clear_rpm']:
                if self.low_since is None:
                    self.low_since = now
                if (now - self.low_since) * 1000 >= policy['recovery_ms']:
                    self.warning = False
            else:
                self.low_since = None
        if rpm > alarm_rpm:
            self.alarm = True
            self.alarm_clear_since = None
        elif self.alarm:
            if self.alarm_clear_since is None:
                self.alarm_clear_since = now
            if (now - self.alarm_clear_since) * 1000 >= policy['recovery_ms']:
                self.alarm = False
        elapsed = 0 if self.high_since is None else max(0, round((now - self.high_since) * 1000))
        state = ('ALARM' if self.alarm else 'WARNING' if self.warning else
                 'PENDING' if self.high_since is not None else 'NORMAL')
        self.value = dict(base, state=state, rpm=rpm, elapsed_ms=elapsed)
        return dict(self.value)
