`timescale 1ns/1ps
// AXI and UART share ONE command/config staging owner. The PS service must be
// the only writer; UART is a maintenance alternative, not concurrent control.
module edge_csr_mux(
    input wire clk,rst_n,
    input wire a_req,a_write,input wire [15:0] a_address,input wire [31:0] a_wdata,
    output reg a_response,output reg [31:0] a_rdata,output reg [7:0] a_error,
    input wire b_req,b_write,input wire [15:0] b_address,input wire [31:0] b_wdata,
    output reg b_response,output reg [31:0] b_rdata,output reg [7:0] b_error,
    output reg req,write_en,output reg [15:0] address,output reg [31:0] wdata,
    input wire response,input wire [31:0] rdata,input wire [7:0] error
);
    reg busy,owner,last_owner,a_pending,b_pending;
    reg [48:0] ap,bp;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            busy<=0;owner<=0;last_owner<=1;a_pending<=0;b_pending<=0;ap<=0;bp<=0;
            req<=0;write_en<=0;address<=0;wdata<=0;
            a_response<=0;b_response<=0;a_rdata<=0;b_rdata<=0;a_error<=0;b_error<=0;
        end else begin
            req<=0;a_response<=0;b_response<=0;
            if(a_req) begin ap<={a_write,a_address,a_wdata};a_pending<=1;end
            if(b_req) begin bp<={b_write,b_address,b_wdata};b_pending<=1;end
            if(!busy) begin
                if(a_pending && (!b_pending || last_owner)) begin
                    {write_en,address,wdata}<=ap;a_pending<=0;req<=1;owner<=0;busy<=1;
                end else if(b_pending) begin
                    {write_en,address,wdata}<=bp;b_pending<=0;req<=1;owner<=1;busy<=1;
                end
            end else if(response) begin
                busy<=0;last_owner<=owner;
                if(owner) begin b_response<=1;b_rdata<=rdata;b_error<=error;end
                else begin a_response<=1;a_rdata<=rdata;a_error<=error;end
            end
        end
    end
endmodule
