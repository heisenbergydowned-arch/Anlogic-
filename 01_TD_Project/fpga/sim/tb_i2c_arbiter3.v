`timescale 1ns/1ps
module tb_i2c_arbiter3;

localparam CLK_FREQ = 1000;

reg clk;
reg rst_n;

reg  [2:0]  requests;
reg  [20:0] devices;
reg  [8:0]  write_counts;
reg  [23:0] wb0, wb1, wb2;
reg  [14:0] read_counts;
wire        master_req;
wire [6:0]  master_dev;
wire [2:0]  master_nwr;
wire [7:0]  master_wr0, master_wr1, master_wr2;
wire [4:0]  master_nrd;
reg         master_ack, master_err, master_rd_valid;
wire [2:0]  acknowledgements, errors, read_valid;
wire        master_reset_n;

i2c_arbiter3 #(
    .CLK_FREQ(CLK_FREQ),
    .TIMEOUT_MS(20)
) dut (
    .clk(clk), .rst_n(rst_n),
    .requests(requests), .devices(devices), .write_counts(write_counts),
    .write_byte0(wb0), .write_byte1(wb1), .write_byte2(wb2),
    .read_counts(read_counts),
    .master_req(master_req), .master_dev(master_dev), .master_nwr(master_nwr),
    .master_wr0(master_wr0), .master_wr1(master_wr1), .master_wr2(master_wr2),
    .master_nrd(master_nrd),
    .master_ack(master_ack), .master_err(master_err),
    .master_rd_valid(master_rd_valid),
    .acknowledgements(acknowledgements), .errors(errors),
    .read_valid(read_valid),
    .master_reset_n(master_reset_n)
);

initial clk = 1'b0;
always #5 clk = ~clk;

integer mm_delay;
reg     mm_hang;
reg     mm_errmode;
reg     mm_force_ack;
reg     mm_rdv;
reg     mm_pending;
integer mm_t;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        master_ack <= 1'b0;
        master_err <= 1'b0;
        master_rd_valid <= 1'b0;
        mm_pending <= 1'b0;
        mm_t <= 0;
    end else begin
        master_err <= 1'b0;
        master_rd_valid <= mm_rdv;
        if (mm_force_ack) begin
            master_ack <= 1'b1;
            mm_pending <= 1'b0;
            mm_t <= 0;
        end else if (!master_reset_n) begin
            master_ack <= 1'b0;
            mm_pending <= 1'b0;
            mm_t <= 0;
        end else if (mm_pending) begin
            if (mm_t == 0) begin
                master_ack <= 1'b1;
                master_err <= mm_errmode;
                mm_pending <= 1'b0;
            end else begin
                master_ack <= 1'b0;
                mm_t <= mm_t - 1;
            end
        end else if (master_req && !mm_hang) begin
            master_ack <= 1'b0;
            mm_pending <= 1'b1;
            mm_t <= mm_delay;
        end else begin
            master_ack <= 1'b0;
        end
    end
end

integer c0, c1, c2;
reg     mreq_d;
reg [2:0] ack_seen, err_seen, rdv_seen;

always @(posedge clk) begin
    #1;
    if (master_req && !mreq_d) begin
        case (dut.owner)
        2'd0: c0 = c0 + 1;
        2'd1: c1 = c1 + 1;
        default: c2 = c2 + 1;
        endcase
    end
    mreq_d = master_req;
    if (acknowledgements !== 3'b000) ack_seen = ack_seen | acknowledgements;
    if (errors !== 3'b000) err_seen = err_seen | errors;
    if (read_valid !== 3'b000) rdv_seen = rdv_seen | read_valid;
end

reg [6:0] dev_e [0:2];
reg [2:0] nwr_e [0:2];
reg [4:0] nrd_e [0:2];
reg [7:0] w0_e  [0:2];
reg [7:0] w1_e  [0:2];
reg [7:0] w2_e  [0:2];

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

task ar_reset;
    begin
        rst_n = 1'b0;
        requests = 3'b000;
        mm_hang = 1'b0;
        mm_errmode = 1'b0;
        mm_force_ack = 1'b0;
        mm_rdv = 1'b0;
        mm_delay = 3;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);
        c0 = 0; c1 = 0; c2 = 0;
        ack_seen = 3'b000;
        err_seen = 3'b000;
        rdv_seen = 3'b000;
    end
endtask

task wait_req;
    integer wait_cycles;
    begin
        wait_cycles = 0;
        while (master_req !== 1'b1) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 4000) $fatal(1, "timeout waiting for master_req");
        end
    end
endtask

task wait_ackseen;
    integer wait_cycles;
    begin
        wait_cycles = 0;
        while (ack_seen === 3'b000) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 4000) $fatal(1, "timeout waiting for acknowledgement");
        end
    end
endtask

task wait_low_reset;
    integer wait_cycles;
    begin
        wait_cycles = 0;
        while (master_reset_n !== 1'b0) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 4000) $fatal(1, "timeout waiting for master_reset_n low");
        end
    end
endtask

task wait_grant;
    input [1:0] eo;
    integer wait_cycles;
    begin
        wait_cycles = 0;
        while (master_req === 1'b1) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 4000) $fatal(1, "timeout waiting for grant end");
        end
        wait_cycles = 0;
        while (master_req !== 1'b1) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 4000) $fatal(1, "timeout waiting for grant");
        end
        #1;
        chk(dut.owner === eo, "granted owner mismatch");
        chk(master_dev === dev_e[eo], "granted device mismatch");
        chk(master_nwr === nwr_e[eo], "granted nwr mismatch");
        chk(master_nrd === nrd_e[eo], "granted nrd mismatch");
        chk(master_wr0 === w0_e[eo], "granted wr0 mismatch");
        chk(master_wr1 === w1_e[eo], "granted wr1 mismatch");
        chk(master_wr2 === w2_e[eo], "granted wr2 mismatch");
    end
endtask

initial begin
    rst_n = 1'b0;
    requests = 3'b000;
    devices = {7'h25, 7'h76, 7'h38};
    write_counts = {3'd2, 3'd1, 3'd3};
    read_counts = {5'd9, 5'd6, 5'd0};
    wb0 = {8'hAA, 8'hBB, 8'hCC};
    wb1 = {8'hDD, 8'hEE, 8'h11};
    wb2 = {8'h22, 8'h33, 8'h44};
    master_ack = 1'b0;
    master_err = 1'b0;
    master_rd_valid = 1'b0;
    mm_delay = 3;
    mm_hang = 1'b0;
    mm_errmode = 1'b0;
    mm_force_ack = 1'b0;
    mm_rdv = 1'b0;
    mm_pending = 1'b0;
    mm_t = 0;
    c0 = 0; c1 = 0; c2 = 0;
    mreq_d = 1'b0;
    ack_seen = 3'b000;
    err_seen = 3'b000;
    rdv_seen = 3'b000;

    dev_e[0] = 7'h38; dev_e[1] = 7'h76; dev_e[2] = 7'h25;
    nwr_e[0] = 3'd3;  nwr_e[1] = 3'd1;  nwr_e[2] = 3'd2;
    nrd_e[0] = 5'd0;  nrd_e[1] = 5'd6;  nrd_e[2] = 5'd9;
    w0_e[0]  = 8'hCC; w0_e[1]  = 8'hBB; w0_e[2]  = 8'hAA;
    w1_e[0]  = 8'h11; w1_e[1]  = 8'hEE; w1_e[2]  = 8'hDD;
    w2_e[0]  = 8'h44; w2_e[1]  = 8'h33; w2_e[2]  = 8'h22;

    ar_reset;
    requests = 3'b111;
    wait_grant(2'd0);
    wait_grant(2'd1);
    wait_grant(2'd2);
    wait_grant(2'd0);
    wait_grant(2'd1);
    requests = 3'b000;
    $display("AR1 round robin order ok");

    ar_reset;
    requests = 3'b111;
    repeat (400) @(posedge clk);
    chk(c0 >= 5, "AR2 client0 served");
    chk(c1 >= 5, "AR2 client1 served");
    chk(c2 >= 5, "AR2 client2 served");
    chk(((c0 > c1) ? (c0 - c1) : (c1 - c0)) <= 2, "AR2 fairness 0 vs 1");
    chk(((c1 > c2) ? (c1 - c2) : (c2 - c1)) <= 2, "AR2 fairness 1 vs 2");
    chk(((c0 > c2) ? (c0 - c2) : (c2 - c0)) <= 2, "AR2 fairness 0 vs 2");
    requests = 3'b000;
    $display("AR2 fairness ok");

    ar_reset;
    requests = 3'b010;
    mm_delay = 5;
    wait_req;
    chk(dut.owner === 2'd1, "AR3 owner is client1");
    chk(master_dev === 7'h76, "AR3 device routed");
    chk(master_nwr === 3'd1, "AR3 nwr routed");
    chk(master_nrd === 5'd6, "AR3 nrd routed");
    chk(master_wr0 === 8'hBB, "AR3 wr0 routed");
    chk(master_wr1 === 8'hEE, "AR3 wr1 routed");
    chk(master_wr2 === 8'h33, "AR3 wr2 routed");
    wait_ackseen;
    chk(ack_seen === 3'b010, "AR3 only owner1 acknowledged");
    chk(err_seen === 3'b000, "AR3 no error routed");
    requests = 3'b000;
    $display("AR3 owner-only reply ok");

    ar_reset;
    requests = 3'b001;
    mm_delay = 3;
    wait_req;
    wait_ackseen;
    @(posedge clk);
    requests = 3'b000;
    repeat (30) @(posedge clk);
    chk(c0 === 1, "AR4 no duplicate transaction after delayed drop");
    chk(ack_seen === 3'b001, "AR4 single acknowledgement");
    $display("AR4 delayed request drop ok");

    ar_reset;
    requests = 3'b001;
    mm_delay = 60;
    wait_req;
    chk(dut.owner === 2'd0, "AR5 owner0 before cancel");
    repeat (3) @(posedge clk);
    requests = 3'b000;
    wait_low_reset;
    chk(ack_seen === 3'b000, "AR5 no ack delivered on cancellation");
    repeat (12) @(posedge clk);
    chk(master_req === 1'b0, "AR5 bus released after cancellation");
    $display("AR5 owner cancellation ok");

    ar_reset;
    requests = 3'b100;
    mm_hang = 1'b1;
    wait_req;
    chk(dut.owner === 2'd2, "AR6 owner2");
    wait_ackseen;
    chk(ack_seen === 3'b100, "AR6 watchdog ack to owner2");
    chk(err_seen === 3'b100, "AR6 watchdog error to owner2");
    requests = 3'b000;
    wait_low_reset;
    chk(master_req === 1'b0, "AR6 bus released during watchdog reset");
    mm_hang = 1'b0;
    repeat (12) @(posedge clk);
    chk(master_req === 1'b0, "AR6 bus idle after watchdog");
    $display("AR6 watchdog ok");

    ar_reset;
    requests = 3'b001;
    mm_delay = 60;
    wait_req;
    repeat (2) @(posedge clk);
    requests = 3'b000;
    wait_low_reset;
    ack_seen = 3'b000;
    err_seen = 3'b000;
    mm_force_ack = 1'b1;
    repeat (2) @(posedge clk);
    chk(ack_seen === 3'b000, "AR7 stale reply suppressed during reset");
    chk(err_seen === 3'b000, "AR7 no spurious error during reset");
    mm_force_ack = 1'b0;
    requests = 3'b100;
    mm_delay = 3;
    wait_req;
    chk(dut.owner === 2'd2, "AR7 new owner after reset");
    wait_ackseen;
    chk(ack_seen === 3'b100, "AR7 new owner gets own acknowledgement");
    requests = 3'b000;
    repeat (20) @(posedge clk);
    $display("AR7 no stale reply leak ok");

    ar_reset;
    requests = 3'b100;
    mm_delay = 30;
    wait_req;
    chk(dut.owner === 2'd2, "AR8 owner2");
    repeat (2) @(posedge clk);
    mm_rdv = 1'b1;
    repeat (2) @(posedge clk);
    mm_rdv = 1'b0;
    repeat (2) @(posedge clk);
    chk(rdv_seen === 3'b100, "AR8 read_valid routed to owner only");
    requests = 3'b000;

    $display("TB_I2C_ARBITER3: all checks passed (AR1-AR8)");
    $finish;
end

endmodule
