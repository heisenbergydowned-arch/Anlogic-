`timescale 1ns/1ps
module tb_single_temperature;
    reg clk=0;always #5 clk=~clk;
    tri reserved_pad;tri1 core_dq,sda,scl,board_sda,board_scl;
    reg external_low=0;assign reserved_pad=external_low ? 1'b0:1'bz;
    wire pwm; tri reserved22;
    reg drive22=0, value22=0;
    assign reserved22=drive22 ? value22:1'bz;
    subsys_acq #(.POR_BITS(5),.ACQ_CLK_HZ(100000000),.ENABLE_FEATURES(1),
        .LINK_TEST_MODE(0),.CONTROL_BENCH_ENABLE(0),.DS_CONV_MS(1),.GRACE_MS(0)) dut(
        .I_sysclk(clk),.I_spi_miso(1'b0),.I_adc_douta(1'b0),.I_adc_busy(1'b0),.I_adc_frstdata(1'b1),
        .IO_j12_19_reserved(reserved_pad),.IO_temp_core_dq(core_dq),.IO_i2c_sda_ext(sda),.IO_i2c_scl_ext(scl),
        .I_fan_fg(1'b1),.O_fan_pwm(pwm),.IO_j12_22_reserved(reserved22),.I_rs485_rx(1'b1),.I_key1(1'b1),.I_key2(1'b1),
        .I_pl_uart_rx(1'b1),.IO_iic_sda(board_sda),.IO_iic_scl(board_scl),
        .edge_clk(clk),.edge_rst_n(1'b0),.edge_awaddr(16'd0),.edge_awvalid(1'b0),.edge_wdata(32'd0),
        .edge_wstrb(4'd0),.edge_wvalid(1'b0),.edge_bready(1'b0),.edge_araddr(16'd0),.edge_arvalid(1'b0),.edge_rready(1'b0));
    initial begin
        repeat(100)@(negedge clk);
        force dut.aht_present=1;force dut.aht_err=0;force dut.aht_temp_code=393216;force dut.aht_hum_code=524288;
        force dut.bmp_present=1;force dut.bmp_err=0;force dut.bmp_t_raw=519888;force dut.bmp_p_raw=415148;
        force dut.bmp_cal_regs=192'h1770c6f83c8cfff9008c0b270bd0d6438e7dfc1867436b70;
        force dut.aht_sample_valid=1;force dut.bmp_sample_valid=1;
        force dut.temp_core_raw=16'sd1040;force dut.temp_core_present=1;force dut.temp_core_stale=0;force dut.temp_core_short=0;
        repeat(10)@(negedge clk);force dut.aht_sample_valid=0;force dut.bmp_sample_valid=0;
        repeat(500)@(negedge clk);
        if(reserved_pad!==1'bz)$fatal(1,"Reserved J12-19 pad is driven");
        if(dut.control_active[15] || dut.environment_auxiliary_bad)$fatal(1,"Unconnected J12-19 raised AUX_LOSS");
        if(dut.inlet_aht_raw!=400)$fatal(1,"AHT inlet Q12.4 conversion");
        if(dut.u_control.temp_raw!=1040 || dut.g_features.features.temp_raw!=1040)$fatal(1,"S4b core path changed");
        external_low=1;repeat(10)@(negedge clk);
        if(dut.control_active[15] || dut.environment_auxiliary_bad)$fatal(1,"Unused pad low affects auxiliary status");
        force dut.aht_temp_code=262144;repeat(3)@(negedge clk);
        if(dut.inlet_aht_raw!=0 || dut.u_control.temp_raw!=1040)$fatal(1,"AHT leaked into S4b");
        force dut.aht_err=1;repeat(3)@(negedge clk);
        if(!dut.control_active[15] || !dut.environment_auxiliary_bad)$fatal(1,"Actual AHT failure not degraded");
        force dut.aht_err=0;force dut.temp_core_present=0;force dut.temp_core_stale=1;force dut.temp_core_short=1;
        repeat(3)@(negedge clk);
        if(dut.control_active[15] || !dut.u_control.temp_short || !dut.g_features.features.temp_bad)$fatal(1,"Core DS fault masked by AHT");
        if(pwm!==0 || reserved22!==1'bz)$fatal(1,"Unqualified test activated outputs");
        force dut.control_inhibit=1'b0;
        repeat(3)@(negedge clk);
        if(reserved22!==1'bz)$fatal(1,"W8 driven with PWM uninhibited");
        force dut.control_inhibit=1'b1;
        repeat(3)@(negedge clk);
        if(reserved22!==1'bz)$fatal(1,"W8 driven during hard protection");
        drive22=1;value22=1;repeat(3)@(negedge clk);
        if(reserved22!==1'b1)$fatal(1,"W8 conflicts with external high");
        value22=0;repeat(3)@(negedge clk);
        if(reserved22!==1'b0)$fatal(1,"W8 conflicts with external low");
        drive22=0;release dut.control_inhibit;
        $display("tb_single_temperature ALL PASS real-path wiring; S4b independent; W8 high-Z with inhibit on/off and no external drive contention");$finish;
    end
    initial begin #1000000;$fatal(1,"TIMEOUT topology");end
endmodule
