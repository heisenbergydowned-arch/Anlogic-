`timescale 1ns/1ps
module sdp810_model #(parameter TIME_MS_NS=1000000)(
    inout wire sda,scl,
    input wire present,
    input wire signed [15:0] pressure_raw,temperature_raw,
    input wire [15:0] scale_factor,
    input wire [31:0] product_number,
    input wire [2:0] crc_corrupt,
    output reg [31:0] protocol_errors,
    output reg [31:0] stop_commands,start_commands,identity_reads,measurement_reads
);
    initial begin protocol_errors=0;stop_commands=0;start_commands=0;identity_reads=0;measurement_reads=0;end
    reg drive_low=0,started=0,previous_sda=1,address_seen=0,selected=0,read_direction=0,reading=0;
    reg [3:0] bit_index=0;
    reg [7:0] receive_shift=0,transmit_shift=0,command_high=0;
    reg [1:0] write_count=0;
    reg [4:0] read_index=0;
    reg master_ack=0,matched;
    reg continuous=0,identifier_prepared=0,identifier_ready=0,identity_transaction=0;
    reg [7:0] response_bytes[0:17];
    reg [7:0] next_byte;
    reg [15:0] command_word=0;
    time last_stop=0,last_identifier=0,last_start=0;
    assign sda=drive_low ? 1'b0:1'bz;

    function [7:0] crc_word;
        input [15:0] word_data;
        reg [7:0] crc_value;
        integer bit_number;
        begin
            crc_value=8'hff;
            for(bit_number=15;bit_number>=0;bit_number=bit_number-1)begin
                if(crc_value[7]^word_data[bit_number])crc_value=(crc_value<<1)^8'h31;
                else crc_value=crc_value<<1;
            end
            crc_word=crc_value;
        end
    endfunction
    task store_word;
        input integer word_index;
        input [15:0] word_data;
        input corrupt;
        begin
            response_bytes[word_index*3]=word_data[15:8];
            response_bytes[word_index*3+1]=word_data[7:0];
            response_bytes[word_index*3+2]=crc_word(word_data)^(corrupt ? 8'h01:8'h00);
        end
    endtask

    always @(sda)begin
        if(scl===1'b1)begin
            if(sda===1'b0 && previous_sda===1'b1)begin
                started<=1;bit_index<=0;address_seen<=0;selected<=0;reading<=0;write_count<=0;
            end
            if(sda===1'b1 && previous_sda===1'b0)begin
                if(selected && !read_direction && write_count==2)begin
                    case(command_word)
                        16'h3ff9:begin continuous=0;identifier_ready=0;identifier_prepared=0;last_stop=$time;stop_commands=stop_commands+1;end
                        16'h367c:begin
                            if(continuous || $time-last_stop<TIME_MS_NS)protocol_errors=protocol_errors+1;
                            identifier_prepared=1;
                        end
                        16'he102:begin
                            if(!identifier_prepared || continuous)protocol_errors=protocol_errors+1;
                            identifier_ready=1;last_identifier=$time;
                        end
                        16'h361e:begin
                            if(continuous)protocol_errors=protocol_errors+1;
                            continuous=1;last_start=$time;start_commands=start_commands+1;
                        end
                        default:protocol_errors=protocol_errors+1;
                    endcase
                end
                if(identity_transaction)identifier_ready=0;
                started<=0;reading<=0;drive_low<=0;identity_transaction<=0;
            end
        end
        previous_sda<=sda;
    end
    always @(posedge scl)begin
        if(started)begin
            if(bit_index<8)receive_shift<={receive_shift[6:0],sda};
            if(bit_index==8)master_ack<=sda===1'b0;
            bit_index<=bit_index==8 ? 0:bit_index+1;
        end
    end
    always @(negedge scl)begin
        if(started)begin
            if(bit_index==8)begin
                if(reading)drive_low<=0;
                else begin
                    matched=receive_shift[7:1]==7'h25 && present;
                    if(!address_seen)begin
                        address_seen<=1;selected<=matched;read_direction<=receive_shift[0];
                        identity_transaction<=0;
                        if(matched && receive_shift[0])begin
                            if(identifier_ready)begin
                                if($time-last_identifier<TIME_MS_NS)protocol_errors=protocol_errors+1;
                                store_word(0,product_number[31:16],0);store_word(1,product_number[15:0],0);
                                store_word(2,16'h1122,0);store_word(3,16'h3344,0);
                                store_word(4,16'h5566,0);store_word(5,16'h7788,0);
                                identity_reads=identity_reads+1;identity_transaction<=1;
                            end else if(continuous)begin
                                if($time-last_start<20*TIME_MS_NS)protocol_errors=protocol_errors+1;
                                store_word(0,pressure_raw,crc_corrupt[0]);store_word(1,temperature_raw,crc_corrupt[1]);
                                store_word(2,scale_factor,crc_corrupt[2]);measurement_reads=measurement_reads+1;
                            end else begin selected<=0;matched=0;end
                        end
                    end else if(selected && !read_direction)begin
                        if(write_count==0)command_high<=receive_shift;
                        if(write_count==1)command_word<={command_high,receive_shift};
                        if(write_count<3)write_count<=write_count+1;
                    end
                    drive_low<=address_seen ? selected:matched;
                end
            end else if(bit_index==0 && address_seen)begin
                if(reading)begin
                    if(master_ack)begin
                        next_byte=response_bytes[read_index+1];transmit_shift<=next_byte;
                        drive_low<=!next_byte[7];read_index<=read_index+1;
                    end else begin drive_low<=0;reading<=0;end
                end else if(selected && read_direction)begin
                    next_byte=response_bytes[0];transmit_shift<=next_byte;
                    drive_low<=!next_byte[7];read_index<=0;reading<=1;
                end else drive_low<=0;
            end else if(reading)begin
                drive_low<=!transmit_shift[6];transmit_shift<={transmit_shift[6:0],1'b0};
            end
        end
    end
endmodule
