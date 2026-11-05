`timescale 1ns/1ps
module tb_sdp810_bus;
    reg clk=0;
    always #5 clk=~clk;
    tri1 sda,scl,board_sda,board_scl,reserved_pad,core_dq;
    reg sensor_present=1,hold_scl_low=0;
    reg [2:0] corrupt=0;
    reg signed [15:0] pressure_raw=6000;
    wire pwm; tri reserved22;
    wire [31:0] protocol_errors;
    wire [31:0] stop_commands,start_commands,identity_reads,measurement_reads;
    assign scl=hold_scl_low ? 1'b0:1'bz;
    subsys_acq #(.POR_BITS(4),.ACQ_CLK_HZ(4000000),.ENABLE_SDP810(1),
        .CONTROL_BENCH_ENABLE(0),.DS_CONV_MS(1)) dut(
        .I_sysclk(clk),.I_spi_miso(1'b0),.I_adc_douta(1'b0),.I_adc_busy(1'b0),.I_adc_frstdata(1'b1),
        .IO_j12_19_reserved(reserved_pad),.IO_temp_core_dq(core_dq),.IO_i2c_sda_ext(sda),.IO_i2c_scl_ext(scl),
        .I_fan_fg(1'b1),.O_fan_pwm(pwm),.IO_j12_22_reserved(reserved22),.I_rs485_rx(1'b1),.I_key1(1'b1),.I_key2(1'b1),
        .I_pl_uart_rx(1'b1),.IO_iic_sda(board_sda),.IO_iic_scl(board_scl),.edge_clk(clk),.edge_rst_n(1'b0),
        .edge_awaddr(16'd0),.edge_awvalid(1'b0),.edge_wdata(32'd0),.edge_wstrb(4'd0),.edge_wvalid(1'b0),
        .edge_bready(1'b0),.edge_araddr(16'd0),.edge_arvalid(1'b0),.edge_rready(1'b0));
    sdp810_model #(.TIME_MS_NS(40000)) sensor(
        .sda(sda),.scl(scl),.present(sensor_present),.pressure_raw(pressure_raw),.temperature_raw(16'sd5000),
        .scale_factor(16'd60),.product_number(32'h03020a01),.crc_corrupt(corrupt),.protocol_errors(protocol_errors),
        .stop_commands(stop_commands),.start_commands(start_commands),.identity_reads(identity_reads),.measurement_reads(measurement_reads));
    aht20_model #(.MEAS_MS(0)) environment(
        .sda(sda),.scl(scl),.present(1'b1),.cal_powerup(1'b1),.hum_in(20'h80000),.temp_in(20'h66666),.crc_corrupt(1'b0));
    bmp280_model #(.MEAS_MS(0)) barometer(
        .sda(sda),.scl(scl),.present(1'b1),.cal_in({12{16'h1234}}),
        .t_raw_in(20'habcde),.p_raw_in(20'h12345));
    integer samples=0;
    always @(posedge clk)if(dut.sdp_sample_valid)samples<=samples+1;
    task wait_sample;
        input integer expected;
        integer waited;
        begin
            waited=0;
            while(samples<expected && waited<1200000)begin @(negedge clk);waited=waited+1;end
            if(samples<expected)$fatal(1,"physical bus timeout err=%0d state=%0d",dut.sdp_error_code,dut.g_sdp810.driver.st);
        end
    endtask
    task wait_error;
        integer waited;
        begin
            waited=0;
            while(!dut.sdp_err && waited<160000)begin @(negedge clk);waited=waited+1;end
            if(!dut.sdp_err)$fatal(1,"physical bus fault not reported");
            if(dut.u_control.pressure_valid)$fatal(1,"faulty pressure marked valid by control");
        end
    endtask
    integer saved_samples;
    initial begin
        wait_sample(3);
        if(dut.sdp_pressure_raw!=6000 || !dut.u_control.pressure_valid)$fatal(1,"digital pressure not routed to control");
        if(!dut.aht_present || !dut.bmp_present)$fatal(1,"shared-bus peers starved");
        if(start_commands!=1 || identity_reads!=1 || protocol_errors!=0)$fatal(1,"continuous/identity/settling protocol errors %0d",protocol_errors);
        force dut.adc_ch2=16'sh7fff;
        force dut.err_adc=1'b1;
        repeat(4)@(negedge clk);
        if(!dut.u_control.pressure_valid)$fatal(1,"unused ADC CH2/error invalidates digital pressure");
        release dut.adc_ch2;release dut.err_adc;

        sensor_present=0;wait_error;saved_samples=samples;
        repeat(10000)@(negedge clk);
        if(samples!=saved_samples || dut.sdp_pressure_raw!=6000)$fatal(1,"offline sensor republishes old value");
        pressure_raw=-6000;sensor_present=1;
        wait_sample(saved_samples+1);
        if(dut.sdp_pressure_raw!=-6000 || !dut.u_control.pressure_valid)$fatal(1,"signed pressure recovery failed");

        corrupt=3'b010;wait_error;saved_samples=samples;
        if(dut.sdp_error_code!=4)$fatal(1,"temperature-word CRC not checked");
        repeat(10000)@(negedge clk);
        if(samples!=saved_samples)$fatal(1,"CRC failure publishes a fresh sample");
        corrupt=0;pressure_raw=0;wait_sample(saved_samples+1);
        if(dut.sdp_pressure_raw!=0 || !dut.u_control.pressure_valid)$fatal(1,"real zero pressure not valid");

        wait(dut.req_gnt && dut.master_dev==7'h25 && scl===1'b0);
        hold_scl_low=1;wait_error;saved_samples=samples;
        repeat(20000)@(negedge clk);
        if(samples!=saved_samples)$fatal(1,"stuck SCL makes old pressure fresh");
        hold_scl_low=0;wait_sample(saved_samples+1);
        if(pwm || reserved22!==1'bz)$fatal(1,"unqualified bus fixture enabled actuators");
        if(protocol_errors!=0)$fatal(1,"wire-level protocol violation %0d",protocol_errors);
        $display("tb_sdp810_bus ALL PASS wire-level commands/CRC, 3-device sharing, ADC isolation, disconnect, stuck SCL and recovery");
        $finish;
    end
    initial begin #100000000;$fatal(1,"TIMEOUT SDP810 physical bus fixture");end
endmodule
