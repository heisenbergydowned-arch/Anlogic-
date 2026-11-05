`timescale 1ns/1ps
module edge_rs485 #(
    parameter CLK_HZ=100000000,BAUD=115200,UNIT_ID=1,PARITY=1,STOP_BITS=(PARITY==0 ? 2:1)
)(
    input wire clk,rst_n,rx,input wire [255:0] holding,
    output wire tx,output reg de,output reg [31:0] bad_frames
);
    localparam TICKS=CLK_HZ/BAUD,CHAR_BITS=9+(PARITY!=0 ? 1:0)+STOP_BITS;
    localparam [63:0] T15_CALC=BAUD>19200 ? (CLK_HZ*64'd750+999999)/1000000:(64'd3*TICKS*CHAR_BITS+1)/2;
    localparam [63:0] T35_CALC=BAUD>19200 ? (CLK_HZ*64'd1750+999999)/1000000:(64'd7*TICKS*CHAR_BITS+1)/2;
    localparam [31:0] T15=T15_CALC[31:0],T35=T35_CALC[31:0];
    wire rx_valid,rx_busy,rx_start,rx_error,rx_high;
    wire [7:0] rx_data;
    wire [31:0] rx_errors;
    edge_uart_rx #(.CLK_HZ(CLK_HZ),.BAUD(BAUD),.PARITY(PARITY),.STOP_BITS(STOP_BITS)) receiver(
        .clk(clk),.rst_n(rst_n),.rx(rx),.valid(rx_valid),.data(rx_data),.errors(rx_errors),
        .busy(rx_busy),.line_high(rx_high),.frame_start(rx_start),.frame_error(rx_error));
    reg send;
    reg [7:0] tx_data;
    wire tx_busy;
    edge_uart_tx #(.CLK_HZ(CLK_HZ),.BAUD(BAUD),.PARITY(PARITY),.STOP_BITS(STOP_BITS)) transmitter(
        .clk(clk),.rst_n(rst_n),.start(send),.data(tx_data),.busy(tx_busy),.tx(tx));
    reg [7:0] request[0:7];
    reg [3:0] length;
    reg [31:0] idle,guard;
    reg ready,rejected;
    reg [15:0] request_crc,response_crc;
    reg [5:0] tx_index,tx_length;
    reg [2:0] state;
    reg exception;
    reg [7:0] exception_code,exception_function;
    reg [4:0] base,count;
    reg [255:0] snapshot;
    reg [7:0] next_byte;
    wire [15:0] requested_base={request[2],request[3]},requested_count={request[4],request[5]};
    function [15:0] crc;
        input [15:0] old;
        input [7:0] byte_data;
        integer bit_number;
        reg [15:0] value;
        begin
            value=old^{8'd0,byte_data};
            for(bit_number=0;bit_number<8;bit_number=bit_number+1)
                value=value[0] ? (value>>1)^16'ha001:value>>1;
            crc=value;
        end
    endfunction
    always @* begin
        next_byte=0;
        if(tx_index==0)next_byte=UNIT_ID;
        else if(tx_index==1)next_byte=exception ? exception_function:8'h03;
        else if(tx_index==tx_length-2)next_byte=response_crc[7:0];
        else if(tx_index==tx_length-1)next_byte=response_crc[15:8];
        else if(tx_index==2)next_byte=exception ? exception_code:{2'd0,count,1'b0};
        else if(tx_index[0])next_byte=snapshot[(base+((tx_index-3)>>1))*16+8+:8];
        else next_byte=snapshot[(base+((tx_index-3)>>1))*16+:8];
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            length<=0;idle<=0;guard<=0;ready<=0;rejected<=0;
            request_crc<=16'hffff;response_crc<=16'hffff;tx_index<=0;tx_length<=0;state<=0;
            exception<=0;exception_code<=0;exception_function<=0;base<=0;count<=0;
            snapshot<=0;send<=0;tx_data<=0;de<=0;bad_frames<=0;
        end else begin
            send<=0;
            if(de)begin idle<=0;ready<=0;end
            else if(rx_start)begin
                if(!ready || (length!=0 && idle>T15))rejected<=1;
                idle<=0;
            end else if(rx_busy || rx_valid || rx_error)idle<=0;
            else if(idle<T35)idle<=idle+1;
            if(!de && rx_error)rejected<=1;
            if(!de && rx_valid && ready)begin
                if(length<8)begin
                    request[length[2:0]]<=rx_data;length<=length+1;
                    if(length<6)request_crc<=crc(request_crc,rx_data);
                end else length<=9;
            end
            case(state)
                0:if(!de && idle==T35 && !rx_busy && !rx_start && !rx_valid && rx_high)begin
                    ready<=1;
                    if(length!=0 || rejected)begin
                        length<=0;request_crc<=16'hffff;rejected<=0;
                        if(rejected || length!=8 || request_crc!={request[7],request[6]})bad_frames<=bad_frames+1;
                        else if(request[0]==UNIT_ID)begin
                            snapshot<=holding;base<=requested_base[4:0];count<=requested_count[4:0];
                            exception<=request[1]!=3 || requested_count==0 || requested_count>16 || requested_base+{1'b0,requested_count}>16;
                            exception_code<=request[1]!=3 ? 1:2;
                            exception_function<=request[1]|8'h80;
                            tx_length<=(request[1]!=3 || requested_count==0 || requested_count>16 || requested_base+{1'b0,requested_count}>16) ? 6'd5:6'd5+{requested_count[4:0],1'b0};
                            tx_index<=0;response_crc<=16'hffff;guard<=TICKS;de<=1;state<=1;ready<=0;
                        end
                    end
                end
                1:if(guard!=0)guard<=guard-1;else state<=2;
                2:begin
                    tx_data<=next_byte;send<=1;
                    if(tx_index<tx_length-2)response_crc<=crc(response_crc,next_byte);
                    state<=3;
                end
                3:if(tx_busy)state<=4;
                4:if(!tx_busy)begin
                    if(tx_index==tx_length-1)begin guard<=TICKS;state<=5;end
                    else begin tx_index<=tx_index+1;state<=2;end
                end
                5:if(guard!=0)guard<=guard-1;else begin de<=0;idle<=0;ready<=0;state<=0;end
                default:begin state<=0;de<=0;ready<=0;rejected<=1;end
            endcase
        end
    end
endmodule
