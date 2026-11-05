`timescale 1ns/1ps
module tb_dbg_i2c;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n = 1'b0;

    wire io_sda, io_scl;
    pullup (io_sda);
    pullup (io_scl);

    reg        req = 1'b0;
    reg [6:0]  dev = 7'h38;
    reg [2:0]  nwr = 3'd0;
    reg [7:0]  wr0 = 8'd0, wr1 = 8'd0, wr2 = 8'd0;
    reg [4:0]  nrd = 5'd0;
    wire       ack, err, rd_valid;
    wire [7:0] rd_data;
    wire [4:0] rd_idx;

    i2c_master #(
        .CLK_FREQ (100_000_000),
        .I2C_FREQ (400_000)
    ) u_i2c (
        .clk(clk), .rst_n(rst_n),
        .io_sda(io_sda), .io_scl(io_scl),
        .u_req(req), .u_dev(dev), .u_nwr(nwr),
        .u_wr0(wr0), .u_wr1(wr1), .u_wr2(wr2), .u_nrd(nrd),
        .u_ack(ack), .u_err(err),
        .u_rd_valid(rd_valid), .u_rd_data(rd_data), .u_rd_idx(rd_idx)
    );

    aht20_model #(
        .MEAS_MS (1)
    ) u_model (
        .sda(io_sda), .scl(io_scl),
        .present(1'b1),
        .cal_powerup(1'b0),
        .hum_in(20'h80000), .temp_in(20'h66666),
        .busy()
    );

    // BMP280 模型共享总线（地址 0x76），校准字节 i = 0x88+i
    wire [191:0] cal_dbg;
    genvar gi;
    generate
        for (gi = 0; gi < 24; gi = gi + 1) begin : g_cal
            assign cal_dbg[gi*8 +: 8] = 8'h88 + gi[7:0];
        end
    endgenerate
    bmp280_model #(
        .MEAS_MS (1)
    ) u_bmp (
        .sda(io_sda), .scl(io_scl),
        .present(1'b1),
        .cal_in(cal_dbg),
        .t_raw_in(20'hABCDE), .p_raw_in(20'h12345)
    );

    task xfer;
        input [2:0] t_nwr;
        input [7:0] t_wr0, t_wr1, t_wr2;
        input [4:0] t_nrd;
        begin
            nwr = t_nwr; wr0 = t_wr0; wr1 = t_wr1; wr2 = t_wr2; nrd = t_nrd;
            @(negedge clk);
            req = 1'b1;
            wait (ack);
            @(negedge clk);
            req = 1'b0;
            $display("@%0t xfer(wr=%0d,%02x %02x %02x, rd=%0d) ack err=%b",
                     $time, t_nwr, t_wr0, t_wr1, t_wr2, t_nrd, err);
        end
    endtask

    always @(posedge clk)
        if (rd_valid) $display("@%0t RD idx=%0d data=%02x", $time, rd_idx, rd_data);

    // 模型内部状态追踪（每个 SCL 沿）
    always @(u_model.scl)
        $display("@%0t [mdl] scl=%b bitn=%0d sda_en=%b sda_bit=%b mack=%b reading=%b rxsh=%02x addr_seen=%b rd_idx=%0d",
                 $time, u_model.scl, u_model.bitn, u_model.sda_en, u_model.sda_bit,
                 u_model.mack, u_model.reading, u_model.rxsh, u_model.addr_seen, u_model.rd_idx);

    // 主机内部状态追踪（状态切换 + 每 100 clk 快照）
    always @(u_i2c.st)
        $display("@%0t [mst] st=%0d ph=%0d ph_lim=%0d bit_cnt=%0d byte_idx=%0d sh_tx=%02x sda_oe=%b scl_oe=%b rx_byte=%b in_rd=%b wr_left=%0d rd_left=%0d",
                 $time, u_i2c.st, u_i2c.ph, u_i2c.ph_lim, u_i2c.bit_cnt, u_i2c.byte_idx,
                 u_i2c.sh_tx, u_i2c.sda_oe, u_i2c.scl_oe, u_i2c.rx_byte, u_i2c.in_rd,
                 u_i2c.wr_left, u_i2c.rd_left);

    // BMP 模型状态追踪
    always @(u_bmp.scl)
        $display("@%0t [bmp] scl=%b bitn=%0d sda_en=%b sda_bit=%b mack=%b reading=%b rxsh=%02x addr_seen=%b addr_ok=%b rw_r=%b ptr=%02x ptr_seen=%b started=%b",
                 $time, u_bmp.scl, u_bmp.bitn, u_bmp.sda_en, u_bmp.sda_bit,
                 u_bmp.mack, u_bmp.reading, u_bmp.rxsh, u_bmp.addr_seen, u_bmp.addr_ok,
                 u_bmp.rw_r, u_bmp.ptr, u_bmp.ptr_seen, u_bmp.started);

    initial begin
        #(1_000_000);
        rst_n = 1'b1;
        #(100_000);
        $display("=== 1: pure read status ===");
        xfer(3'd0, 8'h00, 8'h00, 8'h00, 5'd1);
        #(10_000);
        $display("=== 2: init write BE 08 00 ===");
        xfer(3'd3, 8'hBE, 8'h08, 8'h00, 5'd0);
        #(20_000_000);                    // 20ms：等初始化完成
        $display("=== 3: read status again ===");
        xfer(3'd0, 8'h00, 8'h00, 8'h00, 5'd1);
        #(10_000);
        $display("=== 4: trigger AC 33 00 ===");
        xfer(3'd3, 8'hAC, 8'h33, 8'h00, 5'd0);
        #(2_000_000);                     // 2ms：等测量完成
        $display("=== 5: read 7 bytes ===");
        xfer(3'd0, 8'h00, 8'h00, 8'h00, 5'd7);
        #(10_000);
        dev = 7'h76;
        $display("=== 6: BMP combined read ID (W D0 + RS + R 1) ===");
        xfer(3'd1, 8'hD0, 8'h00, 8'h00, 5'd1);
        #(10_000);
        $display("=== 7: BMP combined read cal (W 88 + RS + R 6) ===");
        xfer(3'd1, 8'h88, 8'h00, 8'h00, 5'd6);
        #(10_000);
        $display("=== 8: BMP write F4 25 ===");
        xfer(3'd2, 8'hF4, 8'h25, 8'h00, 5'd0);
        #(2_000_000);
        $display("=== 9: BMP combined read data (W F7 + RS + R 6) ===");
        xfer(3'd1, 8'hF7, 8'h00, 8'h00, 5'd6);
        #(10_000);
        $display("=== done ===");
        $finish;
    end
endmodule
