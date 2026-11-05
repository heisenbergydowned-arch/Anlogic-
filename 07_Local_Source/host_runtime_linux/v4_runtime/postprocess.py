"""Explicit five-class PS postprocessing, never an inference backend fallback."""
import math

from .bundle import fp32


EXECUTION = 'ALNPU_LOGITS_PS_SOFTMAX'
ALGORITHM = 'FP32_STABLE_SOFTMAX_TIES_TO_EVEN_V1'


def softmax_u8(logits, scale, zero):
    if type(logits) is not list or len(logits) != 5 or any(type(value) is not int or not 0 <= value <= 255 for value in logits):
        raise ValueError('Exactly five UINT8 logits required')
    scale = fp32(scale)
    if scale <= 0 or type(zero) is not int or not 0 <= zero <= 255:
        raise ValueError('Invalid PS Softmax quantization')
    values = [fp32((value-zero)*scale) for value in logits]
    maximum = max(values)
    values = [fp32(math.exp(fp32(value-maximum))) for value in values]
    total = 0.0
    for value in values:
        total = fp32(total+value)
    if total <= 0:
        raise ValueError('Invalid PS Softmax normalization')
    result = [round(fp32(fp32(value/total)/fp32(1/255))) for value in values]
    if any(not 0 <= value <= 255 for value in result):
        raise ValueError('PS Softmax output outside UINT8')
    return result
