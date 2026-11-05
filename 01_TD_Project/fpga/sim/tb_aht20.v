//============================================================================
// tb_aht20.v — aht20_drv + i2c_master 单元测试（含 aht20_model 行为模型）
//
// 时序压缩：PERIOD_MS=50、MEAS_MS=2（驱动）/ 1（模型）；I2C 保持真实 400kHz。
// 校验：上电未校准 → 0xBE 初始化路径 → 首帧数据（20bit 湿度/温度码，CRC 通路）；
//       输入变化后下一帧跟随；CRC 坏帧 → err 置位且数据保持；CRC 恢复 → err 清零；
//       掉线 → err 黏性 + 数据保持；恢复 → err 清零。
// 换算参考：RH = hum/2^20×100 %；T = temp/2^20×200−50 °C。
//============================================================================
`timescale 1ns/1ps
module tb_aht20 #(parameter CLK_HZ=100_000_000);
    localparam integer CLK_NS = 1000000000/CLK_HZ;

    reg clk = 1'b0;
    always #(CLK_NS/2.0) clk = ~clk;

    reg rst_n = 1'b0;

    wire io_sda, io_scl;
    pullup (io_sda);
    pullup (io_scl);

    reg  present_tb = 1'b1;
    reg  crc_corrupt_tb = 1'b0;           // 1 = 模型送坏 CRC（注错）
    reg  [19:0] hum_in_tb  = 20'h80000;   // 50%RH
    reg  [19:0] temp_in_tb = 20'h66666;   // 30°C

    wire        req;
    wire [6:0]  dev;
    wire [2:0]  nwr;
    wire [7:0]  wr0, wr1, wr2;
    wire [4:0]  nrd;
    wire        ack, err_m, rd_valid;
    wire [7:0]  rd_data;
    wire [4:0]  rd_idx;

    wire        busy, present, err, sample_valid;
    wire [19:0] hum_code, temp_code;

    aht20_drv #(
        .CLK_FREQ  (CLK_HZ),
        .PERIOD_MS (50),
        .MEAS_MS   (2)
    ) u_drv (
        .clk         (clk),
        .rst_n       (rst_n),
        .i2c_req     (req),
        .i2c_dev     (dev),
        .i2c_nwr     (nwr),
        .i2c_wr0     (wr0),
        .i2c_wr1     (wr1),
        .i2c_wr2     (wr2),
        .i2c_nrd     (nrd),
        .i2c_ack     (ack),
        .i2c_err     (err_m),
        .i2c_rd_valid(rd_valid),
        .i2c_rd_data (rd_data),
        .i2c_rd_idx  (rd_idx),
        .busy        (busy),
        .hum_code    (hum_code),
        .temp_code   (temp_code),
        .present     (present),
        .err         (err),
        .sample_valid(sample_valid)
    );

    i2c_master #(
        .CLK_FREQ (CLK_HZ),
        .I2C_FREQ (400_000)
    ) u_i2c (
        .clk        (clk),
        .rst_n      (rst_n),
        .io_sda     (io_sda),
        .io_scl     (io_scl),
        .u_req      (req),
        .u_dev      (dev),
        .u_nwr      (nwr),
        .u_wr0      (wr0),
        .u_wr1      (wr1),
        .u_wr2      (wr2),
        .u_nrd      (nrd),
        .u_ack      (ack),
        .u_err      (err_m),
        .u_rd_valid (rd_valid),
        .u_rd_data  (rd_data),
        .u_rd_idx   (rd_idx)
    );

    aht20_model #(
        .MEAS_MS     (1)
    ) u_model (
        .sda         (io_sda),
        .scl         (io_scl),
        .present     (present_tb),
        .cal_powerup (1'b0),        // 上电未校准 → 走 0xBE 初始化路径
        .hum_in      (hum_in_tb),
        .temp_in     (temp_in_tb),
        .crc_corrupt (crc_corrupt_tb),
        .busy        ()
    );

    //====================================================================
    // 校验与激励
    //====================================================================
    integer errors = 0;
    integer good_samples=0;
    always @(posedge clk) if(sample_valid) begin
        if(err || !present)$fatal(1,"AHT invalid sample pulse");
        good_samples=good_samples+1;
    end
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

    initial begin
        rst_n = 1'b0;
        #(20_000_000);                 // 20ms 复位
        rst_n = 1'b1;

        // 复位释放后：POR 40ms + 状态查询 + 0xBE 初始化 + 10ms + 触发 + 2ms + 读
        // → 首帧数据 ≈ 52.5ms；此处等 100ms 确保 ≥1 帧完成
        #(100_000_000);
        $display("@%0t frame1: present=%b err=%b hum=%05x temp=%05x",
                 $time, present, err, hum_code, temp_code);
        check(present === 1'b1,  "present_after_init");
        check(err    === 1'b0,  "no_err_frame1");
        check(hum_code  == 20'h80000, "hum_code_frame1");
        check(temp_code == 20'h66666, "temp_code_frame1");
        check(busy === 1'b0,  "idle_frame1");
        check(io_sda === 1'b1 && io_scl === 1'b1, "bus_idle_frame1");

        // 换输入 → 下一帧跟随（模型在触发时刻锁存输入）
        hum_in_tb  = 20'hA0000;       // 62.5%RH
        temp_in_tb = 20'h73333;       // 40°C
        #(80_000_000);                // ≥ 1 个测量周期（50ms）
        $display("@%0t frame2: hum=%05x temp=%05x", $time, hum_code, temp_code);
        check(hum_code  == 20'hA0000, "hum_code_frame2");
        check(temp_code == 20'h73333, "temp_code_frame2");

        // CRC 坏帧注入 → err 置位、数据保持旧值（帧被丢弃）
        crc_corrupt_tb = 1'b1;
        hum_in_tb  = 20'hB3333;       // 70%RH（若误更新将被检查捕获）
        temp_in_tb = 20'h80000;       // 50°C
        #(80_000_000);                // ≥ 1 个坏帧完成
        $display("@%0t crc_bad: err=%b hum=%05x temp=%05x",
                 $time, err, hum_code, temp_code);
        check(err === 1'b1, "err_set_crc_bad");
        check(hum_code  == 20'hA0000, "hum_hold_crc_bad");
        check(temp_code == 20'h73333, "temp_hold_crc_bad");

        // CRC 恢复 → 好帧清 err，数据更新到新输入
        crc_corrupt_tb = 1'b0;
        #(80_000_000);
        $display("@%0t crc_ok: err=%b hum=%05x temp=%05x",
                 $time, err, hum_code, temp_code);
        check(err === 1'b0, "err_clear_crc_ok");
        check(hum_code  == 20'hB3333, "hum_code_crc_ok");
        check(temp_code == 20'h80000, "temp_code_crc_ok");

        // 掉线 → err 黏性置位，数据保持旧值
        present_tb = 1'b0;
        #(80_000_000);
        $display("@%0t offline: err=%b hum=%05x temp=%05x",
                 $time, err, hum_code, temp_code);
        check(err === 1'b1, "err_sticky_offline");
        check(hum_code  == 20'hB3333, "hum_hold_offline");
        check(temp_code == 20'h80000, "temp_hold_offline");

        // 恢复 → 好帧自动清 err，数据恢复
        present_tb = 1'b1;
        hum_in_tb  = 20'h99999;       // 60%RH
        temp_in_tb = 20'h4CCCD;       // 10°C
        #(120_000_000);               // 覆盖掉线残留周期 + ≥1 个好帧
        $display("@%0t recover: err=%b hum=%05x temp=%05x",
                 $time, err, hum_code, temp_code);
        check(err === 1'b0, "err_clear_recover");
        check(hum_code  == 20'h99999, "hum_code_recover");
        check(temp_code == 20'h4CCCD, "temp_code_recover");

        check(good_samples>=4, "fresh_sample_pulses");
        if (errors == 0) begin
            $display("tb_aht20: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_aht20: %0d ERRORS", errors);
        end
    end

    // 超时保护
    initial begin
        #700_000_000;
        $fatal(2, "tb_aht20: TIMEOUT — errors=%0d", errors);
    end
endmodule
