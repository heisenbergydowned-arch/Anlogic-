"""Use the same environmental math in the collector and standalone diagnostics."""
from hmi_daily.cabinet.environment import (
    ENVIRONMENT_CAPABILITY, MAX_AGE_MS, HARDWARE_PROFILE, INSTALLED_ENVIRONMENT_SENSORS,
    age_environment, compensate_bmp280, decode_environment,
    display_fields, read_environment, time, unavailable,
)
