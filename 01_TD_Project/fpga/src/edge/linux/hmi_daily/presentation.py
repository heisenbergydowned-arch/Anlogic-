"""Chinese, read-only presentation derived from actual FPGA observations."""

MODES = {'BOOT': '初始化', 'READY_OFF': '待机', 'STARTING': '启动中', 'RUN': '稳定运行',
         'TRANSIENT': '状态过渡', 'STOPPING': '停机中', 'MAINTENANCE': '维护模式',
         'LOCKED': '保护锁定', 'FALLBACK': '失效回退'}
ACTIONS = {'PI': '闭环调速', 'BOOST': '增强散热', 'LIMIT': '降额限速', 'INHIBIT': '禁止驱动',
           'FALLBACK': '失效回退', 'OFF': '输出关闭', 'MANUAL': '本地手动', 'STARTUP': '启动驱动'}
FAULTS = {
    'OC_HARD': ('严重过流', '硬件检测到电流危险，请先检查风机与供电'),
    'CURRENT_HIGH': ('电流偏高', '电流规则触发，检查负载与机械阻力'),
    'TEMP_WARN': ('温度预警', '温度规则触发，检查散热与热负载'),
    'TEMP_HARD': ('严重过热', '保持可用散热，要求人工处置热源'),
    'CURRENT_PROTECTION_LOST': ('电流保护输入丢失', '关键保护信号无效，不能按正常运行处理'),
    'TEMP_LOSS': ('温度输入丢失', '检查温度传感器接线与数据新鲜度'),
    'FG_LOSS': ('转速反馈丢失', '检查转速信号、供电及风机实际状态'),
    'START_FAIL': ('启动未确认', '风机启动后未得到符合规则的转速反馈'),
    'STALL_CORROBORATED': ('卡死证据成立', '转速与电流证据触发硬件保护'),
    'OVERSPEED': ('转速超限', '硬件转速规则触发，不代表模型分类结果'),
    'VIB_WARN': ('振动预警', '振动规则触发，检查安装与机械状态'),
    'VIB_HARD': ('振动严重超限', '硬件振动规则触发，检查保护状态'),
    'PS_LOSS': ('上层心跳丢失', '硬件按失效回退规则独立处理'),
    'CMD_EXPIRED': ('控制指令过期', '上层指令已过期，本界面不补发控制租约'),
    'DIAG_LOSS': ('振动诊断数据不足', '等待有效振动窗口，不能据此判定设备健康'),
    'AUX_LOSS': ('辅助测量数据无效', '检查电流、温度、压差等过程量输入'),
    'CONFIG_UNQUALIFIED': ('保护配置未完成', '保护参数尚未满足资格条件，界面不会自动放行'),
    'TRACK_ERROR': ('转速跟踪偏差', '实际转速未按控制目标收敛'),
    'STOP_UNCONFIRMED': ('停机未确认', '没有得到符合规则的停机证据'),
    'SOFT_PS': ('上层诊断提示', '这是硬件收到的上层提示，不是本界面运行了模型'),
    'SOFT_EXPIRED': ('诊断结果过期', '上层诊断结果失效，不能继续用于判断'),
}


def build_presentation(state, sample):
    status = sample['status']
    validity = status.get('input_validity', {})
    if state['frame_state'] == 'REJECTED_TEST':
        validity = {}
    active = status.get('active', [])
    fresh = state['frame_fresh'] == '1'
    quality = int(state['quality'], 0) if fresh else 0
    level = status.get('alarm_level', 0)
    severity = 3 if level == 3 else 2 if level > 0 or not status.get('configured') or not fresh else 0
    if state['frame_state'] == 'REJECTED_TEST':
        title, note, severity = '检测到测试数据源', '测试帧不作为真实采样证据，当前数值已隐藏', 2
    elif not fresh:
        title = '等待有效采样' if state['frame_id'] == '--' else '采样帧已过期'
        note = 'FPGA链路在线；尚无可用的完整特征帧，不显示推测值'
    elif quality:
        title, note, severity = '采样质量需要检查', '已收到真实帧，但存在质量标志；仅供诊断查看', max(2, severity)
    elif level > 0:
        title, note = '当前存在设备告警', '请查看右侧保护面板；告警等级由FPGA返回'
    elif not status.get('configured'):
        title, note = '保护配置待完成', '数据已接收；控制资格未完成，不能宣称整机正常'
    else:
        title, note = '实时采样已接收', '监测链路工作中；模型判断未接入本界面'
    if level == 3:
        title, note = '严重告警，请检查设备', '以硬件保护状态为准，本界面不执行复位或放行'
    elif level == 2:
        title, note = '设备告警，需要处置', '请检查右侧保护面板与现场设备状态'
    seconds = int(status.get('uptime_ms', 0)) // 1000
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    runtime = '%02d:%02d:%02d' % (hours, minutes, seconds)
    if days:
        runtime = '%d天 %s' % (days, runtime)
    result = {
        'ui_banner_title': title, 'ui_banner_note': note, 'ui_severity': str(severity),
        'ui_mode': MODES.get(status.get('mode'), '未知状态'),
        'ui_action': ACTIONS.get(status.get('fan_action'), '未知动作'),
        'ui_level': {0: '无等级告警', 1: '维护提示', 2: '需要处置', 3: '严重告警'}.get(level, '未知等级'),
        'ui_output': '禁止驱动' if status.get('hard_inhibit') else '未禁止驱动',
        'ui_configuration': '配置已完成' if status.get('configured') else '配置待完成',
        'ui_runtime': runtime,
        'ui_frame_id': state['frame_id'], 'ui_frame_age': state['frame_age'],
        'ui_quality': '待采样' if not fresh else '存在质量标志' if quality else '无质量标志',
        'ui_drops': state['drops'], 'ui_fault_count': str(len(active)),
        'ui_latched': '无锁存告警' if not status.get('latched') else '、'.join(FAULTS.get(name, (name, ''))[0] for name in status['latched']),
        'ui_vibration': '窗口已接收' if fresh else '振动窗口待就绪',
        'ui_rpm_value': str(status.get('measured_rpm', '--')) if validity.get('rpm') else '--',
        'ui_rpm_unit': 'rpm',
        'ui_rpm_note': '来自FG转速反馈' if validity.get('rpm') else '等待有效转速反馈',
        'ui_temp_value': '%.1f' % (status['temp_raw_1_16_C'] / 16.0) if validity.get('temperature') else '--',
        'ui_temp_unit': '℃',
        'ui_temp_note': 'DS18B20 / S4b' if validity.get('temperature') else '等待有效温度输入',
        'ui_current_value': str(status.get('current_distance_raw_code', '--')) if validity.get('adc') else '--',
        'ui_current_unit': '原始码',
        'ui_current_note': '电流幅值尚未标定' if validity.get('adc') else '等待有效电流输入',
        'ui_pressure_value': str(status.get('pressure_raw_code', '--')) if validity.get('pressure') else '--',
        'ui_pressure_unit': '原始码',
        'ui_pressure_note': '压差量纲尚未标定' if validity.get('pressure') else '等待有效压差输入',
    }
    for name, valid_key in [('rpm', 'rpm'), ('temp', 'temperature'), ('current', 'adc'), ('pressure', 'pressure')]:
        result['ui_' + name + '_valid'] = '1' if validity.get(valid_key) else '0'
    for index, fault in enumerate(active[:21]):
        description, suggestion = FAULTS.get(fault, ('未知告警', '请核对接口版本与原始故障位'))
        result['ui_fault_%d_title' % index] = description
        result['ui_fault_%d_note' % index] = suggestion
    return result
