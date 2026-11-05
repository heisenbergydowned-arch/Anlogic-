`timescale 1ns/1ps
module tb_rs485_counterexamples_r35;
    parameter CLK_HZ=100000000, BAUD=115200, EXTRA_GAP=50000;
    localparam BIT_TICKS=CLK_HZ/BAUD;
    reg clk=0, rst_n=0, rx=1;
    wire tx,de,monitor_valid;
    wire [31:0] bad_frames,monitor_errors;
    wire [7:0] monitor_data;
    reg [7:0] request[0:7];
    integer received_bytes=0, request_index, contiguous_bytes, gapped_bytes;
    time request_end, response_begin;
    real response_delay_us;
    always #(500000000.0/CLK_HZ) clk=~clk;
    edge_rs485 #(.CLK_HZ(CLK_HZ),.BAUD(BAUD)) dut(
        .clk(clk),.rst_n(rst_n),.rx(rx),.holding(256'h1234abcd),
        .tx(tx),.de(de),.bad_frames(bad_frames));
    edge_uart_rx #(.CLK_HZ(CLK_HZ),.BAUD(BAUD),.PARITY(1)) monitor(
        .clk(clk),.rst_n(rst_n),.rx(tx),.valid(monitor_valid),
        .data(monitor_data),.errors(monitor_errors));
    always @(posedge clk) if(monitor_valid) received_bytes=received_bytes+1;
    always @(posedge de) response_begin=$time;
    task send_byte;
        input [7:0] value;
        integer bit_index;
        begin
            rx=0;repeat(BIT_TICKS)@(negedge clk);
            for(bit_index=0;bit_index<8;bit_index=bit_index+1)begin
                rx=value[bit_index];repeat(BIT_TICKS)@(negedge clk);
            end
            rx=^value;repeat(BIT_TICKS)@(negedge clk);
            rx=1;repeat(BIT_TICKS)@(negedge clk);
        end
    endtask
    task reset_case;
        begin
            rst_n=0;rx=1;repeat(10)@(negedge clk);
            rst_n=1;received_bytes=0;repeat(400*BIT_TICKS)@(negedge clk);
        end
    endtask
    initial begin
        request[0]=1;request[1]=3;request[2]=0;request[3]=0;
        request[4]=0;request[5]=2;request[6]=8'hc4;request[7]=8'h0b;
        reset_case;
        for(request_index=0;request_index<8;request_index=request_index+1)send_byte(request[request_index]);
        request_end=$time;
        repeat(400*BIT_TICKS)@(negedge clk);
        contiguous_bytes=received_bytes;
        response_delay_us=(response_begin-request_end)/1000.0;
        if(contiguous_bytes!=9 || bad_frames!=0 || monitor_errors!=0)$fatal(1,"Baseline request failed");
        $display("CONTIGUOUS baud=%0d bytes=%0d de_after_request_end_us=%0.3f",BAUD,contiguous_bytes,response_delay_us);
        reset_case;
        for(request_index=0;request_index<8;request_index=request_index+1)begin
            send_byte(request[request_index]);
            if(request_index==3)repeat(EXTRA_GAP)@(negedge clk);
        end
        repeat(400*BIT_TICKS)@(negedge clk);
        gapped_bytes=received_bytes;
        $display("GAPPED baud=%0d extra_idle_ticks=%0d bytes=%0d bad_frames=%0d",BAUD,EXTRA_GAP,gapped_bytes,bad_frames);
        if(BAUD==115200 && gapped_bytes!=9)$fatal(1,"500us legal high-baud gap rejected");
        if(BAUD==9600 && (gapped_bytes!=0 || bad_frames==0))$fatal(1,"Interrupted low-baud frame not rejected");
        $display("REGRESSION_FIXED_NOT_BOARD_ACCEPTANCE");
        $finish;
    end
    initial begin #1000000000;$fatal(1,"Review timeout");end
endmodule
