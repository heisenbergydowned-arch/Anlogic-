"""Collector-owned output boundary for normal-reference inference; no hardware I/O.

FRM1 words 5..8 contain the union of both real sample windows in acquisition
clock cycles. That counter and FCB1 uptime share the same clock and reset.
An entire sample window must start after the first observed safe status, not
merely finish after a trial. Millisecond rounding is accounted for explicitly.
"""

SCHEMA = 'cabinet-normal-reference-output-v1'
MASK = 0xffffffff
HALF = 0x80000000


def uint32(value):
    return type(value) is int and 0 <= value <= MASK


def output_reason(status, require_zero=False):
    if (type(status) is not dict or type(status.get('configured')) is not bool
            or type(status.get('hard_inhibit')) is not bool
            or type(status.get('test_mode')) is not bool or type(status.get('mode')) is not str
            or not uint32(status.get('uptime_ms'))
            or not uint32(status.get('applied_pwm_counts'))
            or status['applied_pwm_counts'] > 4000
            or not uint32(status.get('requested_rpm'))
            or status['requested_rpm'] > 65535):
        return 'OUTPUT_STATUS_UNAVAILABLE'
    # Configured RUN profiles keep their existing model/context contracts.
    # An unconfigured output must never masquerade as the inhibited baseline.
    if (require_zero or not status['configured'] or status['test_mode']
            or status['mode'] in ('STOPPING', 'READY_OFF', 'LOCKED')) and (
            status['hard_inhibit'] is not True or status['applied_pwm_counts'] != 0
            or status['requested_rpm'] != 0):
        return 'OUTPUT_OUTSIDE_REFERENCE'
    return None


def bench_reason(bench):
    if type(bench) is not dict or bench.get('controls_enabled') is not False:
        return 'BENCH_STATE_UNAVAILABLE_OR_ACTIVE'
    state = bench.get('state')
    if state == 'IDLE':
        return None
    if state in ('COMPLETED', 'STOPPED', 'REJECTED'):
        if (bench.get('output_stop_confirmed') is True
                and type(bench.get('applied_bench_pwm_counts')) is int
                and bench['applied_bench_pwm_counts'] == 0):
            return None
        if bench.get('output_never_applied') is True:
            return None
        return 'BENCH_STOP_UNCONFIRMED'
    return 'BENCH_BUSY_OR_UNCONFIRMED'


def window_start(header, uptime):
    """Validate the physical cycle interval, including uint32 uptime wrap."""
    if (type(header) not in (list, tuple) or len(header) != 32
            or any(not uint32(v) for v in header) or not uint32(uptime)
            or header[21] != 100000000):
        raise ValueError('REFERENCE_WINDOW_TIME_UNAVAILABLE')
    start = header[5] | (header[6] << 32)
    end = header[7] | (header[8] << 32)
    span = max(header[9], header[10])
    if (not start or end < start or not span or header[25] > 25000
            or not span <= end - start <= span + header[25]
            or ((uptime - (end // 100000)) & MASK) > 1000):
        raise ValueError('REFERENCE_WINDOW_TIME_UNAVAILABLE')
    return start


def require_after_boundary(start, boundary, uptime):
    if (type(start) is not int or not 0 < start < 1 << 64
            or not uint32(boundary) or not uint32(uptime)
            or ((uptime - boundary) & MASK) >= HALF):
        raise ValueError('REFERENCE_RECOVERY_BOUNDARY_UNAVAILABLE')
    # A status at millisecond B was read before B+1. Requiring the window's
    # integer start to be >= B+1 excludes the entire uncertain millisecond.
    distance = ((start // 100000) - boundary) & MASK
    if not 0 < distance < HALF or ((uptime - (start // 100000)) & MASK) >= HALF:
        raise ValueError('REFERENCE_WAIT_FULL_POST_TRIAL_WINDOW')


class NormalReferenceGuard:
    """Only Service.io_loop calls update; subscribers receive immutable copies."""

    def __init__(self):
        self.boot = None
        self.boundary = None
        self.ready = False
        self.last_uptime = None
        self.bench_identity = None
        self.bench_state = None
        self.wait_after_uptime = None
        self.profile = None

    def update(self, boot, status, bench, frame=None):
        if boot != self.boot:
            self.__init__()
            self.boot = boot
        uptime = status.get('uptime_ms') if type(status) is dict else None
        reason = output_reason(status) or bench_reason(bench)
        if not isinstance(boot, str) or not boot:
            reason = 'REFERENCE_BOOT_UNAVAILABLE'
        if (uint32(uptime) and self.last_uptime is not None
                and ((uptime - self.last_uptime) & MASK) >= HALF):
            reason = 'REFERENCE_STATUS_CLOCK_REORDERED'
        identity = bench.get('id') if type(bench) is dict else None
        bench_state = bench.get('state') if type(bench) is dict else None
        transition = identity != self.bench_identity or bench_state != self.bench_state
        profile = tuple(status.get(k) for k in ('configured','mode','test_mode')) if type(status) is dict else None
        if profile != self.profile:
            self.boundary = None
            self.ready = False
        self.profile = profile
        if identity != self.bench_identity:
            self.boundary = None
            self.ready = False
        # bench.poll runs after the FCB1 status read. A newly observed terminal
        # readback must not reuse that pre-stop status as the recovery boundary.
        if transition and bench_state in ('COMPLETED', 'STOPPED', 'REJECTED'):
            self.boundary = None
            self.ready = False
            self.wait_after_uptime = uptime if uint32(uptime) else None
        self.bench_identity = identity
        self.bench_state = bench_state
        self.last_uptime = uptime if uint32(uptime) else None
        if reason:
            self.boundary = None
            self.ready = False
        else:
            if self.wait_after_uptime is not None and 0 < ((uptime-self.wait_after_uptime)&MASK) < HALF:
                self.wait_after_uptime = None
            if self.boundary is None and self.wait_after_uptime is None:
                self.boundary = uptime
            if self.boundary is not None and ((uptime-self.boundary)&MASK) >= HALF-1000:
                # uint32 ordering is only unambiguous within half a cycle.
                # Re-prove a full window before that limit, retaining the 1 s
                # maximum accepted frame age; do not leave an ancient boundary
                # that rejects healthy inference forever after 24.8 days.
                self.boundary = uptime
                self.ready = False
            if frame is not None and self.boundary is not None:
                try:
                    start = window_start(frame.header, uptime)
                    require_after_boundary(start, self.boundary, uptime)
                    self.ready = True
                except (AttributeError, ValueError):
                    pass
        return dict(schema=SCHEMA, boot=boot,
                    state='BLOCKED' if reason else ('IDLE' if self.ready else 'WAIT_FULL_WINDOW'),
                    reason=reason or (None if self.ready else ('REFERENCE_WAIT_POST_TRIAL_STATUS'
                        if self.wait_after_uptime is not None else 'REFERENCE_WAIT_FULL_POST_TRIAL_WINDOW')),
                    safe_since_uptime_ms=self.boundary, status_uptime_ms=uptime,
                    bench_state=bench.get('state') if type(bench) is dict else None,
                    bench_id=identity)
