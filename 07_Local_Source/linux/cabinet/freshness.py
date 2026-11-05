"""Age immutable snapshots without treating queue processing as acquisition."""
import math
import time


def finite_time(value):
    return type(value) in (int,float) and math.isfinite(value)


def aged_ms(state, key, *, now=None, require_snapshot=False):
    age=state.get(key)
    if not finite_time(age) or age<0:return None
    if 'snapshot_monotonic' not in state:
        return None if require_snapshot else age
    snapshot=state['snapshot_monotonic']
    now=time.monotonic() if now is None else now
    if not finite_time(snapshot) or not finite_time(now) or not 0<=snapshot<=now:return None
    return age+(now-snapshot)*1000
