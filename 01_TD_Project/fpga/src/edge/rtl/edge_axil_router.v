`timescale 1ns/1ps
// Intercept the unused 0x80400000..0x8040ffff page after the existing GP0
// AXI4->AXI-Lite converter. All other transactions retain their old route.
// One read and one write outstanding; AW and W may arrive in either order.
module edge_axil_router(
    input wire clk,rst_n,
    input wire [31:0] s_awaddr,input wire [2:0] s_awprot,input wire s_awvalid,output wire s_awready,
    input wire [31:0] s_wdata,input wire [3:0] s_wstrb,input wire s_wvalid,output wire s_wready,
    output reg [1:0] s_bresp,output reg s_bvalid,input wire s_bready,
    input wire [31:0] s_araddr,input wire [2:0] s_arprot,input wire s_arvalid,output wire s_arready,
    output reg [31:0] s_rdata,output reg [1:0] s_rresp,output reg s_rvalid,input wire s_rready,
    output wire [31:0] p_awaddr,output wire [2:0] p_awprot,output wire p_awvalid,input wire p_awready,
    output wire [31:0] p_wdata,output wire [3:0] p_wstrb,output wire p_wvalid,input wire p_wready,
    input wire [1:0] p_bresp,input wire p_bvalid,output wire p_bready,
    output wire [31:0] p_araddr,output wire [2:0] p_arprot,output wire p_arvalid,input wire p_arready,
    input wire [31:0] p_rdata,input wire [1:0] p_rresp,input wire p_rvalid,output wire p_rready,
    output wire [15:0] e_awaddr,output wire e_awvalid,input wire e_awready,
    output wire [31:0] e_wdata,output wire [3:0] e_wstrb,output wire e_wvalid,input wire e_wready,
    input wire [1:0] e_bresp,input wire e_bvalid,output wire e_bready,
    output wire [15:0] e_araddr,output wire e_arvalid,input wire e_arready,
    input wire [31:0] e_rdata,input wire [1:0] e_rresp,input wire e_rvalid,output wire e_rready
);
    reg aw_hold,w_hold,write_active,write_edge,aw_sent,w_sent;
    reg read_active,read_edge,ar_sent;
    reg [31:0] wa,wd,ra;reg [3:0] ws;reg [2:0] wp,rp;
    assign s_awready=!aw_hold && !write_active && !s_bvalid;
    assign s_wready=!w_hold && !write_active && !s_bvalid;
    assign s_arready=!read_active && !s_rvalid;
    assign p_awaddr=wa;assign p_awprot=wp;assign p_wdata=wd;assign p_wstrb=ws;
    assign p_awvalid=write_active && !write_edge && !aw_sent;
    assign p_wvalid=write_active && !write_edge && !w_sent;
    assign p_bready=write_active && !write_edge && aw_sent && w_sent && !s_bvalid;
    assign e_awaddr=wa[15:0];assign e_wdata=wd;assign e_wstrb=ws;
    assign e_awvalid=write_active && write_edge && !aw_sent;
    assign e_wvalid=write_active && write_edge && !w_sent;
    assign e_bready=write_active && write_edge && aw_sent && w_sent && !s_bvalid;
    assign p_araddr=ra;assign p_arprot=rp;
    assign p_arvalid=read_active && !read_edge && !ar_sent;
    assign p_rready=read_active && !read_edge && ar_sent && !s_rvalid;
    assign e_araddr=ra[15:0];assign e_arvalid=read_active && read_edge && !ar_sent;
    assign e_rready=read_active && read_edge && ar_sent && !s_rvalid;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            aw_hold<=0;w_hold<=0;write_active<=0;write_edge<=0;aw_sent<=0;w_sent<=0;
            read_active<=0;read_edge<=0;ar_sent<=0;wa<=0;wd<=0;ra<=0;ws<=0;wp<=0;rp<=0;
            s_bresp<=0;s_bvalid<=0;s_rdata<=0;s_rresp<=0;s_rvalid<=0;
        end else begin
            if(s_bvalid && s_bready)s_bvalid<=0;
            if(s_rvalid && s_rready)s_rvalid<=0;
            if(s_awvalid && s_awready)begin wa<=s_awaddr;wp<=s_awprot;aw_hold<=1;end
            if(s_wvalid && s_wready)begin wd<=s_wdata;ws<=s_wstrb;w_hold<=1;end
            if(aw_hold && w_hold && !write_active && !s_bvalid)begin
                write_active<=1;write_edge<=wa[31:16]==16'h8040;aw_sent<=0;w_sent<=0;
                aw_hold<=0;w_hold<=0;
            end
            if((p_awvalid && p_awready)||(e_awvalid && e_awready))aw_sent<=1;
            if((p_wvalid && p_wready)||(e_wvalid && e_wready))w_sent<=1;
            if((p_bvalid && p_bready)||(e_bvalid && e_bready))begin
                s_bvalid<=1;s_bresp<=write_edge ? e_bresp:p_bresp;write_active<=0;
            end
            if(s_arvalid && s_arready)begin
                ra<=s_araddr;rp<=s_arprot;read_edge<=s_araddr[31:16]==16'h8040;
                read_active<=1;ar_sent<=0;
            end
            if((p_arvalid && p_arready)||(e_arvalid && e_arready))ar_sent<=1;
            if((p_rvalid && p_rready)||(e_rvalid && e_rready))begin
                s_rvalid<=1;s_rdata<=read_edge ? e_rdata:p_rdata;
                s_rresp<=read_edge ? e_rresp:p_rresp;read_active<=0;
            end
        end
    end
endmodule
