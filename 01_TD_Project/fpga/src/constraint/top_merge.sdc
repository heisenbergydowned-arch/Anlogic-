# top_merge.sdc v1.2: shared PS AXI clock PLL, 75MHz C0 and 150MHz C1.
# PLL_0 already provides both outputs. Its C1 now clocks NPU and video AXI.
# Both reset sequencers use this PLL's lock. System Builder Design.xml matches.
# Native PS AXI clocks must report 75/150/150/150MHz before physical timing.
# Generated clocks retain hardware dividers, phase and compensation behavior.
# C0/C1 are synchronous. Keep their paths checked in the same clock group.
# This file is tied to the current IP settings; rerun clock checks after changes.
create_clock -period 10.0 -name sysclk [get_ports I_sysclk]
set_max_delay 8.0 -to [get_ports O_adc_reset]
set_min_delay 0.0 -to [get_ports O_adc_reset]
# Cabinet main build uses ENABLE_CAMERA=0; no MIPI/ISP clocks exist.
# The camera-enabled legacy constraints are preserved in the backup.
# Enabling the legacy camera block requires its matching clock constraints.
derive_clocks
rename_clock -name clk_75m [get_clocks {design_0_inst/design_0_pll_75m_Inst/dr1_phy_pll_1f386b1db2c3_Inst/u_DR1_PHY_PLL.clkc[0]}]
rename_clock -name clk_fabric_150m [get_clocks {design_0_inst/design_0_pll_75m_Inst/dr1_phy_pll_1f386b1db2c3_Inst/u_DR1_PHY_PLL.clkc[1]}]
rename_clock -name clk_vtg [get_clocks {design_0_inst/design_0_video_timing_generator_v01_0_Inst/video_timing_generator_v01_e2dadf6740ca_Inst/dr1_pll_vtc_Inst/u_DR1_PHY_PLL.clkc[0]}]
rename_clock -name clk_hdmi [get_clocks {design_0_inst/design_0_PLL_3_Inst/dr1_phy_pll_58e32fb6dd07_Inst/u_DR1_PHY_PLL.clkc[0]}]
set_false_path -from [get_nets {design_0_inst/design_0_ARM_Processor_System_0_Inst/p2f_rst0_n}]
set_clock_groups -asynchronous -group [get_clocks {clk_75m clk_fabric_150m}] -group [get_clocks {clk_vtg clk_hdmi}] -group [get_clocks sysclk]
#=============================================================================
# ── 采集域约束追加段（照抄 top.sdc v0.6，删 O_led1/O_led2）──
#
#   1) 全部采集输入（含 SPI MISO / ADC）在 subsys_acq 内一律 2FF 同步
#      后使用（sns_sync/ads7606_if/fg_cap/ds18b20/i2c_master/按键均如此），
#      pad→第一级同步器的时序无意义（亚稳态由 2FF 吸收）→ false_path；
#   2) 慢速输出（LED/蜂鸣器/485/PWM/调试串口）µs~ms 级外部电路，
#      clk→pad 的 ns 级延迟完全无影响 → false_path；
#   3) SPI/ADC 输出（SCLK/MOSI/CS/CONVST）不加 output_delay，按协议
#      裕量保证（SCLK 由 100MHz 寄存器分频产生：ICM 6.25MHz 半周期
#      80ns；ADC 12.5MHz 半周期 40ns，同域寄存器到 pad 歪斜 < ~9ns，
#      远大于器件要求）——出现在 unconstrained 列表属预期，不计入违例；
#   4) 采集域单时钟域内部路径按 10ns 分析，v0.6.1 基线：布线后
#      SWNS +1.577ns / HWNS +0.080ns（Hold 余量仅 80ps，合并版回归
#      时必须复核 HWNS 不回退）。
#=============================================================================

#-----------------------------------------------------------------------------
# 全部采集输入端口 → 第一级 2FF 同步器：异步路径，不做 setup/hold 分析
#-----------------------------------------------------------------------------
set_false_path -from [get_ports {I_spi_miso I_adc_douta I_adc_busy I_adc_frstdata \
                                I_fan_fg I_key1 I_key2 I_pl_uart_rx I_rs485_rx \
                                IO_j12_19_reserved IO_temp_core_dq \
                                IO_i2c_sda_ext IO_i2c_scl_ext IO_iic_sda IO_iic_scl}]

#-----------------------------------------------------------------------------
# 慢速输出：外部电路 µs~ms 级（LED 人眼、蜂鸣器、485 半双工帧、
# PWM 25kHz、调试 UART 115200 bit≈8.7µs），ns 级 clk→pad 延迟无影响
#-----------------------------------------------------------------------------
set_false_path -to [get_ports {O_led_grn O_led_red O_led3_hb O_led4_alm \
                              O_buzzer_en \
                              O_rs485_tx O_rs485_de O_fan_pwm O_pl_uart_tx}]

# Use only clocks which actually exist in this variant. Missing PS native
# GEN_PL_* clocks are a separate release-blocking coverage issue; an invalid
# name in a TD group aborts the entire set_clock_groups command.
