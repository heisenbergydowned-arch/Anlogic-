`timescale 1ns/1ps
module tb_rs485_r35;
    parameter CLK_HZ=100000000,BAUD=115200,PARITY=1,STOP_BITS=(PARITY==0 ? 2:1);
    localparam TICKS=CLK_HZ/BAUD,CHAR_BITS=9+(PARITY!=0 ? 1:0)+STOP_BITS;
    localparam [63:0] T15_CALC=BAUD>19200 ? (CLK_HZ*64'd750+999999)/1000000:(64'd3*TICKS*CHAR_BITS+1)/2;
    localparam [63:0] T35_CALC=BAUD>19200 ? (CLK_HZ*64'd1750+999999)/1000000:(64'd7*TICKS*CHAR_BITS+1)/2;
    localparam [31:0] T15=T15_CALC[31:0],T35=T35_CALC[31:0];
    reg clk=0,rst_n=0,master_rx=1,echo=0;
    wire tx,de;
    wire bus_rx=echo && de ? tx:master_rx;
    wire [31:0] bad_frames;
    reg [255:0] holding;
    reg [7:0] response[0:63],request[0:8];
    reg [7:0] sampled;
    reg [15:0] checksum;
    integer response_count=0,monitor_bit,monitor_stop,request_index,register_index,case_count=0;
    integer saved_bad,random_index,random_base,random_count,random_gap;
    reg [31:0] random_state=32'h51435035;
    time last_request_end=0;
    always #(500000000.0/CLK_HZ) clk=~clk;
    edge_rs485 #(.CLK_HZ(CLK_HZ),.BAUD(BAUD),.PARITY(PARITY),.STOP_BITS(STOP_BITS)) dut(
        .clk(clk),.rst_n(rst_n),.rx(bus_rx),.holding(holding),.tx(tx),.de(de),.bad_frames(bad_frames));
    function [15:0] crc;
        input [15:0] previous;
        input [7:0] value;
        integer bit_number;
        reg [15:0] temporary;
        begin
            temporary=previous^{8'd0,value};
            for(bit_number=0;bit_number<8;bit_number=bit_number+1)
                temporary=temporary[0] ? (temporary>>1)^16'ha001:temporary>>1;
            crc=temporary;
        end
    endfunction
    always @(posedge de)begin
        if(last_request_end!=0 && $time-last_request_end < T35*1000000000.0/CLK_HZ)
            $fatal(1,"DE before t3.5 silence");
    end
    initial forever begin
        @(negedge tx);
        repeat(TICKS+TICKS/2)@(negedge clk);
        sampled=0;
        for(monitor_bit=0;monitor_bit<8;monitor_bit=monitor_bit+1)begin
            sampled[monitor_bit]=tx;
            if(monitor_bit!=7)repeat(TICKS)@(negedge clk);
        end
        if(PARITY!=0)begin
            repeat(TICKS)@(negedge clk);
            if(tx!=(PARITY==1 ? ^sampled:~^sampled))$fatal(1,"Response parity");
        end
        for(monitor_stop=0;monitor_stop<STOP_BITS;monitor_stop=monitor_stop+1)begin
            repeat(TICKS)@(negedge clk);
            if(!tx)$fatal(1,"Response stop bit");
        end
        if(response_count>=64)$fatal(1,"Response overflow");
        response[response_count]=sampled;response_count=response_count+1;
    end
    task send_byte;
        input [7:0] value;
        input bad_parity,bad_stop;
        integer bit_number,stop_number;
        begin
            @(negedge clk);master_rx=0;repeat(TICKS)@(negedge clk);
            for(bit_number=0;bit_number<8;bit_number=bit_number+1)begin
                master_rx=value[bit_number];repeat(TICKS)@(negedge clk);
            end
            if(PARITY!=0)begin
                master_rx=(PARITY==1 ? ^value:~^value)^bad_parity;
                repeat(TICKS)@(negedge clk);
            end
            for(stop_number=0;stop_number<STOP_BITS;stop_number=stop_number+1)begin
                master_rx=!bad_stop;repeat(TICKS)@(negedge clk);
            end
            master_rx=1;
        end
    endtask
    task prepare_case;
        begin
            repeat(T35+3*CHAR_BITS*TICKS)@(negedge clk);
            if(de)$fatal(1,"Stuck DE");
            response_count=0;saved_bad=bad_frames;last_request_end=0;case_count=case_count+1;
        end
    endtask
    task request_read;
        input [7:0] address,function_code;
        input [15:0] base,count;
        input integer gap,bad_crc,bad_format,extra;
        begin
            request[0]=address;request[1]=function_code;request[2]=base[15:8];request[3]=base[7:0];
            request[4]=count[15:8];request[5]=count[7:0];checksum=16'hffff;
            for(request_index=0;request_index<6;request_index=request_index+1)checksum=crc(checksum,request[request_index]);
            request[6]=checksum[7:0]^(bad_crc!=0 ? 8'd1:8'd0);request[7]=checksum[15:8];request[8]=8'h55;
            for(request_index=0;request_index<8+extra;request_index=request_index+1)begin
                send_byte(request[request_index],bad_format!=0 && PARITY!=0 && request_index==2,
                    bad_format!=0 && PARITY==0 && request_index==2);
                if(request_index==3)repeat(gap)@(negedge clk);
            end
            last_request_end=$time;
            repeat(T35+45*CHAR_BITS*TICKS)@(negedge clk);
        end
    endtask
    task expect_read;
        input integer base,count;
        integer byte_number;
        reg [15:0] expected_crc;
        begin
            if(response_count!=5+count*2 || response[0]!=1 || response[1]!=3 || {24'd0,response[2]}!=count*2)
                $fatal(1,"Read framing case=%0d got=%0d",case_count,response_count);
            for(byte_number=0;byte_number<count;byte_number=byte_number+1)
                if({16'd0,response[3+2*byte_number],response[4+2*byte_number]}!=32'ha000+base+byte_number)
                    $fatal(1,"Read payload case=%0d",case_count);
            expected_crc=16'hffff;
            for(byte_number=0;byte_number<response_count-2;byte_number=byte_number+1)expected_crc=crc(expected_crc,response[byte_number]);
            if({response[response_count-1],response[response_count-2]}!=expected_crc)$fatal(1,"Read CRC");
            if(bad_frames!=saved_bad)$fatal(1,"Valid request rejected case=%0d",case_count);
        end
    endtask
    task expect_silent;
        input integer count_error;
        begin
            if(response_count!=0 || de)$fatal(1,"Invalid or foreign frame answered case=%0d",case_count);
            if(count_error!=0 && bad_frames<=saved_bad)$fatal(1,"Missing rejection count case=%0d",case_count);
        end
    endtask
    task expect_exception;
        input [7:0] function_code,error_code;
        reg [15:0] expected_crc;
        integer byte_number;
        begin
            if(response_count!=5 || response[0]!=1 || response[1]!=(function_code|8'h80) || response[2]!=error_code)
                $fatal(1,"Exception framing case=%0d",case_count);
            expected_crc=16'hffff;
            for(byte_number=0;byte_number<3;byte_number=byte_number+1)expected_crc=crc(expected_crc,response[byte_number]);
            if({response[4],response[3]}!=expected_crc)$fatal(1,"Exception CRC");
        end
    endtask
    initial begin
        holding=0;
        for(register_index=0;register_index<16;register_index=register_index+1)holding[register_index*16+:16]=16'ha000+register_index[15:0];
        repeat(10)@(negedge clk);rst_n=1;
        prepare_case;request_read(1,3,0,2,0,0,0,0);expect_read(0,2);
        prepare_case;request_read(1,3,0,2,T15/2,0,0,0);expect_read(0,2);
        prepare_case;request_read(1,3,0,2,T15+3*TICKS,0,0,0);expect_silent(1);
        prepare_case;request_read(1,3,0,2,T35+3*TICKS,0,0,0);expect_silent(1);
        prepare_case;request_read(1,3,0,2,0,1,0,0);expect_silent(1);
        prepare_case;request_read(2,3,0,2,0,0,0,0);expect_silent(0);
        prepare_case;request_read(0,3,0,2,0,0,0,0);expect_silent(0);
        prepare_case;request_read(1,6,0,2,0,0,0,0);expect_exception(6,1);
        prepare_case;request_read(1,3,16,1,0,0,0,0);expect_exception(3,2);
        prepare_case;request_read(1,3,0,0,0,0,0,0);expect_exception(3,2);
        prepare_case;request_read(1,3,15,2,0,0,0,0);expect_exception(3,2);
        prepare_case;request_read(1,3,0,16,0,0,0,0);expect_read(0,16);
        prepare_case;request_read(1,3,0,2,0,0,0,1);expect_silent(1);
        prepare_case;request_read(1,3,0,2,0,0,1,0);expect_silent(1);
        prepare_case;echo=1;request_read(1,3,2,3,0,0,0,0);expect_read(2,3);echo=0;
        for(random_index=0;random_index<32;random_index=random_index+1)begin
            random_state=random_state*32'd1664525+32'd1013904223;
            random_base={28'd0,random_state[3:0]};random_count=1+{28'd0,random_state[7:4]}%(16-random_base);
            random_gap={24'd0,random_state[15:8]}%(T15/2+1);
            prepare_case;request_read(1,3,random_base[15:0],random_count[15:0],random_gap,0,0,0);expect_read(random_base,random_count);
        end
        $display("tb_rs485_r35 ALL PASS cases=%0d CLK_HZ=%0d BAUD=%0d PARITY=%0d STOP_BITS=%0d",case_count,CLK_HZ,BAUD,PARITY,STOP_BITS);
        $finish;
    end
    initial begin #10000000000;$fatal(1,"RTU regression timeout");end
endmodule
