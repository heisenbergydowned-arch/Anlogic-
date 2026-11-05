`timescale 1ns/1ps
// Real acquisition wrapper, compressed POR delay, real 115200 8N1 pins.
// Missing external sensors are intentional; this only accepts UART/wiring/PWM,
// not sensor sampling or calibrated physical protection.
module tb_subsys_control;
    reg clk=0;always #5 clk=~clk;
    reg rx=1;
    wire tx,pwm,buzzer;
    tri1 reserved_pad,core_dq,sda,scl,board_sda,board_scl;
    wire spi_sclk,spi_mosi,cs_a,cs_b,convst,adc_sclk,adc_cs;
    wire grn,red,rs_tx,rs_de,hb,alm,l1,l2;
    subsys_acq #(.POR_BITS(4)) dut(.I_sysclk(clk),.O_spi_sclk(spi_sclk),.O_spi_mosi(spi_mosi),.I_spi_miso(1'b0),
        .O_cs_icm_a(cs_a),.O_cs_icm_b(cs_b),.O_adc_convst(convst),.O_adc_sclk(adc_sclk),.O_adc_cs(adc_cs),
        .I_adc_douta(1'b0),.I_adc_busy(1'b0),.I_adc_frstdata(1'b0),
        .IO_j12_19_reserved(reserved_pad),.IO_temp_core_dq(core_dq),.IO_i2c_sda_ext(sda),.IO_i2c_scl_ext(scl),
        .I_fan_fg(1'b1),.O_fan_pwm(pwm),.O_buzzer_en(buzzer),.O_led_grn(grn),.O_led_red(red),
        .O_rs485_tx(rs_tx),.I_rs485_rx(1'b1),.O_rs485_de(rs_de),.O_led3_hb(hb),.O_led4_alm(alm),
        .I_key1(1'b1),.I_key2(1'b1),.O_pl_uart_tx(tx),.I_pl_uart_rx(rx),.IO_iic_sda(board_sda),.IO_iic_scl(board_scl),.O_led1(l1),.O_led2(l2));
    function [15:0] crc;
        input [15:0] old;input [7:0] b;reg [15:0] c;integer k;
        begin c=old^{b,8'd0};for(k=0;k<8;k=k+1)c=c[15] ? (c<<1)^16'h1021:c<<1;crc=c;end
    endfunction
    task send_byte;input [7:0] b;integer k;begin
        @(negedge clk);rx=0;repeat(868)@(negedge clk);
        for(k=0;k<8;k=k+1)begin rx=b[k];repeat(868)@(negedge clk);end
        rx=1;repeat(868)@(negedge clk);
    end endtask
    task read_byte;output [7:0] b;integer k;begin
        @(negedge tx);#13020;for(k=0;k<8;k=k+1)begin b[k]=tx;#8680;end
        if(tx!==1)$fatal(1,"Bad stop bit at actual subsystem TX");
    end endtask
    reg [111:0] packet;reg [127:0] reply;reg [15:0] c;integer i;
    integer rising=0;reg last_pwm=0;
    always @(posedge clk)begin last_pwm<=pwm;if(pwm && !last_pwm)rising<=rising+1;end
    initial begin
        wait(dut.sys_rst_n);repeat(20)@(posedge clk);
        packet={16'd0,32'd0,16'd0,16'h1234,8'd0,8'd1,8'h51,8'hc3};c=16'hffff;
        for(i=0;i<12;i=i+1)c=crc(c,packet[i*8 +:8]);packet[111:96]=c;
        fork
            begin for(integer a=0;a<14;a=a+1)send_byte(packet[a*8 +:8]);end
            begin for(integer b=0;b<16;b=b+1)read_byte(reply[b*8 +:8]);end
        join
        if(reply[15:0]!=16'h52c3 || reply[31:16]!=16'h0001 || reply[47:32]!=16'h1234 || reply[95:64]!=32'h46434231)$fatal(1,"FCB1 register path not live in acquisition top");
        c=16'hffff;for(i=0;i<14;i=i+1)c=crc(c,reply[i*8 +:8]);if(reply[127:112]!=c)$fatal(1,"Integrated response CRC");
        if(dut.fan_duty!=2000 || rising<20 || buzzer!==0 || dut.control_config[3:0]!=0)$fatal(1,"Bench PWM/qualification wiring");
        $display("ALL PASS tb_subsys_control actual_115200_UART_compressed_POR pwm_edges=%0d",rising);$finish;
    end
    initial begin #30000000;$fatal(1,"TIMEOUT tb_subsys_control");end
endmodule
