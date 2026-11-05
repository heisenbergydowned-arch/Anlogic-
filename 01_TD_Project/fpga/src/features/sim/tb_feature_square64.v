`timescale 1ns/1ps
// Self-checking testbench for feature_square64.
//
// The reference is an independent 128-bit extended multiply,
//     ref = {64'd0,v} * {64'd0,v}
// so the check does not reuse the four-limb / shift / accumulate algorithm that
// is under test. Coverage: 0, 1, 2^64-1, 2^54-1, powers of two at every limb
// boundary, low-limb-only and high-limb-only operands, mixed high/low limb
// values, and 4096 pseudo-random operands from a fixed-seed LCG.
//
// Result: prints SQUARE64_TB_PASS or SQUARE64_TB_FAIL at the end.
module tb_feature_square64;
    reg clk, rst_n, start;
    reg [63:0] operand;
    wire busy, done;
    wire [127:0] result;

    integer checks, errors, i;
    reg [63:0] rnd;

    localparam integer MAX_WAIT = 200;

    feature_square64 dut (
        .clk(clk), .rst_n(rst_n), .start(start), .operand(operand),
        .busy(busy), .done(done), .result(result)
    );

    always #5 clk = ~clk; // 100 MHz

    // Independent reference: 128-bit operand width forces a full-width multiply.
    function [127:0] ref_square;
        input [63:0] v;
        begin
            ref_square = {64'd0, v} * {64'd0, v};
        end
    endfunction

    task check_one;
        input [63:0] v;
        reg [127:0] expected;
        integer waited;
        begin
            @(negedge clk);
            operand = v;
            start   = 1'b1;
            @(negedge clk);
            start   = 1'b0;

            waited = 0;
            while ((done !== 1'b1) && (waited < MAX_WAIT)) begin
                @(posedge clk); #1;
                waited = waited + 1;
            end

            expected = ref_square(v);
            checks = checks + 1;

            if (done !== 1'b1) begin
                errors = errors + 1;
                $display("FAIL timeout operand=%h", v);
            end else if (waited != 21 || busy || result !== expected) begin
                errors = errors + 1;
                $display("FAIL operand=%h got=%h expected=%h (latency %0d)",
                         v, result, expected, waited);
            end

            @(negedge clk); // let done fall and the squarer return to idle
        end
    endtask

    initial begin
        checks = 0;
        errors = 0;
        clk    = 1'b0;
        rst_n  = 1'b0;
        start  = 1'b0;
        operand= 64'd0;

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        // Boundary and structural vectors
        check_one(64'h0000_0000_0000_0000); // zero
        check_one(64'h0000_0000_0000_0001); // one
        check_one(64'h0000_0000_0000_0002);
        check_one(64'hFFFF_FFFF_FFFF_FFFF); // max
        check_one(64'h003F_FFFF_FFFF_FFFF); // 2^54-1
        check_one(64'h0040_0000_0000_0000); // 2^54
        check_one(64'h0000_0000_0000_FFFF); // limb0 all ones
        check_one(64'h0000_0000_FFFF_0000); // limb1 only
        check_one(64'h0000_FFFF_0000_0000); // limb2 only
        check_one(64'hFFFF_0000_0000_0000); // limb3 only
        check_one(64'hFFFF_FFFF_0000_0000); // high limbs only
        check_one(64'h0000_0000_FFFF_FFFF); // low limbs only
        check_one(64'h0000_0000_0001_0001); // mixed low limbs
        check_one(64'h0000_0001_0000_0001); // mixed limb0 + limb2
        check_one(64'h1000_0000_0000_0001); // mixed limb0 + limb3
        check_one(64'h8000_0000_0000_0001); // mixed, top bit set
        check_one(64'h1234_5678_9ABC_DEF0);
        check_one(64'hFEDC_BA98_7654_3210);
        check_one(64'h8000_0000_0000_0000); // 2^63
        check_one(64'h0000_0001_0000_0000); // 2^32

        // Deterministic pseudo-random operands (fixed-seed 64-bit LCG)
        rnd = 64'h0123_4567_89AB_CDEF;
        for (i = 0; i < 4096; i = i + 1) begin
            rnd = (rnd * 64'h5851_F42D_4C95_7F2D) + 64'h1405_7B7E_F767_814F;
            check_one(rnd);
        end

        // Abort in the middle of a carry column, then retry an extreme operand.
        @(negedge clk);operand=64'hffff_ffff_ffff_ffff;start=1;
        @(negedge clk);start=0;repeat(7)@(negedge clk);rst_n=0;
        @(negedge clk);if(busy || done || result!==0)$fatal(1,"SQUARE64 reset abort failed");
        rst_n=1;check_one(64'hffff_ffff_ffff_ffff);
        repeat(3)@(negedge clk);
        if(done || result!==ref_square(64'hffff_ffff_ffff_ffff))$fatal(1,"SQUARE64 output not held after done");
        if (errors == 0)
            $display("SQUARE64_TB_PASS: %0d checks, 0 errors", checks);
        else
            $fatal(1,"SQUARE64_TB_FAIL: %0d checks, %0d errors", checks, errors);

        $finish;
    end
endmodule
