"""Read-only industrial dashboard fields; no hardware access or control writes."""
import math


LABELS = ('normal', 'imbalance', 'stall', 'clog', 'overheat')


def protection_fields(state, sample, vibration):
    """Keep input availability separate from the qualification of protection."""
    status = sample['status']
    active, latched = set(status.get('active', [])), set(status.get('latched', []))
    validity = status.get('input_validity', {})
    real = (state.get('link') == 'FCB1 + EDG1 ABI OK' and
            state.get('frame_state') != 'REJECTED_TEST')
    qualified = status.get('configured') is True and status.get('test_mode') is False
    channels = (
        ('oc', {'OC_HARD'}, {'CURRENT_HIGH'}, validity.get('adc')),
        ('ot', {'TEMP_HARD'}, {'TEMP_WARN'}, validity.get('temperature')),
        ('stall', {'STALL_CORROBORATED'}, {'START_FAIL', 'FG_LOSS'}, validity.get('rpm') and validity.get('adc')),
        ('os', {'OVERSPEED'}, set(), validity.get('rpm')),
        ('vib', {'VIB_HARD'}, {'VIB_WARN', 'DIAG_LOSS'}, vibration),
        ('sensor', {'CURRENT_PROTECTION_LOST'}, {'TEMP_LOSS', 'AUX_LOSS', 'FG_LOSS'},
         all(validity.get(name) is True for name in ('rpm', 'adc', 'temperature', 'pressure')) and vibration))
    result = {'panel_protection_ready': '1' if real and qualified else '0'}
    partial_configuration = False
    for name, faults, warnings, ready in channels:
        qualifications=status.get('protection_qualifications')
        channel_qualified=qualified
        parameters_present = status.get('configured') is True
        if isinstance(qualifications,dict):
            required={'oc':('current',),'ot':('temperature',),'stall':('current','actuator'),
                      'os':('actuator',),'vib':('vibration',),'sensor':()}[name]
            flags_present = all(qualifications.get(key) is True for key in required)
            channel_qualified=qualified and flags_present
            parameters_present = parameters_present and flags_present
            partial_configuration = partial_configuration or not flags_present
        # This explains an unready protection channel, not sensor unit calibration
        # or NPU training. Keep the existing fault/validity/color decisions below.
        result['panel_pl_' + name + '_readiness'] = (
            'UNKNOWN' if not real or type(status.get('configured')) is not bool else
            'CONFIGURATION_REQUIRED' if not parameters_present else
            'CONTROL_NOT_STARTED' if status.get('test_mode') is True else
            'READY' if status.get('test_mode') is False else 'UNKNOWN')
        result['panel_pl_' + name] = (
            'UNKNOWN' if not real else
            'LATCH' if (faults | warnings) & latched else
            'ALARM' if faults & active else 'WARN' if warnings & active else
            'UNKNOWN' if not ready else
            'CLEAR' if channel_qualified or name == 'sensor' else 'UNREADY')
    result['panel_protection_scope'] = (
        'UNKNOWN' if not real or type(status.get('configured')) is not bool else
        'CONFIGURATION_REQUIRED' if not status['configured'] else
        'PARTIAL_CONFIGURATION_REQUIRED' if partial_configuration else
        'CONTROL_NOT_STARTED' if status.get('test_mode') is True else
        'READY' if status.get('test_mode') is False else 'UNKNOWN')
    return result


def monitor_fields(state, sample):
    # Called only after independent A/B evidence and the whole-window gate.
    vibration = state.get('panel_raw_features_valid') == '1'
    result = protection_fields(state, sample, vibration)
    status = sample['status']
    static_flags = {'CONFIG_UNQUALIFIED'} if not status.get('configured') else set()
    if (not status.get('configured') and status.get('test_mode') and status.get('hard_inhibit')
            and status.get('applied_pwm_counts') == 0 and status.get('requested_rpm') == 0):
        static_flags.add('STOP_UNCONFIRMED')
    active = set(status.get('active', []))
    hardware_warning = bool(active - static_flags) or (status.get('alarm_level', 0) > 0 and not active)
    if state.get('ui_severity') == '3' or state.get('frame_state') == 'REJECTED_TEST':
        return result
    if status.get('alarm_level', 0) >= 2 or status.get('latched') or any(value in ('ALARM', 'LATCH') for value in result.values()):
        result.update(ui_severity='3', ui_banner_title='硬件保护报警',
                      ui_banner_note='请检查右侧保护面板与现场设备状态')
    elif sample.get('control',{}).get('binding_error'):
        result.update(ui_severity='2',ui_banner_title='控制参数读回不匹配',
                      ui_banner_note='控制指令已停止；请恢复本机已保存参数')
    elif result['panel_pl_sensor'] == 'UNKNOWN':
        result.update(ui_severity='2', ui_banner_title='传感器数据不完整',
                      ui_banner_note='检查无效或过期输入，不能判为正常运行')
    elif any(value == 'WARN' for value in result.values()):
        result.update(ui_severity='2', ui_banner_title='设备预警，请检查',
                      ui_banner_note='请检查右侧保护面板与现场设备状态')
    elif hardware_warning:
        result.update(ui_severity='2', ui_banner_title='设备预警，请检查',
                      ui_banner_note='请检查右侧保护面板与现场设备状态')
    elif result['panel_protection_scope'] in ('CONFIGURATION_REQUIRED', 'PARTIAL_CONFIGURATION_REQUIRED'):
        # Keep commissioning readiness visible while the separate NPU panel
        # reports fresh advisory results. A missing result cannot change readiness.
        title = ('保护阈值待配置' if result['panel_protection_scope'] == 'CONFIGURATION_REQUIRED'
                 else '保护部分待配置')
        result.update(ui_severity='1', ui_banner_title=title,
                      ui_banner_note='NPU实推理不替代控制参数配置与闭环验证')
    elif state.get('panel_classifier_valid') == '1' and state.get('panel_classifier_label') not in ('normal', 'uncertain'):
        result.update(ui_severity='2', ui_banner_title='NPU工况分类预警',
                      ui_banner_note=state.get('panel_model_note','请检查当前工况'))
    elif state.get('panel_classifier_valid') == '1' and state.get('panel_classifier_label') == 'uncertain':
        result.update(ui_severity='2', ui_banner_title='NPU工况尚未确认',
                      ui_banner_note='当前模型结果不确定，请检查现场工况')
    elif state.get('panel_nn_valid') == '1':
        advisory = (state.get('panel_nn_advisory_state')
                    if state.get('panel_nn_advisory_valid') == '1' else 'UNKNOWN')
        if advisory in ('WARN', 'RECOVERING'):
            result.update(ui_severity='2', ui_banner_title='实测基线持续偏离 · 预警',
                          ui_banner_note='等待持续恢复确认' if advisory == 'RECOVERING' else
                          '当前输入持续偏离正常样本；尚不能判定故障类别')
        elif advisory == 'PENDING':
            result.update(ui_severity='1', ui_banner_title='NPU偏离待确认',
                          ui_banner_note='保留当前分数；持续偏离时发出预警')
        elif advisory != 'NORMAL':
            result.update(ui_severity='1', ui_banner_title='NPU监测中 · 等待确认',
                          ui_banner_note='等待连续有效输入，不能判为正常运行')
        elif not sample['status'].get('configured') or sample['status'].get('test_mode'):
            result.update(ui_severity='1', ui_banner_title='NPU基线匹配 · ' +
                          ('闭环未启用' if status.get('configured') else '控制待配置'),
                          ui_banner_note='NPU实推理不替代控制参数配置与闭环验证')
        else:
            result.update(ui_severity='0', ui_banner_title='NPU基线匹配',
                          ui_banner_note='连续有效输入与正常参考匹配')
    elif state.get('panel_classifier_valid') == '1' and (not status.get('configured') or status.get('test_mode')):
        result.update(ui_severity='1', ui_banner_title='NPU监测中 · ' +
                      ('闭环未启用' if status.get('configured') else '控制待配置'),
                      ui_banner_note='NPU实推理不替代控制参数配置与闭环验证')
    return result


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
    result.update(protection_fields(state, sample, vibration))
    for name in LABELS:
        result['panel_prob_' + name] = '--'
    model = sample.get('model')
    probabilities = model.get('probabilities') if isinstance(model, dict) else None
    # A newly admitted fault-window model may observe unknown FG; that is
    # separate from the physical sensor validity shown in the RPM card.
    try: model_quality=int(state.get('quality',''),16)
    except (ValueError,TypeError):model_quality=-1
    fault_input=(isinstance(model,dict) and model.get('input_policy')=='FAULT_WINDOWS_FG_UNKNOWN_V1'
                 and sample.get('model_formal') is True)
    model_quality_valid=(model_quality==0 or (fault_input and model_quality>=0 and model_quality & ~0x2800==0))
    model_valid = (fresh and state.get('frame_calibrated') == '1' and
                   state.get('frame_contract_current') == '1' and model_quality_valid and
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
            if fault_input and model.get('rpm_measurement_available') is False:
                result['panel_model_note'] = 'FG UNKNOWN / FAULT CANDIDATE'
            elif fault_input and model.get('protection_window'):
                result['panel_model_note'] += ' / PROTECTED'
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
