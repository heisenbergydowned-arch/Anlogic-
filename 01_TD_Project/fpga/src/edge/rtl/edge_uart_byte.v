`timescale 1ns/1ps
module edge_uart_rx #(parameter CLK_HZ=100000000, BAUD=115200, PARITY=0, STOP_BITS=1)(
    input wire clk,rst_n,rx,
    output reg valid,output reg [7:0] data,output reg [31:0] errors,
    output wire busy,line_high,output reg frame_start,frame_error
);
    localparam TICKS=CLK_HZ/BAUD;
    (* ASYNC_REG="TRUE" *) reg rx_meta,rx_sync;
    reg [2:0] state;
    reg [31:0] timer;
    reg [2:0] bit_index;
    reg [7:0] shift;
    reg stop_index,frame_good;
    assign busy=state!=0;
    assign line_high=rx_sync;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            rx_meta<=1;rx_sync<=1;state<=0;timer<=0;bit_index<=0;shift<=0;
            valid<=0;data<=0;errors<=0;frame_start<=0;frame_error<=0;stop_index<=0;frame_good<=1;
        end else begin
            rx_meta<=rx;rx_sync<=rx_meta;valid<=0;frame_start<=0;frame_error<=0;
            case(state)
                0:if(!rx_sync)begin timer<=TICKS/2-1;state<=1;frame_start<=1;frame_good<=1;end
                1:if(timer!=0)timer<=timer-1;
                  else if(!rx_sync)begin timer<=TICKS-1;bit_index<=0;state<=2;end
                  else begin state<=0;frame_error<=1;errors<=errors+1;end
                2:if(timer!=0)timer<=timer-1;
                  else begin
                    shift[bit_index]<=rx_sync;timer<=TICKS-1;
                    if(bit_index==7)begin state<=PARITY==0 ? 4:3;stop_index<=0;end
                    else bit_index<=bit_index+1;
                  end
                3:if(timer!=0)timer<=timer-1;
                  else begin
                    if(rx_sync!=(PARITY==1 ? ^shift:~^shift))frame_good<=0;
                    state<=4;stop_index<=0;timer<=TICKS-1;
                  end
                4:if(timer!=0)timer<=timer-1;
                  else begin
                    if(!rx_sync)frame_good<=0;
                    if(STOP_BITS==2 && !stop_index)begin stop_index<=1;timer<=TICKS-1;end
                    else begin state<=5;timer<=TICKS-TICKS/2-1;end
                  end
                5:if(timer!=0)timer<=timer-1;
                  else begin
                    if(frame_good)begin valid<=1;data<=shift;end
                    else begin frame_error<=1;errors<=errors+1;end
                    state<=0;
                  end
                default:begin state<=0;frame_error<=1;errors<=errors+1;end
            endcase
        end
    end
endmodule

module edge_uart_tx #(parameter CLK_HZ=100000000, BAUD=115200, PARITY=0, STOP_BITS=1)(
    input wire clk,rst_n,start,input wire [7:0] data,output reg busy,output reg tx
);
    localparam TICKS=CLK_HZ/BAUD,FRAME_BITS=9+(PARITY!=0 ? 1:0)+STOP_BITS;
    localparam [3:0] LAST_INDEX=FRAME_BITS[3:0]-4'd1;
    reg [31:0] timer;
    reg [3:0] index;
    reg [11:0] shift;
    wire parity_bit=PARITY==1 ? ^data:~^data;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin timer<=0;index<=0;shift<=12'hfff;busy<=0;tx<=1;end
        else if(!busy)begin
            tx<=1;
            if(start)begin
                shift<=PARITY==0 ? {3'b111,data,1'b0}:{2'b11,parity_bit,data,1'b0};
                tx<=0;busy<=1;index<=0;timer<=TICKS-1;
            end
        end else if(timer!=0)timer<=timer-1;
        else if(index==LAST_INDEX)begin tx<=1;busy<=0;end
        else begin shift<={1'b1,shift[11:1]};tx<=shift[1];index<=index+1;timer<=TICKS-1;end
    end
endmodule
