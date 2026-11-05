"""Read-only industrial dashboard fields; no hardware access or control writes."""
import math


LABELS = ('normal', 'imbalance', 'stall', 'clog', 'overheat')


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def build_instrument(state, daily, sample, baseline):
    status = sample['status']
    words = sample.get('feature_words', [])
    fresh = state.get('frame_fresh') == '1' and state.get('frame_state') != 'REJECTED_TEST'
    vibration = daily.get('daily_rms_a_x', '--') != '--'
    result = {'panel_schema': 'industrial-v2', 'panel_vibration_valid': '1' if vibration else '0',
              'panel_source': 'TEST' if state.get('frame_state') == 'REJECTED_TEST' else 'REAL' if fresh else 'WAIT',
              'panel_sample_mode': state.get('frame_sample_mode', '--'),
              'panel_mode': str(status.get('mode', 'UNKNOWN')),
              'panel_level': str(status.get('alarm_level', '--')),
              'panel_model_valid': '0', 'panel_model_state': 'MODEL_UNAVAILABLE',
              'panel_model_note': '没有新鲜的真实模型结果',
              'panel_drive_status': '驱动闭锁' if status.get('hard_inhibit') else '驱动未闭锁',
              'panel_drive_note': '仅控制PWM，不控制电源',
              'panel_pi': 'PI调节' if status.get('fan_action') == 'PI' and status.get('configured') else 'PI未就绪',
              'panel_pwm': '--', 'panel_baseline_valid': '0', 'panel_baseline_limit': '--'}
    counts = number(status.get('applied_pwm_counts'))
    if (state.get('link') == 'FCB1 + EDG1 ABI OK' and type(status.get('applied_pwm_counts')) is int and
            counts is not None and 0 <= counts <= 4000):
        # FCB1 exposes normalized duty counts, not the 5000 PWM clock ticks.
        result['panel_pwm'] = '%.0f%%' % (counts / 4000 * 100)
    rates = [number(state.get('frame_rate_' + point)) for point in ('a', 'b')]
    valid_edges = (fresh and state.get('frame_contract_current') == '1' and len(words) == 17 and
                   all(type(edge) is int for edge in words[8:]) and
                   1 <= words[8] < words[-1] <= 513 and
                   all(words[index] < words[index + 1] for index in range(8, 16)))
    for band in range(8):
        text = '--'
        if valid_edges and all(rate is not None and rate > 0 for rate in rates):
            low = words[8 + band] * min(rates) / 1024
            high = (words[9 + band] - 1) * max(rates) / 1024
            text = '%.0f-%.0f' % (low, high)
        result['panel_band%d_hz' % band] = text
    active = set(status.get('active', []))
    latched = set(status.get('latched', []))
    validity = status.get('input_validity', {})
    qualified = bool(status.get('configured') and not status.get('test_mode') and
                     state.get('frame_state') != 'REJECTED_TEST')
    channels = (
        ('oc', {'OC_HARD'}, {'CURRENT_HIGH'}, validity.get('adc')),
        ('ot', {'TEMP_HARD'}, {'TEMP_WARN'}, validity.get('temperature')),
        ('stall', {'STALL_CORROBORATED'}, {'START_FAIL', 'FG_LOSS'}, validity.get('rpm') and validity.get('adc')),
        ('os', {'OVERSPEED'}, set(), validity.get('rpm')),
        ('vib', {'VIB_HARD'}, {'VIB_WARN', 'DIAG_LOSS'}, vibration),
        ('sensor', {'CURRENT_PROTECTION_LOST'}, {'TEMP_LOSS', 'AUX_LOSS', 'FG_LOSS'},
         all(validity.get(name) for name in ('rpm', 'adc', 'temperature', 'pressure')) and vibration))
    for name, faults, warnings, inputs_ready in channels:
        result['panel_pl_' + name] = ('LATCH' if (faults | warnings) & latched else
                                     'ALARM' if faults & active else 'WARN' if warnings & active else
                                     'CLEAR' if qualified and inputs_ready else 'UNKNOWN')
    for name in LABELS:
        result['panel_prob_' + name] = '--'
    model = sample.get('model')
    probabilities = model.get('probabilities') if isinstance(model, dict) else None
    model_valid = (fresh and state.get('frame_calibrated') == '1' and
                   state.get('frame_contract_current') == '1' and state.get('quality') == '0x00000000' and
                   isinstance(probabilities, list) and len(probabilities) == 5 and not model.get('test') and
                   model.get('diagnostic_state') not in ('REJECTED_CONFIDENCE', 'REJECTED_MARGIN', 'OUT_OF_DOMAIN') and
                   len(words) == 17 and
                   (model.get('feature_config_id'), model.get('calibration_id')) == tuple(words[:2]))
    if model_valid:
        values = [number(probability) for probability in probabilities]
        model_valid = all(value is not None and 0 <= value <= 1 for value in values)
        model_valid = model_valid and abs(sum(values) - 1) <= 0.02
        if model_valid:
            result['panel_model_valid'] = '1'
            backend = str(model.get('backend', 'EXTERNAL'))
            result['panel_model_state'] = backend + (' / 正式' if sample.get('model_formal') else ' / 观察')
            result['panel_model_note'] = '帧 #%s · %s ms' % (model.get('frame_id', '--'), model.get('inference_ms', '--'))
            for name, probability in zip(LABELS, values):
                result['panel_prob_' + name] = '%.2f' % (probability * 100)
    evidence = baseline.get('evidence', {})
    score = number(evidence.get('score'))
    limit = number(baseline.get('warning_score'))
    baseline_valid = (vibration and evidence.get('state') in ('CONSISTENT', 'CANDIDATE', 'DEVIATION') and
                      score is not None and score >= 0 and limit is not None and limit > 0)
    result['panel_baseline_valid'] = '1' if baseline_valid else '0'
    result['panel_baseline_limit'] = '%.2f' % limit if baseline_valid else '--'
    for group in ('amplitude', 'spectrum', 'ratio', 'process'):
        score = number(evidence.get('group_scores', {}).get(group))
        result['panel_group_' + group] = '%.2f' % score if baseline_valid and score is not None and score >= 0 else '--'
    return result
