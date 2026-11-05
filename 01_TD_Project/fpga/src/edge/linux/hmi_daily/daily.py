"""Everyday telemetry and baseline feedback, without administrative controls."""
import math

from cabinet.protocol import FEATURES
from cabinet.environment import display_fields as environment_fields
if __package__:
    from .instrument import build_instrument
else:
    from instrument import build_instrument


BASELINE_TITLES = {
    'IDLE': '健康基线未学习', 'WAIT_STABLE': '等待转速稳定', 'CAPTURING': '正在学习健康工况',
    'VALIDATING': '正在验证候选基线', 'PENDING_CONFIRM': '候选已生成，待确认保存',
    'COMMITTED': '健康基线已保存', 'ABORTED': '学习已中止', 'REJECTED': '学习未通过',
    'CANCELLED': '学习已取消', 'TIMEOUT': '学习任务已超时', 'ERROR': '学习服务不可用',
}
EVIDENCE_TITLES = {
    'UNLEARNED': '尚无健康基线', 'STALE': '等待有效特征帧', 'INVALID_INPUT': '当前数据不满足学习条件',
    'VERSION_MISMATCH': '基线版本不匹配', 'OUT_OF_COVERAGE': '当前转速工况未覆盖',
    'CONSISTENT': '与本工况基线一致', 'CANDIDATE': '观测到基线偏离', 'DEVIATION': '持续偏离健康基线',
}
REASONS = {
    'NO_FRAME': '等待完整的真实特征帧', 'READY': '设备健康时可学习当前工况',
    'INSTALLATION_UNQUALIFIED': '安装与设备身份尚未确认', 'CALIBRATION_UNQUALIFIED': '标定合同尚未冻结',
    'PROTECTION_UNQUALIFIED': '硬件保护配置尚未完成', 'ACTIVE_ALARM': '当前告警未解除，不能学习',
    'CONTROL_UNQUALIFIED': '控制仍处于未合格状态', 'TEST_SOURCE': '测试数据不能建立真实健康基线',
    'FRAME_RPM_NOT_STABLE': '窗口转速与当前反馈不一致，请等待稳态',
    'FEATURE_RANGE': '特征数值范围不合格', 'BAND_POWER_INVALID': '频带功率比例不合格',
    'NOT_STABLE_RUN': '设备尚未进入稳定运行', 'SENSOR_INVALID': '必要传感器数据无效',
    'CONTROL_CONFLICT': '控制状态或保留位不允许学习', 'RPM_TRACKING': '转速未稳定跟踪目标',
    'FRAME_GAP': '特征数据中断，候选已作废', 'PL_RESTART': 'FPGA重启，学习已中止',
    'CONTRACT_CHANGED': '数据合同改变，候选已作废', 'FEATURE_CONFIG_UNQUALIFIED': '特征配置尚未合格',
    'FRAME_QUALITY_REJECTED': '采样质量不满足基线要求', 'MODEL_CONFLICT': '模型诊断冲突，需要现场检查',
    'THERMAL_DRIFT': '温度仍在漂移，请等待热状态稳定', 'HOLDOUT_DEVIATION': '留出验证存在偏离，拒绝保存',
    'CONFIRM_TIMEOUT': '确认已超时，未替换旧基线', 'LEARNING_TIMEOUT': '有效样本不足或等待超时',
    'OPERATOR_CANCELLED': '候选已取消，原基线与保护保持', 'BASELINE_SAVED': '仅记录健康工况，不解除任何保护',
    'EXISTING_BASELINE_DEVIATION': '先排查偏离原因，不能重学消警',
    'EXISTING_BASELINE_DEVIATION_DURING_LEARN': '学习期间出现旧基线偏离，已中止',
    'CANDIDATE_DRIFT': '当前数据偏离候选，需重新检查',
    'CANDIDATE_OPERATING_POINT_CHANGED': '当前转速超出候选范围，需重新学习',
    'PROFILE_HISTORY_FULL': '基线记录需要检查，当前不能学习',
    'PROTECTION_EVENT_DURING_LEARN': '学习期间保护状态变化，候选已作废',
    'PROTECTION_HISTORY_GAP': '保护事件记录不完整，需先检查',
    'MODEL_UNAVAILABLE': '等待有效模型结果，不能学习',
    'COLLECTOR_GAP': '采集数据中断，候选已作废',
    'HARDWARE_FRAME_GAP': '硬件特征帧丢失，候选已作废',
    'HARDWARE_MAILBOX_GAP': '硬件邮箱丢帧，候选已作废',
    'HARDWARE_WINDOW_GAP': '采样窗口丢失，候选已作废',
    'HARDWARE_CONTEXT_CHANGED': '硬件数据合同改变，候选已作废',
    'COLLECTOR_STALE': '采集数据过期，当前不可学习',
    'PL_LINK_LOSS': '采集链路失效，当前状态未知',
}


def build_daily(state, sample, baseline):
    result = environment_fields(sample.get('environment'))
    status = sample['status']
    core_raw = status.get('temp_raw_1_16_C')
    real_source = state.get('frame_state') != 'REJECTED_TEST'
    core_valid = (real_source and status.get('input_validity', {}).get('temperature') is True and
                  type(core_raw) is int and -880 <= core_raw <= 2000)
    result['core_temperature_source'] = 'DS18B20/S4b'
    result['core_temperature_valid'] = '1' if core_valid else '0'
    result['core_temperature_c'] = '%.1f' % (core_raw / 16.0) if core_valid else '--'
    record = sample['frame']
    current = record if record.get('state') == 'RECEIVED_REAL' else None
    fresh = state.get('frame_fresh') == '1'
    quality = int(state['quality'], 0) if fresh else 0xffffffff
    for name in ('rpm', 'current', 'pressure'):
        result['daily_' + name + '_value'] = state.get('ui_' + name + '_value', '--')
        result['daily_' + name + '_unit'] = state.get('ui_' + name + '_unit', '--')
        result['daily_' + name + '_valid'] = state.get('ui_' + name + '_valid', '0')
        validity_key = 'adc' if name == 'current' else name
        if not real_source or status.get('input_validity', {}).get(validity_key) is not True:
            result['daily_' + name + '_value'] = '--'
            result['daily_' + name + '_valid'] = '0'
    result['daily_current_kind'] = 'raw_distance'
    raw_words = status.get('raw_words')
    if (real_source and status.get('input_validity', {}).get('adc') is True and
            isinstance(raw_words, (list, tuple)) and len(raw_words) == 32 and
            type(raw_words[22]) is int and 0 <= raw_words[22] <= 0xffffffff):
        raw = raw_words[22] & 0xffff
        raw -= 0x10000 if raw & 0x8000 else 0
        result['daily_current_value'] = str(raw)
        result['daily_current_unit'] = '原始码'
        result['daily_current_valid'] = '1'
        result['daily_current_kind'] = 'raw_sample'
    if fresh and quality == 0 and state.get('frame_calibrated') == '1' and state.get('frame_contract_current') == '1':
        for name, unit, precision in [('current', 'A', 3), ('pressure', 'kPa', 3)]:
            if result['daily_' + name + '_valid'] != '1':
                continue
            number = state.get('feature_' + name, '--')
            try:
                number = float(number)
            except ValueError:
                continue
            if math.isfinite(number):
                result['daily_' + name + '_value'] = ('%.' + str(precision) + 'f') % number
                result['daily_' + name + '_unit'] = unit
                result['daily_' + name + '_valid'] = '1'
                if name == 'current':
                    result['daily_current_kind'] = 'calibrated'
    vibration_valid = fresh and state.get('frame_calibrated') == '1' and not (quality & 0xffff90ff) and state.get('frame_contract_current') == '1' and state.get('frame_state') != 'REJECTED_TEST'
    for point in ('a', 'b'):
        for axis in 'xyz':
            for kind in ('rms', 'pp', 'kurt'):
                name = '%s_%s_%s' % (kind, point, axis)
                result['daily_' + name] = state.get('feature_' + name, '--') if vibration_valid else '--'
        for band in range(8):
            name = 'band%s%d' % (point, band)
            raw = state.get('feature_' + name, '--')
            result['daily_' + name] = str(round(float(raw) * 100, 2)) if vibration_valid and raw != '--' else '--'
    result['daily_ratio_ab'] = state.get('feature_ratio_ab', '--') if vibration_valid else '--'
    result['daily_target'] = str(status['requested_rpm']) if status.get('configured') else '--'
    for point in ('a', 'b'):
        raw = state.get('frame_rate_' + point, '--')
        result['daily_frame_rate_' + point] = '%.0f' % float(raw) if raw != '--' and raw is not None else '--'
    if not fresh:
        result['daily_frame_rate_a'] = result['daily_frame_rate_b'] = '--'
    faults = [state.get('ui_fault_%d_title' % index, '') for index in range(int(state.get('ui_fault_count', 0)))]
    details = []
    details.extend(faults[:2] if details else faults[:3])
    if status.get('latched'):
        details.append('存在保护锁存')
    result['daily_notice'] = ' / '.join(details) if details else state.get('ui_banner_note', '')
    model = sample.get('model')
    labels = {'normal': '正常', 'imbalance': '振动异常(imbalance)', 'stall': '卡死', 'clog': '风道异常(clog)', 'overheat': '过热'}
    result['daily_model'] = ('%s / %s / %s' % (model.get('backend', 'EXTERNAL'),
                             labels.get(model.get('label'), '未知'), '诊断' if sample.get('model_formal') else '观察')) if model else '模型未就绪'
    result['ui_learn_title'] = BASELINE_TITLES.get(baseline['state'], '学习状态未知')
    result['ui_learn_note'] = REASONS.get(baseline.get('job_reason') or baseline.get('reason'), '等待合格真实数据；保护保持独立')
    if not fresh and baseline['state'] == 'IDLE':
        result['ui_learn_note'] = '等待合格真实39维数据；标定与保护需先完成'
    result['ui_learn_evidence'] = EVIDENCE_TITLES.get(baseline.get('evidence', {}).get('state'), '基线状态未知')
    result['ui_learn_samples'] = '%s / %s' % (baseline.get('samples', 0), baseline.get('required', 100))
    result['ui_learn_can_start'] = '1' if baseline.get('can_start') else '0'
    web = sample.get('learning_web')
    if isinstance(web, dict):
        result['ui_learn_can_start'] = '1' if web.get('can_start') is True else '0'
        if not web.get('clock_trusted') and baseline['state'] == 'IDLE':
            result['ui_learn_note'] = '时间状态未确认，当前不能学习'
    result['ui_learn_state'] = baseline['state']
    result['ui_learn_hash'] = baseline.get('candidate_hash') or ''
    result['ui_learn_job'] = baseline.get('job_id') or ''
    result['ui_learn_score'] = '%.2f' % baseline['evidence']['score'] if baseline.get('evidence', {}).get('score') is not None else '--'
    result['ui_learn_active_id'] = baseline.get('baseline_id') or '--'
    result['ui_learn_scope'] = '观察模式；不改变硬件告警' if not baseline.get('advisory_qualified') else '已验证维护提示；不改变硬保护'
    result.update(build_instrument(state, result, sample, baseline))
    return result
