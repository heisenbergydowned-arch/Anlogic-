`timescale 1ns/1ps
module tb_ds18b20_fault;
    reg clk=0; always #125 clk=~clk; // 4 MHz; protocol microseconds unchanged
    reg rst_n=0, short_after=0;
    reg [15:0] after_temp=16'h0190;
    tri dq_short,dq_zero,dq_after,dq_allzero;
    pullup(dq_short); pullup(dq_zero); pullup(dq_after); pullup(dq_allzero);
    assign dq_short=1'b0;
    assign dq_after=short_after ? 1'b0 : 1'bz;
    wire signed [15:0] t_short,t_zero,t_after;
    wire v_short,v_zero,v_after,p_short,p_zero,p_after,s_short,s_zero,s_after;
    wire f_short,f_zero,f_after;
    wire signed [15:0] t_allzero;
    wire v_allzero,p_allzero,s_allzero,f_allzero;
    ds18b20 #(.CLK_FREQ(4000000),.CONV_MS(2),.PERIOD_MS(15)) short_dut(
        .clk(clk),.rst_n(rst_n),.dq(dq_short),.temperature(t_short),.vld(v_short),
        .present(p_short),.stale(s_short),.bus_short(f_short));
    ds18b20 #(.CLK_FREQ(4000000),.CONV_MS(2),.PERIOD_MS(15)) zero_dut(
        .clk(clk),.rst_n(rst_n),.dq(dq_zero),.temperature(t_zero),.vld(v_zero),
        .present(p_zero),.stale(s_zero),.bus_short(f_zero));
    ds18b20 #(.CLK_FREQ(4000000),.CONV_MS(2),.PERIOD_MS(15)) after_dut(
        .clk(clk),.rst_n(rst_n),.dq(dq_after),.temperature(t_after),.vld(v_after),
        .present(p_after),.stale(s_after),.bus_short(f_after));
    ds18b20_model zero_model(.dq(dq_zero),.en(1'b1),.temp_code(16'h0000),.crc_bad(1'b0));
    ds18b20_model after_model(.dq(dq_after),.en(1'b1),.temp_code(after_temp),.crc_bad(1'b0));
    ds18b20 #(.CLK_FREQ(4000000),.CONV_MS(2),.PERIOD_MS(15)) allzero_dut(
        .clk(clk),.rst_n(rst_n),.dq(dq_allzero),.temperature(t_allzero),.vld(v_allzero),
        .present(p_allzero),.stale(s_allzero),.bus_short(f_allzero));
    ds18b20_model allzero_model(.dq(dq_allzero),.en(1'b1),.temp_code(16'h0190),
        .crc_bad(1'b0),.frame_zero(1'b1));
    always @(posedge clk) if(rst_n && v_allzero)
        $fatal(1,"All-zero scratchpad emitted valid temperature");
    integer n_short=0,n_zero=0,n_after=0,baseline;
    always @(posedge clk) if(rst_n) begin
        if(v_short)n_short=n_short+1;
        if(v_zero)n_zero=n_zero+1;
        if(v_after)n_after=n_after+1;
    end
    integer positions[0:4];
    integer i;
    task verify_slot_fault;
        integer saved_count;
        reg [15:0] saved_temp;
        real injected_at;
        begin
            saved_count=n_after;
            saved_temp=t_after;
            injected_at=$realtime;
            short_after=1;
            wait(f_after===1); @(negedge clk);
            if($realtime-injected_at>100000.0)
                $fatal(1,"Slot fault detection exceeded 100us");
            if(n_after!=saved_count || t_after!==saved_temp || p_after!==0 || s_after!==0)
                $fatal(1,"Slot fault accepted a partial frame");
            short_after=0;
            // Reset recovery alone must not clear a latched fault.
            wait(after_dut.st==after_dut.S_CMDBIT); @(negedge clk);
            if(f_after!==1)$fatal(1,"Fault cleared before a valid scratchpad");
            wait(n_after>saved_count); @(negedge clk);
            if(f_after!==0 || p_after!==1 || t_after!==after_temp)
                $fatal(1,"Slot fault recovery failed");
        end
    endtask
    initial begin
        repeat(10)@(negedge clk); rst_n=1;
        wait(n_after>=1); @(negedge clk);
        if(t_after!==16'h0190)$fatal(1,"Healthy 25C missing");
        baseline=n_after; short_after=1;
        #60000000;   // 4 个采样周期：连续 3 次故障判定 bus_short 必然完成
        // 短路语义（v0.8 实现）：bus_short=1、present=0、无新 vld、
        // 温度保持旧值；stale 与短路正交（stale 只管 CRC/85°C 无效帧）
        if(n_short!=0 || f_short!==1 || s_short!==0 || p_short!==0)
            $fatal(1,"Permanent low not blocked");
        if(n_zero<3 || t_zero!==16'h0000 || f_zero!==0 || s_zero!==0 || p_zero!==1)
            $fatal(1,"Legitimate 0C rejected");
        if(n_after!=baseline || t_after!==16'h0190 || f_after!==1 || s_after!==0 || p_after!==0)
            $fatal(1,"Post-good short corrupted temperature");
        if(f_allzero!==1 || s_allzero!==0 || t_allzero!==0)
            $fatal(1,"Consecutive all-zero frames did not latch a bus fault");
        $display("DS fault: permanent-low valid=0; post-good holds 25C; real 0C accepted");
        short_after=0;
        wait(n_after>baseline); @(negedge clk);
        if(t_after!==16'h0190 || f_after!==0 || s_after!==0 || p_after!==1)
            $fatal(1,"Recovery did not clear fault");
        // 0x0519 (81.5625C) becomes CRC-valid 0x0119 (17.5625C) if
        // a short after bit 9 is merely checked by CRC and nonzero detection.
        after_temp=16'h0519;
        positions[0]=9; positions[1]=0; positions[2]=15;
        positions[3]=63; positions[4]=71;
        for(i=0;i<5;i=i+1) begin
            wait(after_dut.st==after_dut.S_RDBIT && after_dut.rd_cnt==positions[i]);
            @(negedge clk); verify_slot_fault;
            $display("DS fault: read position %0d blocked; recovered 81.5625C", positions[i]);
        end
        // Exercise both command slot lengths, independently of read slots.
        wait(after_dut.st==after_dut.S_CMDBIT && after_dut.bop==after_dut.BOP_TX0);
        @(negedge clk); verify_slot_fault;
        wait(after_dut.st==after_dut.S_CMDBIT && after_dut.bop==after_dut.BOP_TX1);
        @(negedge clk); verify_slot_fault;
        $display("DS fault: TX0/TX1 release checks and fault latch verified");
        $display("tb_ds18b20_fault: ALL PASS"); $finish;
    end
    initial begin #450000000; $fatal(1,"DS fault test TIMEOUT"); end
endmodule
