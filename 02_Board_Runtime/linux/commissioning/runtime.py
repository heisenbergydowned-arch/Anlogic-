"""Readback binding for generated control parameters."""
from . import SOURCE

def read_control_words(io):
    before=io.read(0x24)
    words=[io.read(0x500+4*i) for i in range(24)]
    if words[1]!=before or io.read(0x24)!=before:raise RuntimeError('Control configuration changed during readback')
    return words

def validate_binding(config,control_words,feature_words):
    expected=config.get('commissioning')
    if expected is None:return
    if (expected.get('source')!=SOURCE or len(expected.get('evidence_sha256',''))!=64 or
            control_words!=expected.get('control_words') or feature_words!=expected.get('feature_words')):
        raise ValueError('COMMISSIONED_REGISTER_READBACK_MISMATCH_NO_ACTUATOR_COMMAND')
    if control_words[0]&15!=15 or not feature_words[2] or not feature_words[1]:
        raise ValueError('COMMISSIONED_QUALIFICATION_MISSING')
