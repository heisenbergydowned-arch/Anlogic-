//============================================================================
// tb_bmp280.v — bmp280_drv + i2c_master 单元测试（含 bmp280_model 行为模型）
//
// 时序压缩：PERIOD_MS=50、MEAS_MS=2（驱动）/ 1（模型）；I2C 保持真实 400kHz。
// 校验：chip id（0x58）→ 24 字节校准参数（0x88+i 逐一比对）→ 0xF4 配置
//       → 强制模式首帧 20bit 压力/温度原始码；输入变化下一帧跟随；
//       掉线 → err 黏性 + 数据保持；恢复 → err 清零。
// 注意：本测试同时覆盖 i2c_master 的 RESTART 路径（写子地址 + 重复 START 读）。
//============================================================================
`timescale 1ns/1ps
module tb_bmp280 #(parameter CLK_HZ=100_000_000);
    localparam integer CLK_NS = 1000000000/CLK_HZ;

    reg clk = 1'b0;
    always #(CLK_NS/2.0) clk = ~clk;

    reg rst_n = 1'b0;

    wire io_sda, io_scl;
    pullup (io_sda);
    pullup (io_scl);

    reg present_tb = 1'b1;

    // 校准模式：字节 i（0..23）= 0x88+i，覆盖 0x88..0x9F
    wire [191:0] cal_tb;
    genvar gi;
    generate
        for (gi = 0; gi < 24; gi = gi + 1) begin : g_cal
            assign cal_tb[gi*8 +: 8] = 8'h88 + gi[7:0];
        end
    endgenerate

    reg  [19:0] t_raw_tb = 20'hABCDE;
    reg  [19:0] p_raw_tb = 20'h12345;

    wire        req;
    wire [6:0]  dev;
    wire [2:0]  nwr;
    wire [7:0]  wr0, wr1, wr2;
    wire [4:0]  nrd;
    wire        ack, err_m, rd_valid;
    wire [7:0]  rd_data;
    wire [4:0]  rd_idx;

    wire        busy, present, err, sample_valid;
    wire [7:0]   chip_id;
    wire [191:0] cal_regs;
    wire [19:0]  t_raw, p_raw;

    bmp280_drv #(
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
        .chip_id     (chip_id),
        .cal_regs    (cal_regs),
        .t_raw       (t_raw),
        .p_raw       (p_raw),
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

    bmp280_model #(
        .MEAS_MS (1)
    ) u_model (
        .sda      (io_sda),
        .scl      (io_scl),
        .present  (present_tb),
        .cal_in   (cal_tb),
        .t_raw_in (t_raw_tb),
        .p_raw_in (p_raw_tb)
    );

    //====================================================================
    // 校验与激励
    //====================================================================
    integer errors = 0;
    integer good_samples=0;
    always @(posedge clk) if(sample_valid) begin
        if(err || !present)$fatal(1,"BMP invalid sample pulse");
        good_samples=good_samples+1;
    end
    integer i;
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

        // 复位释放后：POR 3ms + ID + 24 字节校准 + 0xF4 配置 + 触发 + 2ms + 读
        // → 首帧数据 ≈ 6ms；此处等 40ms 确保 ≥1 帧完成
        #(40_000_000);
        $display("@%0t frame1: id=%02x present=%b err=%b t=%05x p=%05x",
                 $time, chip_id, present, err, t_raw, p_raw);
        check(chip_id == 8'h58,    "chip_id_0x58");
        check(present === 1'b1,  "present_after_id");
        check(err    === 1'b0,  "no_err_frame1");
        check(t_raw == 20'hABCDE, "t_raw_frame1");
        check(p_raw == 20'h12345, "p_raw_frame1");
        check(busy === 1'b0,  "idle_frame1");
        check(io_sda === 1'b1 && io_scl === 1'b1, "bus_idle_frame1");

        // 校准字 24 字节逐一比对（小端打包：cal_regs[i*8+:8] = mem[0x88+i]）
        for (i = 0; i < 24; i = i + 1) begin
            if (cal_regs[i*8 +: 8] !== 8'h88 + i) begin
                errors = errors + 1;
                $display("[cal_byte_%0d] FAIL got=%02x exp=%02x @%0t",
                         i, cal_regs[i*8 +: 8], 8'h88 + i, $time);
            end
        end
        if (errors == 0) $display("cal_regs: 24 bytes OK");

        // 换输入 → 下一帧跟随（模型在强制模式触发后更新寄存器）
        t_raw_tb = 20'h54321;
        p_raw_tb = 20'h3FEDC;
        #(80_000_000);                // ≥ 1 个测量周期（50ms）
        $display("@%0t frame2: t=%05x p=%05x", $time, t_raw, p_raw);
        check(t_raw == 20'h54321, "t_raw_frame2");
        check(p_raw == 20'h3FEDC, "p_raw_frame2");

        // 掉线 → err 黏性置位，数据保持旧值
        present_tb = 1'b0;
        #(80_000_000);
        $display("@%0t offline: err=%b t=%05x p=%05x", $time, err, t_raw, p_raw);
        check(err === 1'b1, "err_sticky_offline");
        check(t_raw == 20'h54321, "t_hold_offline");
        check(p_raw == 20'h3FEDC, "p_hold_offline");

        // 恢复 → 好帧自动清 err，数据恢复
        present_tb = 1'b1;
        t_raw_tb = 20'h0FEDC;
        p_raw_tb = 20'h20000;
        #(120_000_000);               // 覆盖掉线残留周期 + ≥1 个好帧
        $display("@%0t recover: err=%b t=%05x p=%05x", $time, err, t_raw, p_raw);
        check(err === 1'b0, "err_clear_recover");
        check(t_raw == 20'h0FEDC, "t_raw_recover");
        check(p_raw == 20'h20000, "p_raw_recover");

        check(good_samples>=3, "fresh_sample_pulses");
        if (errors == 0) begin
            $display("tb_bmp280: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_bmp280: %0d ERRORS", errors);
        end
    end

    // 超时保护
    initial begin
        #450_000_000;
        $fatal(2, "tb_bmp280: TIMEOUT — errors=%0d", errors);
    end
endmodule
