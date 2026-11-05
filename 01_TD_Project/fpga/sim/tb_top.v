//============================================================================
// tb_top.v — subsys_acq 系统级冒烟测试（真实参数时长，仿真约 2.5s）
//
// 单S4b拓扑：J12-19闲置，进风温度来自AHT20，唯一DS18B20测核心器件温度。
//
// v0.8：DUT 加速度计 4kSps（ACCEL_CONFIG2=0x08，陀螺 standby），
//       节拍 8kHz、SCLK 6.25MHz；模型 ODR=3960Hz。
//
// 配置：ICM-A + AD7606 + 单DS18B20 + AHT20 + BMP280 在线，ICM-B 悬空（tri0），
//       FG 1kHz（可停启）。I2C 总线 AHT20/BMP280 共享（subsys_acq 内仲裁，AHT 优先）。
//       压缩参数：DS_CONV_MS=1、FG_SPINUP_MS=100、GRACE_MS=1100（>DS 首帧
//       ~1.01s，避免宽限期早于慢启动传感器出数造成伪告警窗口）。
// 校验：init_done→绿灯；A 片数据流；B 静默容错；AD7606 8 通道数据流；
//       KEY1 四次步进占空比（2000→3000→4000→0→1000）；
//       FG 周期 100000；唯一DS18B20 present+核心温度（CRC8 通路）；
//       AHT20 present/无错/湿度温度码；BMP280 chip_id/present/无错/压温原始码；
//       dbg_uart v2 帧 A 同步解码：状态字（init_done/err_b/present 位）、
//       seq_a 增长、ICM-A ax 与 ADC ch1/ch2（真实出口验证）；
//       FG 停转链：duty=0 停 FG→超时置位但不告警；0%→25% 切换起转
//       宽限内不告警（防切换闪红）；宽限过后停转告警；FG 恢复自愈。
//============================================================================
`timescale 1ns/1ps
module tb_top;
    localparam integer CLK_NS = 10;

    reg clk = 1'b0;
    always #(CLK_NS/2.0) clk = ~clk;

    integer errors = 0;
    task check;
        input cond;
        input [255:0] tag;
        begin
            if (cond !== 1'b1) begin
                errors = errors + 1;
                $display("[%0s] FAIL @%0t", tag, $time);
            end
        end
    endtask

    //====================================================================
    // DUT 连线
    //====================================================================
    wire  O_spi_sclk, O_spi_mosi;
    tri0  I_spi_miso;                // B 悬空：无驱动时为 0
    wire  O_cs_icm_a, O_cs_icm_b;
    wire  O_adc_convst, O_adc_sclk, O_adc_cs, O_adc_reset;
    wire  I_adc_busy, I_adc_frstdata;
    wire  I_adc_douta;
    wire  reserved_pad, core_dq;                // 闲置J12-19 / 唯一核心温度探头
    wire  sda_ext, scl_ext;          // AHT20 + BMP280 I2C
    reg   I_fan_fg = 1'b1;
    wire  O_fan_pwm, O_buzzer_en, O_led_grn, O_led_red;
    wire  O_rs485_tx, O_rs485_de, O_led3_hb, O_led4_alm, O_pl_uart_tx;
    reg   I_key1 = 1'b1;
    reg   I_key2 = 1'b1;
    reg   I_pl_uart_rx = 1'b1;
    reg   I_rs485_rx = 1'b1;
    wire  IO_iic_sda, IO_iic_scl;

    // DS_CONV_MS=1：转换等待压缩（真实硬件 800ms；协议时序仍为真实 µs 级）
    subsys_acq #(.DS_CONV_MS(1), .FG_SPINUP_MS(100), .GRACE_MS(1100)) dut (
        .I_sysclk     (clk),
        .O_spi_sclk   (O_spi_sclk), .O_spi_mosi (O_spi_mosi),
        .I_spi_miso   (I_spi_miso),
        .O_cs_icm_a   (O_cs_icm_a), .O_cs_icm_b (O_cs_icm_b),
        .O_adc_convst (O_adc_convst), .O_adc_sclk (O_adc_sclk),
        .O_adc_cs     (O_adc_cs),
        .O_adc_reset  (O_adc_reset),
        .I_adc_douta  (I_adc_douta), .I_adc_busy (I_adc_busy),
        .I_adc_frstdata(I_adc_frstdata),
        .IO_j12_19_reserved(reserved_pad),
        .IO_temp_core_dq(core_dq),
        .IO_i2c_sda_ext (sda_ext),
        .IO_i2c_scl_ext (scl_ext),
        .I_fan_fg     (I_fan_fg), .O_fan_pwm (O_fan_pwm),
        .O_buzzer_en  (O_buzzer_en),
        .O_led_grn    (O_led_grn), .O_led_red (O_led_red),
        .O_rs485_tx   (O_rs485_tx), .I_rs485_rx (I_rs485_rx), .O_rs485_de (O_rs485_de),
        .O_led3_hb    (O_led3_hb), .O_led4_alm (O_led4_alm),
        .I_key1       (I_key1), .I_key2 (I_key2),
        .O_pl_uart_tx (O_pl_uart_tx), .I_pl_uart_rx (I_pl_uart_rx),
        .IO_iic_sda   (IO_iic_sda), .IO_iic_scl (IO_iic_scl)
    );

    //====================================================================
    // 外部器件
    //====================================================================
    // ODR=3960Hz：故意偏离 4kHz 节拍（真实器件晶振有百分之几偏差），
    // 避免"零频差→采样相位冻结"的退化解（相位恰好落进突发读死窗会全程零 vld）
    icm20602_model #(.WHO_ID(8'h12), .DATA_BASE(8'h01), .ODR_HZ(3960)) u_icm_a (
        .sclk(O_spi_sclk), .mosi(O_spi_mosi), .miso(I_spi_miso), .cs_n(O_cs_icm_a));

    ads7606_model u_adc (
        .reset(O_adc_reset),
        .convst (O_adc_convst), .busy (I_adc_busy), .sclk (O_adc_sclk),
        .cs_n   (O_adc_cs), .douta (I_adc_douta), .frstdata (I_adc_frstdata),
        .ch1_code (16'h1234), .ch2_code (16'h5678), .ch3_code (16'h9ABC),
        .ch4_code (16'hDEF0), .ch5_code (16'h0123), .ch6_code (16'h4567),
        .ch7_code (16'h89AB), .ch8_code (16'hCDEF),
        .en (1'b1), .frst_mode (2'd0)
    );
    pullup (I_adc_douta);

    // 唯一DS18B20：被散热器件旁37.5°C；闲置脚不接模型。
    ds18b20_model u_ds18b20_core (
        .dq(core_dq), .en(1'b1), .temp_code(16'h0258), .crc_bad(1'b0));
    pullup (core_dq);

    // I2C 总线：AHT20（湿度 50%、温度 25°C）+ BMP280（校准字节 i=0x88+i，
    // 原始码 t=0xABCDE / p=0x12345）；模型忙时长均短于驱动等待窗
    pullup (sda_ext);
    pullup (scl_ext);
    aht20_model #(
        .MEAS_MS (40)
    ) u_aht20 (
        .sda(sda_ext), .scl(scl_ext),
        .present  (1'b1),
        .cal_powerup(1'b0),
        .hum_in   (20'h80000),     // 50%RH
        .temp_in  (20'h60000),     // 25°C
        .busy     ()
    );
    wire [191:0] cal_tb;
    genvar gi;
    generate
        for (gi = 0; gi < 24; gi = gi + 1) begin : g_cal
            assign cal_tb[gi*8 +: 8] = 8'h88 + gi[7:0];
        end
    endgenerate
    bmp280_model #(
        .MEAS_MS (5)
    ) u_bmp280 (
        .sda(sda_ext), .scl(scl_ext),
        .present  (1'b1),
        .cal_in   (cal_tb),
        .t_raw_in (20'hABCDE),
        .p_raw_in (20'h12345)
    );

    // FG 1kHz 方波（周期 100000 clk），fg_run=0 停止（停转/宽限测试）
    reg fg_run = 1'b1;
    always begin
        if (fg_run) begin #500_000 I_fan_fg = ~I_fan_fg; end
        else        begin I_fan_fg = 1'b1; #500_000; end   // 停转：保持高（上拉态）
    end

    //====================================================================
    // 监测（层次引用 subsys_acq 内部信号）
    //====================================================================
    integer vld_a_cnt = 0, vld_b_cnt = 0, vld_adc_cnt = 0;
    integer inlet_aht_count = 0, core_temp_count = 0;
    always @(posedge clk) begin
        if (dut.vld_icm_a) vld_a_cnt = vld_a_cnt + 1;
        if (dut.vld_icm_b) vld_b_cnt = vld_b_cnt + 1;
        if (dut.vld_adc)   vld_adc_cnt = vld_adc_cnt + 1;
        if (dut.inlet_aht_vld)  inlet_aht_count = inlet_aht_count + 1;
        if (dut.temp_core_vld) core_temp_count = core_temp_count + 1;
    end

    //====================================================================
    // 激励
    //====================================================================
    task press_key1;
        begin
            I_key1 = 1'b0; #(30_000_000);   // 30ms 按下（> 20ms 去抖）
            I_key1 = 1'b1; #(30_000_000);   // 30ms 释放
        end
    endtask

    // 统计一个 PWM 周期（4000 clk）内的高电平拍数
    task measure_duty;
        output integer hi;
        integer n;
        begin
            hi = 0;
            for (n = 0; n < 4000; n = n + 1) begin
                @(posedge clk);
                if (O_fan_pwm) hi = hi + 1;
            end
        end
    endtask

    // 115200 8N1 采样解码一个字节（位宽 ≈ 868 clk，bit 中心采样）
    task uart_rx_byte;
        output [7:0] b;
        integer k;
        begin
            @(negedge O_pl_uart_tx);      // start 位下降沿
            #(CLK_NS * 1302);             // bit0 中心 = 起始沿 + 1.5 bit
            for (k = 0; k < 8; k = k + 1) begin
                b[k] = O_pl_uart_tx;
                #(CLK_NS * 868);          // 下一位中心
            end
        end
    endtask

    integer hi;
    reg hdr_found;       // dbg_uart 帧头已同步
    initial begin
        hdr_found = 1'b0;
        // 等初始化完成（POR 10ms + POWERUP 100ms + A 初始化 ~150ms + B 失败后 POSTINIT 50ms
        // + AHT20 首帧 ~135ms + BMP280 首帧 ~15ms）
        #(400_000_000);
        $display("@%0t init: grn=%b err_a=%b err_b=%b adc_err=%b", $time, O_led_grn,
                 dut.sns_err_a, dut.sns_err_b, dut.err_adc);
        check(O_led_grn === 1'b1, "init_done_led");
        check(dut.sns_err_b === 1'b1, "err_b_fault_flag");
        check(dut.err_adc  === 1'b0, "adc_no_err");
        check(vld_a_cnt > 50, "vld_a_stream");
        check(vld_b_cnt == 0, "vld_b_silent");
        check(vld_adc_cnt > 1000, "vld_adc_stream");
        $display("A data: ax=%04x gz=%04x fg_period=%0d", dut.a_ax, dut.a_gz, dut.fg_period);
        check(dut.a_ax == 16'sh0102 && dut.a_gz == 16'sh0D0E, "a_data_path");
        check(dut.fg_period > 32'd99990 && dut.fg_period < 32'd100010, "fg_period");
        $display("ADC ch: %04x %04x %04x %04x %04x %04x %04x %04x",
                 dut.adc_ch1, dut.adc_ch2, dut.adc_ch3, dut.adc_ch4,
                 dut.adc_ch5, dut.adc_ch6, dut.adc_ch7, dut.adc_ch8);
        check(dut.adc_ch1 == 16'sh1234 && dut.adc_ch2 == 16'sh5678, "adc_ch12");
        check(dut.adc_ch3 == 16'sh9ABC && dut.adc_ch4 == 16'shDEF0, "adc_ch34");
        check(dut.adc_ch5 == 16'sh0123 && dut.adc_ch6 == 16'sh4567, "adc_ch56");
        check(dut.adc_ch7 == 16'sh89AB && dut.adc_ch8 == 16'shCDEF, "adc_ch78");

        // I2C 传感器：AHT20 首帧 ~135ms、BMP280 首帧 ~15ms，均已出数
        $display("@%0t i2c: aht present=%b err=%b hum=%05x temp=%05x",
                 $time, dut.aht_present, dut.aht_err, dut.aht_hum_code, dut.aht_temp_code);
        $display("@%0t i2c: bmp id=%02x present=%b err=%b t=%05x p=%05x",
                 $time, dut.bmp_chip_id, dut.bmp_present, dut.bmp_err,
                 dut.bmp_t_raw, dut.bmp_p_raw);
        check(dut.aht_present    === 1'b1,   "aht_present");
        check(dut.aht_err        === 1'b0,   "aht_no_err");
        check(dut.aht_hum_code   == 20'h80000, "aht_hum_code");
        check(dut.aht_temp_code  == 20'h60000, "aht_temp_code");
        check(dut.bmp_chip_id    == 8'h58,     "bmp_chip_id");
        check(dut.bmp_present    === 1'b1,     "bmp_present");
        check(dut.bmp_err        === 1'b0,     "bmp_no_err");
        check(dut.bmp_t_raw      == 20'hABCDE, "bmp_t_raw");
        check(dut.bmp_p_raw      == 20'h12345, "bmp_p_raw");
        check(sda_ext === 1'b1 && scl_ext === 1'b1, "i2c_bus_idle");

        // KEY1 步进：初始 2000 → 3000 → 4000 → 0 → 1000
        press_key1;                     // → 3000 (75%)
        measure_duty(hi);
        $display("duty after key1: hi=%0d (expect ~3000)", hi);
        check(hi >= 2998 && hi <= 3002, "duty_75pct");

        press_key1;                     // → 4000 (100%)
        measure_duty(hi);
        $display("duty after key2: hi=%0d (expect ~4000)", hi);
        check(hi >= 3998 && hi <= 4000, "duty_100pct");

        press_key1;                     // → 0 (0%)
        measure_duty(hi);
        $display("duty after key3: hi=%0d (expect 0)", hi);
        check(hi == 0, "duty_0pct");

        press_key1;                     // → 1000 (25%)
        measure_duty(hi);
        $display("duty after key4: hi=%0d (expect ~1000)", hi);
        check(hi >= 998 && hi <= 1002, "duty_25pct");

        check(O_buzzer_en === 1'b0, "buzzer_idle");
        check(O_rs485_de === 1'b0, "rs485_rx_mode");

        // dbg_uart v2 帧 A：同步帧头 0x55 0xA5 → 收满 77B → 状态字/序号/
        // ICM-A ax / ADC ch1/ch2 / dup 计数器 / XOR 校验（全部测量量真实出口验证）
        begin : dbg_frame
            reg [7:0]  fra [0:76];
            reg [7:0]  b0, b1;
            reg [7:0]  xor_calc;
            reg [15:0] st_w;
            integer    guard, k;
            hdr_found = 0; guard = 0;
            while (!hdr_found && guard < 600) begin
                uart_rx_byte(b0);
                if (b0 == 8'h55) begin
                    uart_rx_byte(b1);
                    if (b1 == 8'hA5) hdr_found = 1;
                end
                guard = guard + 1;
            end
            check(hdr_found, "dbg_frame_header");
            if (hdr_found) begin
                fra[0] = 8'h55; fra[1] = 8'hA5;
                for (k = 2; k < 77; k = k + 1) uart_rx_byte(fra[k]);

                st_w = {fra[3], fra[2]};
                $display("dbg_uart frameA: status=%04x seq_a=%02x%02x a_ax=%02x%02x adc1=%02x%02x",
                         st_w, fra[5], fra[4], fra[37], fra[36], fra[49], fra[48]);
                check(st_w[9]  == 1'b1, "dbg_st_init_done");
                check(st_w[1]  == 1'b1, "dbg_st_err_b");
                check(st_w[8]  == 1'b1, "dbg_st_alarm_errb");
                check(st_w[14] == 1'b1, "dbg_st_aht_present");
                check(st_w[15] == 1'b1, "dbg_st_bmp_present");
                check(st_w[13] == 1'b1, "dbg_st_bmp_cal_valid");
                check(st_w[12] == 1'b0, "dbg_st_fg_no_timeout");
                check({fra[5], fra[4]} > 16'd100, "dbg_seq_a_growing");
                check({fra[37], fra[36]} == 16'h0102, "dbg_a_ax");
                check({fra[43], fra[42]} == 16'h0000, "dbg_b_ax_zero");
                check({fra[49], fra[48]} == 16'h1234, "dbg_adc1");
                check({fra[51], fra[50]} == 16'h5678, "dbg_adc2");
                check({fra[73], fra[72]} == 16'd0, "dbg_dup_a_zero");   // A 在线正常流 → dup=0
                check({fra[75], fra[74]} == 16'd0, "dbg_dup_b_zero");   // B 悬空无 vld → dup=0

                xor_calc = 8'h00;
                for (k = 0; k < 76; k = k + 1) xor_calc = xor_calc ^ fra[k];
                check(fra[76] == xor_calc, "dbg_xor_checksum");
            end
        end

        // DS18B20：首次复位 ~1.01s，首次温度 ~1.016s（CONV 压缩后）
        #(400_000_000);
        $display("@%0t inlet AHT20: present=%b temp=0x%04x | core DS18B20: present=%b temp=0x%04x (inlet_cnt=%0d core_cnt=%0d)",
                 $time, dut.inlet_aht_present, dut.inlet_aht_raw,
                 dut.temp_core_present, dut.temp_core_raw, inlet_aht_count, core_temp_count);
        check(dut.inlet_aht_present === 1'b1, "aht_inlet_present");
        check(inlet_aht_count >= 1, "aht_inlet_temp_vld");
        check(dut.inlet_aht_raw == 16'sh0190, "aht_inlet_temp_value");
        check(dut.temp_core_present === 1'b1, "core_present");
        check(core_temp_count >= 1, "core_temp_vld");
        check(dut.temp_core_raw == 16'sh0258, "core_temp_value");
        check(vld_adc_cnt > 10_000, "adc_stream_longrun");

        //──── FG 停转 / 起转宽限 / 恢复自愈（FG_SPINUP_MS=100 压缩）────
        // 占空比环 0→1000→2000→3000→4000→0（5 档）：初始 4 键后停在
        // 1000(idx1)，再按 4 键（2000→3000→4000→0）才回 0%——1000 的
        // 下一步是 2000 不是 0，不能假设一键回零
        press_key1; press_key1; press_key1; press_key1;
        check(dut.fan_duty == 16'd0, "fg_duty_zero");
        fg_run = 1'b0;                  // 风扇停转：FG 无脉冲
        #(450_000_000);                 // > 400ms 超时门限
        $display("@%0t fg stop: timeout=%b stall=%b duty=%0d",
                 $time, dut.fg_timeout, dut.fg_stall, dut.fan_duty);
        check(dut.fg_timeout === 1'b1, "fg_timeout_asserted");
        check(dut.fg_stall  === 1'b0, "no_stall_when_duty0");

        // 0%→非0% 切换：起转宽限内不闪红（修复点：宽限期只覆盖上电，
        // 不覆盖运行中切换会导致切换瞬间误告警）
        press_key1;                     // duty 0 → 1000（起转）
        check(dut.fan_duty == 16'd1000, "fg_duty_25pct");
        #(40_000_000);                  // 宽限 100ms 内
        $display("@%0t spinup grace: timeout=%b stall=%b spinup=%b",
                 $time, dut.fg_timeout, dut.fg_stall, dut.fg_spinup);
        check(dut.fg_timeout === 1'b1, "fg_timeout_still_held");
        check(dut.fg_spinup === 1'b1, "spinup_grace_active");
        check(dut.fg_stall  === 1'b0, "spinup_grace_no_alarm");

        // 宽限过后 FG 仍无脉冲 → 停转告警
        #(120_000_000);                 // 宽限 100ms 已过
        $display("@%0t after grace: timeout=%b stall=%b", $time, dut.fg_timeout, dut.fg_stall);
        check(dut.fg_stall === 1'b1, "stall_after_grace");

        // FG 恢复 → 超时自清、停转告警自愈
        fg_run = 1'b1;
        #(600_000_000);
        $display("@%0t fg resume: timeout=%b stall=%b period=%0d",
                 $time, dut.fg_timeout, dut.fg_stall, dut.fg_period);
        check(dut.fg_timeout === 1'b0, "fg_timeout_cleared");
        check(dut.fg_stall  === 1'b0, "stall_selfhealed");
        check(dut.fg_period > 32'd99990 && dut.fg_period < 32'd100010, "fg_period_restored");

        if (errors == 0) begin
            $display("tb_top: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_top: %0d ERRORS", errors);
        end
    end

    // 超时保护（主流程 ~2.6s：初始 0.4s + KEY1 0.3s + 帧解码 0.02s +
    // DS 0.4s + FG 回零 4 键 0.24s + 停转/宽限/恢复 ~1.33s）
    initial begin
        #3_200_000_000;
        $fatal(2, "tb_top: TIMEOUT — errors=%0d", errors);
    end
endmodule
