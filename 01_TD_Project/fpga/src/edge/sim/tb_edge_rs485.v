`timescale 1ns/1ps
module tb_edge_rs485;
    reg clk=0;always #5 clk=~clk;reg rst_n=0,rx=1;wire tx,de;wire [31:0] bad;
    wire received;wire [7:0] byte_data;wire [31:0] rx_errors;
    edge_rs485 #(.CLK_HZ(1000000),.BAUD(100000)) dut(.clk(clk),.rst_n(rst_n),.rx(rx),.holding(256'h1234abcd),.tx(tx),.de(de),.bad_frames(bad));
    edge_uart_rx #(.CLK_HZ(1000000),.BAUD(100000),.PARITY(1)) monitor(.clk(clk),.rst_n(rst_n),.rx(tx),.valid(received),.data(byte_data),.errors(rx_errors));
    reg [7:0] bytes[0:39];integer n=0,b,j;reg [15:0] crc_value;
    always @(posedge clk)if(received)begin if(!de)$fatal(1,"DE dropped before last character");bytes[n]<=byte_data;n<=n+1;end
    task send_byte;input [7:0] value;begin
        @(negedge clk);rx=0;repeat(10)@(negedge clk);
        for(b=0;b<8;b=b+1)begin rx=value[b];repeat(10)@(negedge clk);end
        rx=^value;repeat(10)@(negedge clk);
        rx=1;repeat(10)@(negedge clk);
    end endtask
    function [15:0] crc;input [15:0] old;input [7:0] v;integer k;reg [15:0] c;
        begin c=old^{8'd0,v};for(k=0;k<8;k=k+1)c=c[0]?(c>>1)^16'ha001:c>>1;crc=c;end
    endfunction
    initial begin
        repeat(8)@(negedge clk);rst_n=1;repeat(2000)@(negedge clk);
        send_byte(1);send_byte(3);send_byte(0);send_byte(0);send_byte(0);send_byte(2);send_byte(8'hc4);send_byte(8'h0b);
        wait(de);wait(!de);repeat(2000)@(negedge clk);
        if(n!=9 || bytes[0]!=1 || bytes[1]!=3 || bytes[2]!=4 || bytes[3]!=8'hab || bytes[4]!=8'hcd || bytes[5]!=8'h12 || bytes[6]!=8'h34)$fatal(1,"Bad RTU response");
        crc_value=16'hffff;for(j=0;j<7;j=j+1)crc_value=crc(crc_value,bytes[j]);
        if({bytes[8],bytes[7]}!=crc_value || rx_errors!=0)$fatal(1,"RTU CRC/framing");
        send_byte(1);send_byte(3);send_byte(0);send_byte(0);send_byte(0);send_byte(2);send_byte(0);send_byte(0);
        repeat(2000)@(negedge clk);if(bad!=1 || de)$fatal(1,"Bad CRC accepted");
        // Unsupported write function must report 0x86, never generic 0x83.
        crc_value=16'hffff;crc_value=crc(crc_value,1);crc_value=crc(crc_value,6);
        crc_value=crc(crc_value,0);crc_value=crc(crc_value,0);crc_value=crc(crc_value,0);crc_value=crc(crc_value,2);
        send_byte(1);send_byte(6);send_byte(0);send_byte(0);send_byte(0);send_byte(2);
        send_byte(crc_value[7:0]);send_byte(crc_value[15:8]);
        wait(de);wait(!de);repeat(20)@(negedge clk);
        if(n!=14 || bytes[9]!=1 || bytes[10]!=8'h86 || bytes[11]!=1)$fatal(1,"Unsupported function exception");
        crc_value=16'hffff;for(j=9;j<12;j=j+1)crc_value=crc(crc_value,bytes[j]);
        if({bytes[13],bytes[12]}!=crc_value)$fatal(1,"Exception CRC");
        $display("tb_edge_rs485 ALL PASS real UART/DE/Modbus CRC and bad-frame rejection");$finish;
    end
    initial begin #1000000;$fatal(1,"TIMEOUT RTU");end
endmodule
