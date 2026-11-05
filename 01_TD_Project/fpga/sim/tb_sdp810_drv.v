`timescale 1ns/1ps
module tb_sdp810_drv;

localparam CLK_FREQ = 1000;

reg clk;
reg rst_n;

wire        i2c_req;
wire [6:0]  i2c_dev;
wire [2:0]  i2c_nwr;
wire [7:0]  i2c_wr0, i2c_wr1, i2c_wr2;
wire [4:0]  i2c_nrd;
reg         i2c_ack, i2c_err, i2c_rd_valid;
reg  [7:0]  i2c_rd_data;
reg  [4:0]  i2c_rd_idx;
wire        sample_valid;
wire signed [15:0] pressure_raw, temperature_raw;
wire [15:0] scale_factor;
wire [31:0] product_number;
wire [63:0] serial_number;
wire        present, err, stale;
wire [31:0] age_ms;
wire [7:0]  error_code;

sdp810_drv #(
    .CLK_FREQ(CLK_FREQ),
    .POLL_MS(10),
    .STALE_MS(100),
    .RETRY_MS(100),
    .REQUEST_TIMEOUT_MS(100)
) dut (
    .clk(clk), .rst_n(rst_n),
    .i2c_req(i2c_req), .i2c_dev(i2c_dev), .i2c_nwr(i2c_nwr),
    .i2c_wr0(i2c_wr0), .i2c_wr1(i2c_wr1), .i2c_wr2(i2c_wr2),
    .i2c_nrd(i2c_nrd),
    .i2c_ack(i2c_ack), .i2c_err(i2c_err),
    .i2c_rd_valid(i2c_rd_valid), .i2c_rd_data(i2c_rd_data),
    .i2c_rd_idx(i2c_rd_idx),
    .sample_valid(sample_valid), .pressure_raw(pressure_raw),
    .temperature_raw(temperature_raw), .scale_factor(scale_factor),
    .product_number(product_number), .serial_number(serial_number),
    .present(present), .err(err), .stale(stale), .age_ms(age_ms),
    .error_code(error_code)
);

initial clk = 1'b0;
always #5 clk = ~clk;

wire [2:0] d_nwr = i2c_nwr;
wire [4:0] d_nrd = i2c_nrd;
wire [7:0] d_wr0 = i2c_wr0;
wire [7:0] d_wr1 = i2c_wr1;
wire [7:0] d_wr2 = i2c_wr2;

reg [7:0] id_b [0:17];
reg [7:0] ms_b [0:17];
reg [7:0] cmd0 [0:63];
reg [7:0] cmd1 [0:63];

integer inj_txn;
integer inj_kind;
integer txn_no;
integer buffer_index;

localparam W_IDLE = 3'd0;
localparam W_DLY  = 3'd1;
localparam W_SEND = 3'd2;
localparam W_GAP  = 3'd3;
localparam W_HANG = 3'd4;

reg [2:0] wst;
integer   wdly;
integer   wcnt;
integer   slen;
integer   seq [0:19];
reg       rwrite;
reg [4:0] rnrd;
reg       inj_err_r;
reg       inj_hang_r;
reg       inj_coinc_r;
reg       hang_now;

wire [7:0] cur_byte = (rnrd == 5'd18) ? id_b[seq[wcnt]] : ms_b[seq[wcnt]];
wire [4:0] cur_idx  = seq[wcnt][4:0];

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        wst <= W_IDLE;
        i2c_ack <= 1'b0;
        i2c_err <= 1'b0;
        i2c_rd_valid <= 1'b0;
        i2c_rd_data <= 8'd0;
        i2c_rd_idx <= 5'd0;
        wdly <= 0;
        wcnt <= 0;
        slen <= 0;
        rwrite <= 1'b0;
        rnrd <= 5'd0;
        inj_err_r <= 1'b0;
        inj_hang_r <= 1'b0;
        inj_coinc_r <= 1'b0;
        hang_now = 1'b0;
        txn_no <= 0;
    end else begin
        i2c_ack <= 1'b0;
        i2c_err <= 1'b0;
        i2c_rd_valid <= 1'b0;
        case (wst)
        W_IDLE: begin
            if (i2c_req) begin
                cmd0[txn_no] <= d_wr0;
                cmd1[txn_no] <= d_wr1;
                txn_no <= txn_no + 1;
                rwrite <= (d_nwr != 3'd0);
                rnrd   <= d_nrd;
                inj_err_r   <= 1'b0;
                inj_hang_r  <= 1'b0;
                inj_coinc_r <= 1'b0;
                hang_now = 1'b0;
                if (d_nrd == 5'd18) slen <= 18;
                else if (d_nrd == 5'd9) slen <= 9;
                else slen <= 0;
                for (buffer_index = 0; buffer_index < 20; buffer_index = buffer_index + 1)
                    seq[buffer_index] <= (buffer_index < 18) ? buffer_index : 0;
                if ((txn_no + 1) == inj_txn) begin
                    case (inj_kind)
                    1: inj_err_r <= 1'b1;
                    2: begin inj_hang_r <= 1'b1; hang_now = 1'b1; end
                    3: if (d_nrd > 5'd1) slen <= d_nrd - 5'd1;
                    4: begin
                        slen <= d_nrd + 5'd1;
                        for (buffer_index = 0; buffer_index < 20; buffer_index = buffer_index + 1)
                            seq[buffer_index] <= (buffer_index == 0) ? 0 : (((buffer_index - 1) < 18) ? (buffer_index - 1) : 0);
                    end
                    5: begin
                        seq[0] <= 1;
                        seq[1] <= 0;
                    end
                    6: begin
                        slen <= d_nrd + 5'd1;
                        for (buffer_index = 0; buffer_index < 20; buffer_index = buffer_index + 1)
                            seq[buffer_index] <= (buffer_index < d_nrd) ? buffer_index : 0;
                    end
                    7: inj_coinc_r <= 1'b1;
                    default: ;
                    endcase
                end
                wcnt <= 0;
                wdly <= 2;
                if (hang_now) wst <= W_HANG;
                else wst <= W_DLY;
            end
        end
        W_DLY: begin
            if (wdly == 0) begin
                if (inj_err_r) begin
                    i2c_ack <= 1'b1;
                    i2c_err <= 1'b1;
                    wst <= W_GAP;
                end else if (rwrite || (slen == 0)) begin
                    i2c_ack <= 1'b1;
                    wst <= W_GAP;
                end else begin
                    wst <= W_SEND;
                end
            end else begin
                wdly <= wdly - 1;
            end
        end
        W_SEND: begin
            if (inj_coinc_r && (wcnt == (slen - 1))) begin
                i2c_rd_valid <= 1'b1;
                i2c_rd_data  <= cur_byte;
                i2c_rd_idx   <= cur_idx;
                i2c_ack      <= 1'b1;
                wst <= W_GAP;
            end else if (wcnt < slen) begin
                i2c_rd_valid <= 1'b1;
                i2c_rd_data  <= cur_byte;
                i2c_rd_idx   <= cur_idx;
                wcnt <= wcnt + 1;
            end else begin
                i2c_ack <= 1'b1;
                wst <= W_GAP;
            end
        end
        W_GAP:  if (!i2c_req) wst <= W_IDLE;
        W_HANG: if (!i2c_req) wst <= W_IDLE;
        default: wst <= W_IDLE;
        endcase
    end
end

integer samples;
reg signed [15:0] last_p;
reg signed [15:0] last_t;
reg [7:0] last_ec;
reg sv_d;

always @(posedge clk) begin
    if (sample_valid) begin
        samples = samples + 1;
        last_p = pressure_raw;
        last_t = temperature_raw;
    end
    if (err && (error_code != 8'd0))
        last_ec = error_code;
end

always @(posedge clk) begin
    if (sample_valid && sv_d)
        $fatal(1, "sample_valid asserted two consecutive clocks");
    sv_d <= sample_valid;
end

function [7:0] crc2;
    input [7:0] byte_high;
    input [7:0] byte_low;
    integer   bit_index;
    reg [7:0] crc_value;
    begin
        crc_value = 8'hFF ^ byte_high;
        for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
            crc_value = crc_value[7] ? ((crc_value << 1) ^ 8'h31) : (crc_value << 1);
        crc_value = crc_value ^ byte_low;
        for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
            crc_value = crc_value[7] ? ((crc_value << 1) ^ 8'h31) : (crc_value << 1);
        crc2 = crc_value;
    end
endfunction

task chk;
    input            cond;
    input [8*64-1:0] msg;
    begin
        if (!cond) begin
            $display("CHECK FAILED: %0s", msg);
            $fatal(1);
        end
    end
endtask

task do_reset;
    begin
        rst_n = 1'b0;
        samples = 0;
        last_p = 16'sd0;
        last_t = 16'sd0;
        last_ec = 8'd0;
        inj_txn = 0;
        inj_kind = 0;
        repeat (6) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);
    end
endtask

task set_id_good;
    begin
        id_b[0]  = 8'h03; id_b[1]  = 8'h02; id_b[2]  = crc2(8'h03, 8'h02);
        id_b[3]  = 8'h0A; id_b[4]  = 8'h01; id_b[5]  = crc2(8'h0A, 8'h01);
        id_b[6]  = 8'h11; id_b[7]  = 8'h22; id_b[8]  = crc2(8'h11, 8'h22);
        id_b[9]  = 8'h33; id_b[10] = 8'h44; id_b[11] = crc2(8'h33, 8'h44);
        id_b[12] = 8'h55; id_b[13] = 8'h66; id_b[14] = crc2(8'h55, 8'h66);
        id_b[15] = 8'h77; id_b[16] = 8'h88; id_b[17] = crc2(8'h77, 8'h88);
    end
endtask

task set_ms;
    input [15:0] pressure_word;
    input [15:0] temperature_word;
    input [15:0] scale_word;
    begin
        ms_b[0] = pressure_word[15:8]; ms_b[1] = pressure_word[7:0]; ms_b[2] = crc2(pressure_word[15:8], pressure_word[7:0]);
        ms_b[3] = temperature_word[15:8]; ms_b[4] = temperature_word[7:0]; ms_b[5] = crc2(temperature_word[15:8], temperature_word[7:0]);
        ms_b[6] = scale_word[15:8]; ms_b[7] = scale_word[7:0]; ms_b[8] = crc2(scale_word[15:8], scale_word[7:0]);
    end
endtask

task wait_samples;
    input integer sample_target;
    integer wait_cycles;
    begin
        wait_cycles = 0;
        while (samples < sample_target) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 20000) $fatal(1, "timeout waiting for sample_valid");
        end
        #1;
    end
endtask

task wait_ec;
    input [7:0] code;
    integer wait_cycles;
    begin
        wait_cycles = 0;
        while (last_ec !== code) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 20000) $fatal(1, "timeout waiting for error_code");
        end
        #1;
    end
endtask

task wait_stale;
    integer wait_cycles;
    begin
        wait_cycles = 0;
        while (stale !== 1'b1) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 20000) $fatal(1, "timeout waiting for stale");
        end
        #1;
    end
endtask

task wait_id_read;
    integer wait_cycles;
    begin
        wait_cycles = 0;
        while (!(i2c_req && (i2c_nrd == 5'd18))) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 20000) $fatal(1, "timeout waiting for identity read state");
        end
        #1;
    end
endtask

initial begin
    rst_n = 1'b0;
    i2c_ack = 1'b0;
    i2c_err = 1'b0;
    i2c_rd_valid = 1'b0;
    i2c_rd_data = 8'd0;
    i2c_rd_idx = 5'd0;
    samples = 0;
    last_ec = 8'd0;
    inj_txn = 0;
    inj_kind = 0;
    for (buffer_index = 0; buffer_index < 20; buffer_index = buffer_index + 1) seq[buffer_index] = buffer_index;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    wait_samples(1);
    chk(pressure_raw === 16'sd1000, "T01 nominal positive pressure");
    chk(temperature_raw === 16'sd250, "T01 nominal temperature");
    chk(scale_factor === 16'd60, "T01 scale factor");
    chk(product_number === 32'h03020A01, "T01 product number");
    chk(serial_number === 64'h1122334455667788, "T01 serial number");
    chk(present === 1'b1, "T01 present");
    chk(err === 1'b0, "T01 err clear after valid sample");
    chk(stale === 1'b0, "T01 stale clear after valid sample");
    chk(error_code === 8'd0, "T01 error code clear");
    chk(i2c_dev === 7'h25, "T01 device address");
    chk(cmd0[0] === 8'h3F, "T01 addressed stop byte0");
    chk(cmd1[0] === 8'hF9, "T01 addressed stop byte1");
    chk(cmd0[1] === 8'h36, "T01 product id cmd byte0");
    chk(cmd1[1] === 8'h7C, "T01 product id cmd byte1");
    chk(cmd0[2] === 8'hE1, "T01 product id read cmd byte0");
    chk(cmd1[2] === 8'h02, "T01 product id read cmd byte1");
    chk(cmd0[4] === 8'h36, "T01 start cmd byte0");
    chk(cmd1[4] === 8'h1E, "T01 start cmd byte1");

    do_reset;
    set_id_good;
    set_ms(16'd0, 16'sd0, 16'd60);
    wait_samples(1);
    chk(pressure_raw === 16'sd0, "T02 zero pressure");
    chk(err === 1'b0, "T02 zero Pa valid when checks pass");
    set_ms(16'hFF9C, -16'sd50, 16'd60);
    wait_samples(2);
    chk(pressure_raw === -16'sd100, "T02 negative pressure");
    chk(temperature_raw === -16'sd50, "T02 negative temperature");

    do_reset;
    set_id_good;
    set_ms(16'hBEEF, 16'sd0, 16'd60);
    wait_samples(1);
    chk(pressure_raw === -16'sd16657, "T03 crc(0xBEEF)==0x92 accepted");
    chk(error_code === 8'd0, "T03 no crc error for BEEF word");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    ms_b[2] = ms_b[2] ^ 8'h01;
    wait_ec(8'h04);
    chk(samples === 0, "T04 no sample on pressure crc error");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    ms_b[5] = ms_b[5] ^ 8'h01;
    wait_ec(8'h04);
    chk(samples === 0, "T05 no sample on temperature crc error");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    ms_b[8] = ms_b[8] ^ 8'h01;
    wait_ec(8'h04);
    chk(samples === 0, "T06 no sample on scale crc error");

    do_reset;
    set_id_good;
    id_b[2] = id_b[2] ^ 8'h01;
    set_ms(16'd1000, 16'd250, 16'd60);
    wait_ec(8'h04);
    chk(samples === 0, "T07 no sample on identity crc error");
    chk(present === 1'b0, "T07 not present after identity crc error");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd61);
    wait_ec(8'h06);
    chk(samples === 0, "T08 no sample on wrong scale");

    do_reset;
    set_id_good;
    id_b[3] = 8'h0B;
    id_b[5] = crc2(id_b[3], id_b[4]);
    set_ms(16'd1000, 16'd250, 16'd60);
    wait_ec(8'h05);
    chk(samples === 0, "T09 no sample on 125Pa model");
    chk(present === 1'b0, "T09 not present on wrong model");

    do_reset;
    set_id_good;
    set_ms(16'd30000, 16'sd0, 16'd60);
    wait_samples(1);
    chk(pressure_raw === 16'sd30000, "T10 +30000 accepted");
    set_ms(16'h8AD0, 16'sd0, 16'd60);
    wait_samples(2);
    chk(pressure_raw === -16'sd30000, "T10 -30000 accepted");

    do_reset;
    set_id_good;
    set_ms(16'h8000, 16'sd0, 16'd60);
    wait_ec(8'h07);
    chk(samples === 0, "T11 -32768 out of range no wrap");

    do_reset;
    set_id_good;
    set_ms(16'd30001, 16'sd0, 16'd60);
    wait_ec(8'h07);
    chk(samples === 0, "T11 +30001 out of range");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    inj_txn = 6;
    inj_kind = 3;
    wait_ec(8'h03);
    chk(samples === 0, "T12 truncated read rejected");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    inj_txn = 6;
    inj_kind = 4;
    wait_ec(8'h03);
    chk(samples === 0, "T13 duplicate byte rejected");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    inj_txn = 6;
    inj_kind = 5;
    wait_ec(8'h03);
    chk(samples === 0, "T14 reordered byte rejected");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    inj_txn = 6;
    inj_kind = 6;
    wait_ec(8'h03);
    chk(samples === 0, "T15 extra byte rejected");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    inj_txn = 6;
    inj_kind = 1;
    wait_ec(8'h01);
    chk(samples === 0, "T16 NACK reported as bus error");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    inj_txn = 6;
    inj_kind = 2;
    wait_ec(8'h02);
    chk(samples === 0, "T17 missing ack reported as request timeout");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    wait_samples(1);
    chk(stale === 1'b0, "T18 fresh after valid sample");
    ms_b[2] = ms_b[2] ^ 8'h01;
    wait_stale;
    chk(age_ms >= 32'd100, "T18 age tracked past stale window");
    chk(samples === 1, "T18 no new sample while faulty");
    chk(err === 1'b1, "T18 err asserted while faulty");
    set_ms(16'd2000, 16'd300, 16'd60);
    wait_samples(2);
    chk(pressure_raw === 16'sd2000, "T19 recovery sample published");
    chk(err === 1'b0, "T19 err cleared after recovery");
    chk(stale === 1'b0, "T19 stale cleared after recovery");
    chk(error_code === 8'd0, "T19 error code cleared after recovery");

    do_reset;
    set_id_good;
    set_ms(16'd1000, 16'd250, 16'd60);
    wait_id_read;
    rst_n = 1'b0;
    repeat (3) @(posedge clk);
    chk(i2c_req === 1'b0, "T20 req deasserted by reset");
    chk(sample_valid === 1'b0, "T20 no sample during reset");
    chk(err === 1'b1, "T20 err high after reset");
    chk(stale === 1'b1, "T20 stale high after reset");
    chk(age_ms === 32'd0, "T20 age cleared by reset");
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    do_reset;
    set_id_good;
    set_ms(16'd1500, 16'd260, 16'd60);
    inj_txn = 6;
    inj_kind = 7;
    wait_samples(1);
    chk(pressure_raw === 16'sd1500, "T21 ack coincident with last byte");
    chk(temperature_raw === 16'sd260, "T21 coincident temperature");

    $display("TB_SDP810_DRV: all checks passed (T01-T21)");
    $finish;
end

endmodule
