# HDMI单核心温度显示接口 v2

当前唯一屏幕协议为`panel_schema=industrial-v2`。发布者是`run_edge.py`的单采集器/LocalDisplay，消费者是同目录`dashboard.c`；日常版和记录版共用同一刷新函数。HMI只读state文件，不读取MMIO，不发送控制/学习指令。

## 温度与环境字段

| 字段 | 来源与含义 | 有效性/单位 |
|---|---|---|
| core_temperature_c | FCB1的temp_raw_1_16_C÷16，唯一DS18B20/S4b实时核心状态 | ℃；缺失/非法范围/失效为`--` |
| core_temperature_valid | FCB1必要温度有效性，且原始值为−880～2000的整数 | 1或0 |
| core_temperature_source | 固定DS18B20/S4b | C端严格检查；不匹配则隐藏核心值与温度趋势 |
| inlet_temperature_c | AHT20进风温度 | ℃；由AHT质量与年龄判断 |
| relative_humidity_pct | AHT20相对湿度 | %RH；与进风温度共用AHT有效期 |
| inlet_source | 固定AHT20 | 不匹配时隐藏AHT显示 |
| ambient_pressure_hpa | BMP280补偿后的环境绝对气压 | hPa；不能当成SDP810差压 |
| ambient_pressure_source | 固定BMP280 | 不匹配时隐藏BMP显示 |
| environment_aht_deadline_ms / environment_bmp_deadline_ms | 与显示进程一致的CLOCK_MONOTONIC有效截止时刻 | 过期、0或超过允许有效期均隐藏 |

屏幕不再输出或读取`daily_temp_value/unit/valid`，不读取环境温度作为核心温度后备。BMP芯片温度只留在补偿及原始环境记录中，不发布到屏幕字段。`feature_temp`仍表示39维中零基36的窗口核心温度，与FCB1实时值可能因采样时刻不同而略有差异，不能互相偷换来凑数。

## 保留和删除

- 保留四维过程量、35维双测点振动特征、16频带、PL灯阵、真实NPU五分类结果和网页双确认基线状态。
- 删除BMP芯片温度显示、重复Pa/kPa数值、无来源的电流阈值、没有实际阈值支撑的核心/电流填充条、ratio“正常稳定”标签以及仅凭L0就宣称“闭环稳态”的文案。
- 温度趋势明确为核心温度；显示轴−55～125℃是传感器数值范围，不是保护阈值。转速条按实际目标，SDP810差压条按500Pa量程；未标定原始码不填充量程条。
- 两种画面都保留缺失`--`、陈旧、质量、锁存、模型不可用和学习门禁；没有新增本地按钮或触摸交互。

## 版本和部署

新显示程序拒绝industrial-v1；不能只替换可执行文件而不升级对应的state发布代码。版本不匹配时明确提示“显示接口版本不匹配”，不按旧键猜测或继续显示旧值。更新时需一起部署同一版`daily.py`、`instrument.py`、`cabinet/environment.py`和显示程序/字库；更推荐完整保留本版Linux源码目录后按原服务入口升级。

本机`dashboard_preview`/`capture_preview`是Mac实染测试程序，不是ARM Linux可执行文件。板上程序应在已核验LVGL9.4.0环境中编译。必须保留现有edge/learning配置、数据库和基线；不得用示例配置覆盖资格或模型合同。旧FPGA没有ENV1能力时，环境行显示`--`，不盲读新寄存器。

此UI更新不改变RTL、39维顺序、Scaler/模型、保护参数、学习规则或SD启动文件。板端不可达时只交付源码/本机测试，不能宣称HDMI实屏已更新。
