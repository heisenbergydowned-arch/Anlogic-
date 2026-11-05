`timescale 1ns/1ps
// Same-clock register interface (one-cycle response). Shared by UART and the
// optional AXI-Lite adapter. See README.md for the frozen version-1 contract.
module cooling_regs #(parameter STARTUP_MS=2000)(
    input wire clk, rst_n,
    input wire req, write_en, input wire [15:0] address, input wire [31:0] write_data,
    output reg response, output reg [31:0] read_data, output reg [7:0] error,
    input wire local_permit, initial_config_permit, commit_allowed,
    input wire [1023:0] live_status,
    input wire [255:0] event_head,
    input wire [7:0] command_status,
    output wire command_fire, output wire [7:0] command,
    output reg [31:0] command_id, command_data,
    output reg [767:0] cfg, output reg cfg_changed,
    output reg [7:0] last_command_status, last_config_status,
    output reg [31:0] last_command_id
);
    reg [767:0] staging;
    reg [23:0] written;
    reg [1023:0] snapshot;
    reg command_seen;
    reg [31:0] last_payload;
    reg [7:0] last_opcode;
    wire execute=req && write_en && address==16'h0014;
    wire same_id=command_seen && command_id==last_command_id;
    wire identical=same_id && write_data[7:0]==last_opcode && command_data==last_payload;
    wire [31:0] seq_delta=command_id-last_command_id;
    wire new_id=!command_seen || (seq_delta!=0 && !seq_delta[31]);
    // Reserved bits are invalid even when the canonical command is a retry;
    // a cached success must not conceal a malformed execution word.
    wire [7:0] exec_error=write_data[31:8]!=0 ? 8'd1 : (identical ? last_command_status :
        (!new_id ? 8'd4 : command_status));
    assign command=write_data[7:0];
    assign command_fire=execute && !same_id && new_id && exec_error==0;

    // Each word is two uint16 fields unless documented otherwise. Defaults
    // retain the old 50% bench output; flags/id are ZERO, so AUTO is unqualified.
    function [31:0] default_word;
        input integer index;
        begin
            case(index)
                0:default_word=0; 1:default_word=0;
                2:default_word={16'd2000,16'd2000};
                3:default_word={16'd1000,16'd4000};
                4:default_word={16'd4000,16'd500};
                5:default_word={16'd6500,16'd500};
                6:default_word=0; 7:default_word=0; 8:default_word=0;
                9:default_word=0; 10:default_word=0;
                11:default_word={8'd0,8'd2,16'd0};
                12:default_word={16'd300,16'd100};
                13:default_word={16'd3500,16'd5};
                14:default_word={16'd1000,16'd400};
                15:default_word=32'h03e80000 | STARTUP_MS;
                16:default_word={16'd60000,16'd2000};
                17:default_word={16'd1000,16'd1000};
                18:default_word={16'd2000,16'd100};
                19:default_word={16'd1000,16'd2000};
                20:default_word={16'd1000,16'd30000};
                21:default_word=1000; 22:default_word=12000000;
                23:default_word=0;
                default:default_word=0;
            endcase
        end
    endfunction
    wire [15:0] dmin=staging[4*32 +:16],dmax=staging[4*32+16 +:16];
    wire [15:0] rmin=staging[5*32 +:16],rmax=staging[5*32+16 +:16];
    wire signed [15:0] tw=staging[9*32 +:16], th=staging[9*32+16 +:16], tr=staging[10*32 +:16];
    wire [15:0] ch=staging[7*32+16 +:16],hard=staging[8*32 +:16],cr=staging[8*32+16 +:16];
    wire [15:0] vl=staging[10*32+16 +:16],vh=staging[11*32 +:16];
    wire base_ok=staging[31:5]==0 && staging[32 +:32]!=0 && staging[32 +:32]!=cfg[32 +:32]
        && dmin>0 && dmin<=dmax && dmax<=4000 && rmin>0 && rmin<rmax
        && staging[2*32 +:16]>0 && staging[2*32 +:16]<=dmax
        && staging[2*32+16 +:16]>0 && staging[2*32+16 +:16]<=dmax
        && staging[3*32 +:16]>=dmin && staging[3*32 +:16]<=dmax
        && staging[3*32+16 +:16]>=dmin && staging[3*32+16 +:16]<=dmax
        && staging[6*32 +:16]<=32767 && staging[6*32+16 +:16]<=32767
        && staging[11*32+16 +:8]>=1 && staging[11*32+16 +:8]<=8 && staging[11*32+24 +:8]==0
        && staging[12*32 +:16]>0 && staging[12*32+16 +:16]>0
        && staging[13*32 +:16]>0 && staging[13*32+16 +:16]>0
        && staging[14*32 +:16]>0 && staging[14*32+16 +:16]>0
        && staging[15*32 +:16]>0 && staging[15*32+16 +:16]>0
        && staging[16*32 +:16]>0 && staging[16*32+16 +:16]>0
        && staging[17*32 +:16]>0 && staging[17*32+16 +:16]>0
        && staging[18*32 +:16]>0 && staging[18*32+16 +:16]>0
        && staging[19*32 +:16]>0 && staging[19*32+16 +:16]>0
        && staging[20*32 +:16]>0 && staging[20*32+16 +:16]>0
        && staging[21*32 +:32]>=128 && staging[21*32 +:32]<staging[22*32 +:32]
        && staging[23*32+16 +:16]==0;
    wire rules_ok=(!staging[0] || (cr<ch && ch<hard))
        && (!staging[1] || (tr>= -16'sd880 && tr<tw && tw<th && th<=16'sd2000))
        && (!staging[2] || (staging[23*32 +:16]>=rmax && staging[23*32 +:16]>0))
        && (!staging[3] || (staging[6*32 +:16]!=0))
        && (!staging[4] || (vl>0 && vl<vh && vh<32767));
    wire initial_authorized=initial_config_permit===1'b1;
    wire initial_full_qualification=local_permit || !initial_authorized || staging[31:0]==32'h0000001f;
    wire [7:0] config_error=write_data!=32'h434f_4d54 ? 8'd1 :
        ((!local_permit && !initial_authorized) || !commit_allowed ? 8'd3 :
        (written!=24'hffffff || !base_ok || !rules_ok || !initial_full_qualification ? 8'd2:8'd0));
    function [31:0] get24;
        input [767:0] value;input [4:0] word_index;
        begin case(word_index)
            5'd0:get24=value[0 +:32];
            5'd1:get24=value[32 +:32];
            5'd2:get24=value[64 +:32];
            5'd3:get24=value[96 +:32];
            5'd4:get24=value[128 +:32];
            5'd5:get24=value[160 +:32];
            5'd6:get24=value[192 +:32];
            5'd7:get24=value[224 +:32];
            5'd8:get24=value[256 +:32];
            5'd9:get24=value[288 +:32];
            5'd10:get24=value[320 +:32];
            5'd11:get24=value[352 +:32];
            5'd12:get24=value[384 +:32];
            5'd13:get24=value[416 +:32];
            5'd14:get24=value[448 +:32];
            5'd15:get24=value[480 +:32];
            5'd16:get24=value[512 +:32];
            5'd17:get24=value[544 +:32];
            5'd18:get24=value[576 +:32];
            5'd19:get24=value[608 +:32];
            5'd20:get24=value[640 +:32];
            5'd21:get24=value[672 +:32];
            5'd22:get24=value[704 +:32];
            5'd23:get24=value[736 +:32];
            default:get24=0;
        endcase end
    endfunction
    function [31:0] get32;
        input [1023:0] value;input [4:0] word_index;
        begin case(word_index)
            5'd0:get32=value[0 +:32];
            5'd1:get32=value[32 +:32];
            5'd2:get32=value[64 +:32];
            5'd3:get32=value[96 +:32];
            5'd4:get32=value[128 +:32];
            5'd5:get32=value[160 +:32];
            5'd6:get32=value[192 +:32];
            5'd7:get32=value[224 +:32];
            5'd8:get32=value[256 +:32];
            5'd9:get32=value[288 +:32];
            5'd10:get32=value[320 +:32];
            5'd11:get32=value[352 +:32];
            5'd12:get32=value[384 +:32];
            5'd13:get32=value[416 +:32];
            5'd14:get32=value[448 +:32];
            5'd15:get32=value[480 +:32];
            5'd16:get32=value[512 +:32];
            5'd17:get32=value[544 +:32];
            5'd18:get32=value[576 +:32];
            5'd19:get32=value[608 +:32];
            5'd20:get32=value[640 +:32];
            5'd21:get32=value[672 +:32];
            5'd22:get32=value[704 +:32];
            5'd23:get32=value[736 +:32];
            5'd24:get32=value[768 +:32];
            5'd25:get32=value[800 +:32];
            5'd26:get32=value[832 +:32];
            5'd27:get32=value[864 +:32];
            5'd28:get32=value[896 +:32];
            5'd29:get32=value[928 +:32];
            5'd30:get32=value[960 +:32];
            5'd31:get32=value[992 +:32];
            default:get32=0;
        endcase end
    endfunction
    function [31:0] get8;
        input [255:0] value;input [4:0] word_index;
        begin case(word_index)
            5'd0:get8=value[0 +:32];
            5'd1:get8=value[32 +:32];
            5'd2:get8=value[64 +:32];
            5'd3:get8=value[96 +:32];
            5'd4:get8=value[128 +:32];
            5'd5:get8=value[160 +:32];
            5'd6:get8=value[192 +:32];
            5'd7:get8=value[224 +:32];
            default:get8=0;
        endcase end
    endfunction
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for(i=0;i<24;i=i+1) begin cfg[i*32 +:32]<=default_word(i); staging[i*32 +:32]<=default_word(i); end
            written<=0;snapshot<=0;response<=0;read_data<=0;error<=0;cfg_changed<=0;
            command_id<=0;command_data<=0;command_seen<=0;last_command_id<=0;
            last_payload<=0;last_opcode<=0;last_command_status<=0;last_config_status<=0;
        end else begin
            response<=req;cfg_changed<=0;error<=0;
            if(req) begin
                read_data<=0;
                if(address[1:0]!=0) error<=1;
                else if(write_en) begin
                    case(address)
                        16'h000c:command_id<=write_data;
                        16'h0010:command_data<=write_data;
                        16'h0014:begin
                            error<=exec_error;read_data<={24'd0,exec_error};
                            if(new_id) begin
                                command_seen<=1;last_command_id<=command_id;last_payload<=command_data;
                                last_opcode<=write_data[7:0];last_command_status<=exec_error;
                            end
                            if(command_fire && command==7) snapshot<=live_status;
                        end
                        16'h0018:begin
                            error<=config_error;last_config_status<=config_error;
                            if(config_error==0) begin cfg<=staging;cfg_changed<=1;written<=0;end
                        end
                        default:begin
                            if(address>=16'h0300 && address<16'h0360) begin
                                for(i=0;i<24;i=i+1) begin
                                    if(address[6:2]==i) begin staging[i*32 +:32]<=write_data;written[i]<=1;end
                                end
                            end else error<=1;
                        end
                    endcase
                end else begin
                    case(address)
                        16'h0000:read_data<=32'h4643_4231; // FCB1
                        16'h0004:read_data<=32'h0001_0000;
                        16'h0008:read_data<={16'd0,last_config_status,last_command_status};
                        16'h000c:read_data<=command_id;
                        16'h0010:read_data<=command_data;
                        16'h0014:read_data<={24'd0,last_opcode};
                        16'h0018:read_data<={8'd0,written};
                        16'h001c:read_data<=live_status[31:0];
                        16'h0020:read_data<=last_command_id;
                        16'h0024:read_data<=cfg[32 +:32];
                        default:begin
                            if(address>=16'h0080 && address<16'h00a0) read_data<=get8(event_head,{2'd0,address[4:2]});
                            else if(address>=16'h0100 && address<16'h0180) read_data<=get32(live_status,address[6:2]);
                            else if(address>=16'h0300 && address<16'h0360) read_data<=get24(staging,address[6:2]);
                            else if(address>=16'h0500 && address<16'h0560) read_data<=get24(cfg,address[6:2]);
                            else if(address>=16'h0700 && address<16'h0780) read_data<=get32(snapshot,address[6:2]);
                            else error<=1;
                        end
                    endcase
                end
            end
        end
    end
endmodule
