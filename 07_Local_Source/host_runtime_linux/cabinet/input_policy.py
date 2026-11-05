"""Versioned model-only encoding. Original words and displayed measurements stay intact.

An absent FG sample is unknown feedback, never an observed zero speed. The
negative sentinel is outside the physical RPM domain and requires retraining.
Neither a class prediction nor this policy can release hardware protection.
"""
FAULT_POLICY = 'FAULT_WINDOWS_FG_UNKNOWN_V1'
MISSING_RPM = -32768.0


def fault_policy(contract):
    policy = contract.get('input_policy', 'STABLE_RUN_V1')
    if policy not in ('STABLE_RUN_V1', FAULT_POLICY):
        raise ValueError('Unknown model input policy')
    return policy == FAULT_POLICY


def rpm_available(frame):
    return frame.header[14] > 0 and not frame.quality & 0x0800


def model_values(frame, contract):
    values = list(frame.values)
    if fault_policy(contract) and not rpm_available(frame):
        values[38] = MISSING_RPM
    return values


def semantics(contract):
    return 'STANDARDIZED_39_FG_UNKNOWN_V1' if fault_policy(contract) else 'STANDARDIZED_PHYSICAL_39'


def input_state(frame, contract):
    missing = fault_policy(contract) and not rpm_available(frame)
    return dict(input_policy=contract.get('input_policy', 'STABLE_RUN_V1'),
                rpm_measurement_available=not missing,
                feedback_state='FG_UNKNOWN_NOT_MEASURED_ZERO' if missing else 'FG_OBSERVED',
                protection_window=frame.header[19] in (7, 8))
