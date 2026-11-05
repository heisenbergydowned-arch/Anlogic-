//============================================================================
// tb_ds18b20.v — ds18b20 单元测试（CONV_MS/PERIOD_MS 压缩加速）
//
// 校验：present 检测；两轮温度读数与模型一致（0x0190 → 0x0200）；
//       采样周期断言：两轮 vld 间隔 == PERIOD_MS（15ms ± 0.5ms，
//       协议段 ~9.5ms + 转换 1ms < 周期，剩余由 S_IDLE 补齐——防回归
//       "us_cnt 预装 TAIL_US 导致整轮 1.6s"的旧缺陷）；
//       stale 路径：crc_bad 注入坏 CRC → 连续 3 帧无效 → stale=1 且
//       temperature 保持旧值（不误发 vld）；恢复后一帧即清 stale；
//       器件离线（en=0）后 present 拉低（stale/present 分开上报）。
//
// v0.8 总线故障防护（审核问题②：总线恒低被当有效 0℃）：
//   T5 全 0 帧注入（frame_zero）：总线健康、presence 正常，但读段
//      72 位全 0——Dallas CRC8 初值 0 喂 72 个 0 恰好"通过"。断言：
//      不发 vld、temperature 保持旧值（0x0000 不得进入温控）、
//      bus_short 不误置（单帧异常≠持续短路）、走故障路径不走 stale；
//      清除注入后一帧恢复读到新值。
//   T6 对地短路注入（short_gnd 强拉 0）：presence 恒"在"、总线恒 0。
//      断言：连续 3 次总线故障 → bus_short=1、present=0、
//      vld 冻结、temperature 保持旧值。
//   T7 短路恢复：释放后 bus_short 清零、读到新值。
//
// 退出码（run_sim.bat 依赖）：断言失败 $fatal(1)；看门狗超时 $fatal(2)。
//============================================================================
`timescale 1ns/1ps
module tb_ds18b20 #(parameter CLK_HZ=100_000_000);
    localparam integer CLK_NS = 1000000000/CLK_HZ;
    localparam integer PERIOD_MS_TB = 15;   // > 协议段 ~9.5ms + 转换 1ms

    reg  clk = 1'b0;
    reg  rst_n = 1'b0;
    wire dq;
    wire signed [15:0] temperature;
    wire vld, present, stale, bus_short;

    always #(CLK_NS/2.0) clk = ~clk;

    ds18b20 #(
        .CLK_FREQ  (CLK_HZ),
        .CONV_MS   (1),                    // 仿真压缩
        .PERIOD_MS (PERIOD_MS_TB)
    ) dut (
        .clk        (clk),
        .rst_n      (rst_n),
        .dq         (dq),
        .temperature(temperature),
        .vld        (vld),
        .present    (present),
        .stale      (stale),
        .bus_short  (bus_short)
    );

    reg [15:0] temp_code = 16'h0190;   // 25.0625°C
    reg        en      = 1'b1;
    reg        crc_bad = 1'b0;         // 1 = 模型发坏 CRC（stale 注入）
    reg        frame_zero = 1'b0;      // 1 = 全 0 帧注入（v0.8 T5）

    ds18b20_model u_model (
        .dq       (dq),
        .en       (en),
        .temp_code(temp_code),
        .crc_bad  (crc_bad),
        .frame_zero(frame_zero)
    );

    pullup (dq);   // 4.7kΩ 上拉

    // 对地短路注入：强 0 压过弱上拉（v0.8 T6/T7）
    reg short_gnd = 1'b0;
    assign dq = short_gnd ? 1'b0 : 1'bz;

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

    integer vld_cnt = 0;
    reg [15:0] vld1_temp = 0, vld2_temp = 0, vld3_temp = 0, vld4_temp = 0, vld5_temp = 0;
    real t_vld1 = 0.0, t_vld2 = 0.0;
    always @(posedge vld) begin
        vld_cnt = vld_cnt + 1;
        if (vld_cnt == 1) begin vld1_temp = temperature; t_vld1 = $realtime; end
        if (vld_cnt == 2) begin vld2_temp = temperature; t_vld2 = $realtime; end
        if (vld_cnt == 3) vld3_temp = temperature;
        if (vld_cnt == 4) vld4_temp = temperature;
        if (vld_cnt == 5) vld5_temp = temperature;
    end

    initial begin
        repeat (10) @(posedge clk);
        rst_n = 1'b1;

        // 第一轮：S_IDLE 等 15ms 周期 + 协议段 + 转换 ≈ 25.5ms
        wait (vld_cnt >= 1);
        $display("round1 temperature=0x%04x (expect 0x0190)", vld1_temp);
        check(vld1_temp == 16'h0190, "temp_round1");
        check(present === 1'b1, "present_online");

        // 模型温度改变 → 第二轮应读到新值 + 周期断言
        temp_code = 16'h0200;   // 32°C
        wait (vld_cnt >= 2);
        $display("round2 temperature=0x%04x (expect 0x0200) interval=%.1f ms",
                 vld2_temp, (t_vld2 - t_vld1) / 1e6);
        check(vld2_temp == 16'h0200, "temp_round2");
        check((t_vld2 - t_vld1) > (PERIOD_MS_TB - 0.5) * 1e6 &&
              (t_vld2 - t_vld1) < (PERIOD_MS_TB + 0.5) * 1e6, "period_exact");

        // CRC 坏帧注入：连续 3 帧无效 → stale=1，temperature 保持旧值
        crc_bad = 1'b1;
        wait (stale === 1'b1);
        $display("after 3 bad-crc frames: stale=%b temperature=0x%04x (expect 0x0200)",
                 stale, temperature);
        check(temperature == 16'h0200, "stale_holds_last_good");
        check(present === 1'b1, "stale_present_still_ok");
        check(vld_cnt == 2, "bad_frames_no_vld");

        // 恢复：下一帧有效即清 stale
        crc_bad = 1'b0;
        temp_code = 16'h0150;   // 21°C：恢复帧读到新值
        wait (vld_cnt >= 3);
        $display("recovered frame: stale=%b temperature=0x%04x", stale, vld3_temp);
        check(stale === 1'b0, "stale_cleared_on_good");
        check(vld3_temp == 16'h0150, "temp_after_recover");

        // 器件离线：下一轮复位后 present 应为 0（stale 不因此路径置位）
        en = 1'b0;
        #(25_000_000);   // 25ms > 周期 15ms + 复位段
        $display("present=%b after unplug (expect 0)", present);
        check(present === 1'b0, "present_offline");
        check(bus_short === 1'b0, "unplug_not_short");   // 拔线≠短路

        //--------------------------------------------------------------
        // T5：全 0 帧注入（v0.8）——CRC 恰好"通过"的 0x0000 必须被拒
        //--------------------------------------------------------------
        en = 1'b1;
        frame_zero = 1'b1;
        temp_code = 16'h0250;   // 新温度：验证恢复后读到的是新值而非旧值
        #(33_000_000);          // ≥2 周期：至少一帧全 0 已被读回并拒绝
        $display("after all-zero frames: vld_cnt=%0d temperature=0x%04x (expect 0x0150) stale=%b bus_short=%b",
                 vld_cnt, temperature, stale, bus_short);
        check(vld_cnt == 3, "allzero_frame_no_vld");             // 不得把 0x0000 当有效 0℃ 发 vld
        check(temperature == 16'h0150, "allzero_hold_last_good"); // 温控输入保持旧有效值
        check(bus_short === 1'b0, "allzero_no_false_short");     // 单帧异常≠持续短路
        check(stale === 1'b0, "allzero_bus_path_not_stale");     // 走总线故障路径，不走 stale 路径

        // 清除注入：下一帧恢复，读到新值
        frame_zero = 1'b0;
        wait (vld_cnt >= 4);
        $display("recovered from all-zero: temperature=0x%04x (expect 0x0250)", vld4_temp);
        check(vld4_temp == 16'h0250, "temp_after_allzero_recover");

        //--------------------------------------------------------------
        // T6：总线对地短路（v0.8）——恒 0 总线：presence 假"在"、全 0 帧
        //--------------------------------------------------------------
        short_gnd = 1'b1;
        #(60_000_000);          // ≥3 周期：bus_fail 连续 3 次 → bus_short=1
        $display("after bus short: bus_short=%b present=%b vld_cnt=%0d temperature=0x%04x (expect 0x0250)",
                 bus_short, present, vld_cnt, temperature);
        check(bus_short === 1'b1, "short_detected");
        check(present === 1'b0, "short_present_low");             // 假 presence 被释放检查推翻
        check(vld_cnt == 4, "short_no_vld");                      // 短路期间不发任何 vld
        check(temperature == 16'h0250, "short_hold_last_good");   // 0x0000 不得进入温控

        //--------------------------------------------------------------
        // T7：短路释放 → 自愈
        //--------------------------------------------------------------
        short_gnd = 1'b0;
        temp_code = 16'h0300;   // 48°C
        wait (vld_cnt >= 5);
        $display("recovered from short: bus_short=%b present=%b temperature=0x%04x (expect 0x0300)",
                 bus_short, present, vld5_temp);
        check(bus_short === 1'b0, "short_cleared_on_release");
        check(present === 1'b1, "present_after_short_recover");
        check(vld5_temp == 16'h0300, "temp_after_short_recover");

        if (errors == 0) begin
            $display("tb_ds18b20: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_ds18b20: %0d ERRORS", errors);
        end
    end

    // 超时保护：主流程 ~215ms（含 3 轮 45ms + stale 45ms + 恢复 15ms +
    // 离线 25ms + 全 0 帧 33ms + 恢复 15ms + 短路 60ms + 恢复 ~30ms）
    initial begin
        #320_000_000;
        $fatal(2, "tb_ds18b20: TIMEOUT — errors=%0d vld_cnt=%0d stale=%b bus_short=%b",
               errors, vld_cnt, stale, bus_short);
    end
endmodule
