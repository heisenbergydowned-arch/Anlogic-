`timescale 1ns/1ps
// Optional AXI-Lite -> same-clock FCB1 CSR adapter. Independent AW/W capture;
// responses survive backpressure. MUST use an AXI clock converter if the PS
// master is in another clock domain. Not attached to design_0 in this release.
module cooling_axi_lite(
    input wire clk,rst_n,
    input wire [15:0] awaddr,input wire awvalid,output wire awready,
    input wire [31:0] wdata,input wire [3:0] wstrb,input wire wvalid,output wire wready,
    output reg [1:0] bresp,output reg bvalid,input wire bready,
    input wire [15:0] araddr,input wire arvalid,output wire arready,
    output reg [31:0] rdata,output reg [1:0] rresp,output reg rvalid,input wire rready,
    output reg req,write_en,output reg [15:0] address,output reg [31:0] write_data,
    input wire response,input wire [31:0] read_data,input wire [7:0] error
);
    reg aw_held,w_held,ar_held,pending,pending_write,last_write;
    reg [15:0] saved_aw,saved_ar;
    reg [31:0] saved_w;
    reg [3:0] saved_strobe;
    assign awready=!aw_held && !bvalid && !(pending && pending_write);
    assign wready=!w_held && !bvalid && !(pending && pending_write);
    assign arready=!ar_held && !rvalid && !(pending && !pending_write);
    wire choose_write=aw_held && w_held && !bvalid && (!(ar_held && !rvalid) || !last_write);
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            aw_held<=0;w_held<=0;ar_held<=0;pending<=0;pending_write<=0;last_write<=0;
            saved_aw<=0;saved_ar<=0;saved_w<=0;saved_strobe<=0;
            bresp<=0;bvalid<=0;rdata<=0;rresp<=0;rvalid<=0;req<=0;write_en<=0;address<=0;write_data<=0;
        end else begin
            req<=0;
            if(bvalid && bready)bvalid<=0;
            if(rvalid && rready)rvalid<=0;
            if(awvalid && awready)begin saved_aw<=awaddr;aw_held<=1;end
            if(wvalid && wready)begin saved_w<=wdata;saved_strobe<=wstrb;w_held<=1;end
            if(arvalid && arready)begin saved_ar<=araddr;ar_held<=1;end
            if(!pending)begin
                if(choose_write)begin
                    aw_held<=0;w_held<=0;last_write<=1;
                    if(saved_strobe!=4'hf)begin bvalid<=1;bresp<=2;end
                    else begin req<=1;write_en<=1;address<=saved_aw;write_data<=saved_w;pending<=1;pending_write<=1;end
                end else if(ar_held && !rvalid)begin
                    ar_held<=0;last_write<=0;req<=1;write_en<=0;address<=saved_ar;write_data<=0;pending<=1;pending_write<=0;
                end
            end else if(response)begin
                pending<=0;
                if(pending_write)begin bvalid<=1;bresp<=error==0 ? 0:2;end
                else begin rvalid<=1;rdata<=read_data;rresp<=error==0 ? 0:2;end
            end
        end
    end
endmodule
