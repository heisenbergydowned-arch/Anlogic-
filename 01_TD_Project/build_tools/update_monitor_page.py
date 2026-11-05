from pathlib import Path
r=Path(__file__).resolve().parents[1]
p=r/'linux/static/index.html';s=p.read_text()
def rep(a,b):
 global s
 assert a in s,a[:100]
 s=s.replace(a,b)
rep('<a href="/commissioning" class="cta">调试与标定工作台 →</a>', '<a href="/commissioning#thermal" class="cta">温控与调试</a>\n    <a href="/commissioning#learn">基线与工况学习</a>\n    <a href="/commissioning#fan-life">寿命记录</a>')
rep('标定投运 (<span id="led-cfg-text">未标定', '温控配置 (<span id="led-cfg-text">待读取')
rep('KEY2 许可 (<span id="led-key2-text">0', '控制方式 (<span id="led-key2-text">待读取')
rep('硬件封锁 (<span id="led-inh-text">--', '实际输出 (<span id="led-inh-text">--')
rep('左下角同源双轴趋势图 · 温度外环与转速内环 PID 实时追平曲线', '温度、转速与 PWM 实时趋势')
rep('目标转速 (RPM)', '目标 PWM (%)')
rep('PID 控制与执行环路', '温度直接调速')
rep('斜坡目标转速</span><b id="ctl-ramped">— RPM', '目标占空比</span><b id="ctl-ramped">— %')
rep('温度外环设定</span><b id="ctl-temp-sp">— ℃', '温度曲线端点</span><b id="ctl-temp-sp">—')
rep('进风口与大气环境 (I2C)', '环境与风道压差')
rep('          <div class="feat-kv"><span>BMP280 大气压</span><b id="env-bmp-p">— kPa</b></div>\n', '')
rep('本地五分类 NPU 实时推理与双路振动特征', 'NPU 正常基线与故障识别')
rep('<div class="prob-list" id="prob-bars">', '<p id="normal-model" class="muted" style="white-space:pre-line">正在读取与 HDMI 同源的推理状态</p>\n      <p id="classifier-model" class="muted">五类识别等待有效模型结果</p>\n      <p><a href="/commissioning#learn">设置基线、按指定工况一键学习 →</a></p>\n      <div class="prob-list" id="prob-bars">')
rep('确认只标记已查看。保护复位和消音在本地操作；本系统不控制供电切断；PWM禁止不等于断电。', '告警只提示，不切断温控 PWM。参数与学习结果由工作台保存到 SD 卡；0% PWM 不等于风机断电。')
rep('远程确认仅记录已阅，不解除硬件锁存', '确认只记录已阅，告警不修改温控 PWM')
rep('historyBuffer.flatMap(p=>[p.rpm,p.reqRpm])', 'historyBuffer.map(p=>p.rpm)')
rep("plotLine(p=>p.reqRpm,rMin,rMax,'#3b9eff',true);", "plotLine(p=>p.target,0,100,'#3b9eff',true);")
rep("let [s,events]=await Promise.all([get('/api/status'),get('/api/events')]);", "let s=await get('/api/status');\n    let events=await get('/api/events').catch(()=>null);")
rep("el('health').textContent=(s.test?'联调测试 · ':'')+(online?'设备已连接':'设备失联 / 未连接')+' · '+(p.mode||'UNKNOWN')+' · L'+(s.level??'—');", "const c=s.temperature_pwm||{}, mf=s.monitor_display?.available?s.monitor_display.fields:{};\n    el('health').textContent=(online?'设备已连接':'设备失联 / 未连接')+' · '+(c.state==='RUNNING'?'温控运行':c.state||'温控状态未知')+' · L'+(s.level??'—');")
rep("const isStableRun=online&&p.mode==='RUN'&&!p.active?.length&&!p.latched?.length&&(s.level||0)===0;", "const isStableRun=online&&c.state==='RUNNING'&&(s.level||0)===0;")
rep("    const raw0=(p.raw_words&&p.raw_words[0])||0;\n    const key2Permit=Boolean(raw0&0x8000);\n", '')
a=s.index("    el('led-cfg').className=");b=s.index('\n\n    const pwmPct=',a)
s=s[:a]+'''    el('led-cfg').className='dot'+(c.saved?' on-cyan':'');
    el('led-cfg-text').textContent=c.saved?'已保存 SD':'待读取';
    el('led-key2').className='dot'+(c.hardware_supported?' on-green':'');
    el('led-key2-text').textContent=c.hardware_supported?'网页配置':'状态未知';
    el('led-inh').className='dot'+(c.hardware_armed?' on-green':'');
    el('led-inh-text').textContent=online&&c.feedback_valid?(c.actual_pwm_percent.toFixed(1)+'%'):'--';'''+s[b:]
rep("const pwmPct=p.applied_pwm_counts==null?null:(p.applied_pwm_counts/40).toFixed(1);", "const pwmPct=c.feedback_valid&&Number.isFinite(c.actual_pwm_percent)?c.actual_pwm_percent.toFixed(1):null;")
rep("const tempC=p.temp_raw_1_16_C==null?null:(p.temp_raw_1_16_C/16).toFixed(1);", "const tempC=p.input_validity?.temperature&&Number.isFinite(c.temperature_C)?c.temperature_C.toFixed(1):null;")
rep("const curVal=fresh&&!(frame.quality&256)&&v.current!=null?v.current.toFixed(3):null;", "const curVal=mf.daily_current_valid==='1'?mf.daily_current_value:null;")
rep("['实际转速',p.measured_rpm,'RPM'", "['实际转速',p.input_validity?.rpm?p.measured_rpm:null,'RPM'")
rep("['目标转速',p.requested_rpm,'RPM','斜坡目标 '+(p.ramped_rpm??'—')+' RPM'],", "['目标 PWM',c.feedback_valid?c.target_pwm_percent:null,'%','由已保存温度曲线计算'],")
rep("[uncal?'电流（名义值，未标定）':'电流',curVal,'A','AD7606 原始码 '+(p.raw_words?.[22]!=null?(p.raw_words[22]&65535):'—')],", "['电流 · 5秒平均',curVal,'A','与 HDMI 同源 · '+(mf.daily_current_average_count||0)+' 个采样 · 名义灵敏度'],")
rep('temp:p.temp_raw_1_16_C!=null?p.temp_raw_1_16_C/16:null,', 'temp:tempC!==null?Number(tempC):null,')
rep('rpm:p.measured_rpm,\n        reqRpm:p.requested_rpm,\n        pwm:p.applied_pwm_counts!=null?p.applied_pwm_counts/40:null', 'rpm:p.input_validity?.rpm?p.measured_rpm:null,\n        target:c.feedback_valid?c.target_pwm_percent:null,\n        pwm:pwmPct!==null?Number(pwmPct):null')
rep("el('ctl-action').textContent=online?(p.fan_action||'—'):'—';", "el('ctl-action').textContent=online?(c.state==='RUNNING'?'温控运行 · 告警不停止 PWM':c.state||'—'):'—';")
rep("el('ctl-ramped').textContent=online&&(p.ramped_rpm!=null)?p.ramped_rpm+' RPM':'—';", "el('ctl-ramped').textContent=c.feedback_valid&&c.target_pwm_percent!=null?c.target_pwm_percent.toFixed(1)+' %':'—';")
rep("el('ctl-temp-sp').textContent=s.coordination?.setpoint_C!=null?s.coordination.setpoint_C+' ℃':'未启用外环';", "el('ctl-temp-sp').textContent=c.settings?c.settings.low_C+'℃ → 0% / '+c.settings.high_C+'℃ → 100%':'待读取';")
rep("(env.state||'—')", "'—'")
rep("    el('env-bmp-p').textContent=env.barometric_pressure_Pa!=null?(Number(env.barometric_pressure_Pa)/1000).toFixed(2)+' kPa':'—';\n", '')
a=s.index('    // NPU 5-class bars');b=s.index("\n    el('details').replaceChildren(",a)
s=s[:a]+'''    // Use the same validated source and expiry gates as the HDMI display.
    const nn=mf.panel_nn_valid==='1', classified=mf.panel_classifier_valid==='1';
    const advisory={NORMAL:'基线匹配',PENDING:'短时偏离，待确认',WARN:'持续偏离',RECOVERING:'恢复观察',UNKNOWN:'等待有效输入'};
    const normalText=nn?(advisory[mf.panel_nn_advisory_state]||'实推理'):'暂无有效推理';
    el('npu-badge').textContent=classified?'五类模型 · 实推理':nn?'正常基线 · 实推理':'推理等待中';
    el('normal-model').textContent='正常基线：'+normalText+'\\n'+(nn?'重建误差 '+mf.panel_nn_score+' / 1.00 · '+mf.panel_nn_latency_ms+' ms · 累计 '+mf.panel_nn_count+' 次':(mf.panel_nn_reason||'等待有效输入'));
    const names={normal:'正常',imbalance:'失衡',stall:'卡死',clog:'堵塞',overheat:'过热',uncertain:'未确认'};
    el('classifier-model').textContent=classified?'五类识别：'+(names[mf.panel_classifier_label]||'未确认'):'五类识别：暂无有效结果；样本与模型进度见学习工作台';
    ['normal','imbalance','stall','clog','overheat'].forEach((name,i)=>{
      const raw=mf['panel_prob_'+name], value=raw===undefined?NaN:Number(raw);
      const pv=classified&&Number.isFinite(value)?Math.max(0,Math.min(100,value)):null;
      el('bar-'+i).style.width=pv!==null?pv.toFixed(1)+'%':'0%';
      el('val-'+i).textContent=pv!==null?pv.toFixed(1)+'%':'—';
    });
'''+s[b:]
rep("row('风扇动作',online?p.fan_action:'UNKNOWN')", "row('温控状态',online?c.state:'UNKNOWN')")
rep("row('模型状态',online?(s.decision?.model_state||'UNAVAILABLE'):'UNAVAILABLE'),\n      row('推理后端',s.model?.backend||'—'),\n      row('模型观察',s.model?.label||'—'),", "row('正常基线',normalText),\n      row('NPU 实推理',nn||classified?'Alnpu':'暂无有效结果'),\n      row('温控告警',(c.alarm_causes||c.faults||[]).join('、')||'无'),")
a=s.index('    if(s.maintenance){');b=s.index("    el('events').replaceChildren();",a)
s=s[:a]+s[b:]
rep("    el('events').replaceChildren();\n    for(let e of events.slice(0,20)){", "    if(events)el('events').replaceChildren();\n    for(let e of (events||[]).slice(0,20)){")
rep("    el('details').replaceChildren(row('设备状态','UNKNOWN'),row('模型状态','UNAVAILABLE'));", "    el('details').replaceChildren(row('设备状态','UNKNOWN'),row('模型状态','UNAVAILABLE'));\n    el('npu-badge').textContent='连接中断';el('normal-model').textContent='暂无有效推理';el('classifier-model').textContent='暂无有效结果';\n    for(let i=0;i<5;i++){el('bar-'+i).style.width='0%';el('val-'+i).textContent='—'}\n    for(const name of ['grn','red','cfg','key2','inh']){el('led-'+name).className='dot';el('led-'+name+'-text').textContent='--'}")
p.write_text(s)
p=r/'linux/static/commissioning.html';s=p.read_text();s=s.replace('保护触发时以实际输出和原因显示为准。','温控告警只提示，不会将 PWM 压零；温度读数失效时保持上一有效占空比。')
old="document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.setAttribute('aria-selected',String(x===b)));document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('active',x.id===b.dataset.tab))});"
new="document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.setAttribute('aria-selected',String(x===b)));document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('active',x.id===b.dataset.tab));history.replaceState(null,'','#'+b.dataset.tab)});\nfunction selectLinkedTab(){const target=location.hash.slice(1);const b=Array.from(document.querySelectorAll('nav button')).find(x=>x.dataset.tab===target);if(b)b.click()}\nwindow.addEventListener('hashchange',selectLinkedTab);selectLinkedTab();"
assert old in s;s=s.replace(old,new);p.write_text(s)
print('Updated merged monitoring page and direct learning/temperature/lifetime navigation')
