"""Shared CLI and HMI steady tracking criteria."""
MIN_SAMPLES = 40
MIN_SECONDS = 10.0
WINDOW_SECONDS = 10.25
MAX_GAP_SECONDS = 0.5
MAX_RELATIVE_ERROR = 0.02


def target_stable(targets):
    return bool(targets) and min(targets) > 0 and max(targets)-min(targets) <= max(1, min(targets)*0.01)
