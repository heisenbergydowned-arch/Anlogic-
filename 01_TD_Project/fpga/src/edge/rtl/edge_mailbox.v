`timescale 1ns/1ps
// Two immutable complete-frame slots. Full mailbox drops NEW feature frames;
// it never blocks acquisition/FFT/protection or overwrites the PS reader.
// A matching frame-id ACK releases only the head; repeated ACK is idempotent.
// SERIAL_HEADER_STABLE is only for a producer that holds all 32 header words
// immutable through indices 0..38. Generic producers retain snapshot capture.
module edge_mailbox #(parameter SERIAL_HEADER_STABLE=0,parameter PRESSURE_INDEPENDENT=0,parameter HAS_ENVIRONMENT=0)(
    input wire clk,rst_n,input wire engine_busy,input wire local_permit,input wire initial_config_permit,
    input wire in_valid,input wire in_abort,input wire [5:0] in_index,input wire [31:0] in_fp32,
    input wire [1023:0] in_header,
    input wire req,write_en,input wire [15:0] address,input wire [31:0] wdata,
    output reg response,output wire [31:0] rdata,output reg [7:0] error,
    output reg [543:0] config_words,output reg config_changed,
    output wire frame_available,output reg [31:0] dropped
);
    // Separate simple dual-port header/feature memories permit simultaneous
    // incoming feature+header writes and a PS read of the other frozen slot.
    // One combined memory would require three independent addresses/ports.
    // A slot is published only after index 38, never as a partial frame.
    (* ram_style="bram" *) reg [31:0] header_memory[0:63];
    (* ram_style="bram" *) reg [31:0] feature_memory[0:77];
    reg [991:0] header_shift;
    reg [31:0] id0,id1,header_read_data,feature_read_data,register_rdata;
    reg ram_response,header_response;
    reg head,tail,building,discard;reg [1:0] count;reg [5:0] expected;
    reg last_ack_valid;reg [31:0] last_ack;
    reg [31:0] boot_cookie;
    reg [543:0] staging;reg [16:0] written;
    wire initial_feature_permit=(initial_config_permit===1'b1)
        && config_words[32+:32]==0 && config_words[64+:32]==0;
    wire [31:0] head_id=head ? id1:id0;
    wire ack=req && write_en && address==16'h1010 && count!=0 && wdata==head_id;
    wire commit=!in_abort && in_valid && in_index==38 && building && !discard && expected==38;
    assign frame_available=count!=0;
    wire accept_feature=rst_n && !in_abort && in_valid &&
        ((in_index==0 && count<2) || (in_index!=0 && building && !discard && in_index==expected));
    wire memory_read=req && !write_en && address[1:0]==0 && count!=0 &&
        ((address>=16'h1100 && address<16'h1180) || (address>=16'h1200 && address<16'h129c));
    wire [5:0] header_read_address={head,address[6:2]};
    wire [6:0] feature_read_address=(head ? 7'd39:7'd0)+{1'd0,address[7:2]};
    wire [6:0] feature_address=(tail ? 7'd39:7'd0)+{1'd0,in_index};
    wire [5:0] header_address={tail,in_index[4:0]};
    assign rdata=ram_response ? (header_response ? header_read_data:feature_read_data):register_rdata;
    // One write plus one registered read per memory, with no RAM reset.
    always @(posedge clk)begin
        if(accept_feature)feature_memory[feature_address]<=in_fp32;
        feature_read_data<=feature_memory[feature_read_address];
    end
    always @(posedge clk)begin
        if(accept_feature && in_index<32)
            header_memory[header_address]<=SERIAL_HEADER_STABLE ? in_header[{in_index[4:0],5'b00000}+:32]:
                (in_index==0 ? in_header[31:0]:header_shift[31:0]);
        header_read_data<=header_memory[header_read_address];
    end
    integer i,stage_word;
    reg config_valid;
    always @* begin
        config_valid=staging[0+:32]!=0 && staging[0+:32]!=config_words[0+:32]
            && staging[64+:32]<=1 && (!staging[64] || staging[32+:32]!=0)
            && staging[160+:32]!=0 && staging[192+:32]!=0
            && staging[224+:32]>=1 && staging[224+:32]<=8;
        for(i=0;i<9;i=i+1) begin
            if(staging[(8+i)*32+:32]>513)config_valid=0;
            if(i==0 && staging[(8+i)*32+:32]!=1)config_valid=0;
            if(i==8 && staging[(8+i)*32+:32]!=513)config_valid=0;
        end
        for(i=0;i<8;i=i+1)if(staging[(8+i)*32+:32]>=staging[(9+i)*32+:32])config_valid=0;
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            head<=0;tail<=0;count<=0;building<=0;discard<=0;expected<=0;
            id0<=0;id1<=0;header_shift<=0;ram_response<=0;header_response<=0;dropped<=0;last_ack_valid<=0;last_ack<=0;boot_cookie<=0;
            response<=0;register_rdata<=0;error<=0;staging<=0;written<=0;config_changed<=0;
            config_words<=0;
            config_words[0+:32]<=1; // provisional feature config, never calibration
            config_words[96+:32]<=32'd1073741824;
            config_words[128+:32]<=PRESSURE_INDEPENDENT ? 0:32'd1073741824;
            config_words[160+:32]<=32'd885622;
            config_words[192+:32]<=PRESSURE_INDEPENDENT ? 32'd17896:32'd163840;config_words[224+:32]<=2;
            config_words[256+:32]<=1;config_words[288+:32]<=13;config_words[320+:32]<=39;
            config_words[352+:32]<=65;config_words[384+:32]<=103;config_words[416+:32]<=154;
            config_words[448+:32]<=205;config_words[480+:32]<=257;config_words[512+:32]<=513;
        end else begin
            response<=0;error<=0;config_changed<=0;ram_response<=memory_read;header_response<=address<16'h1200;
            // The producer aborts an overwritten window by resetting its engine.
            // Cancel only the unpublished tail; committed head/ACK ownership remains.
            if(in_abort)begin
                if(building && !discard)dropped<=dropped+1;
                building<=0;discard<=0;expected<=0;
            end else if(in_valid)begin
                if(in_index==0)begin
                    if(building && !discard)dropped<=dropped+1;
                    expected<=1;
                    if(count<2)begin
                        building<=1;discard<=0;
                        if(tail)id1<=in_header[96+:32];else id0<=in_header[96+:32];
                        if(!SERIAL_HEADER_STABLE)header_shift<=in_header[1023:32];
                    end else begin building<=0;discard<=1;dropped<=dropped+1;end
                end else if(building && !discard)begin
                    if(in_index!=expected)begin discard<=1;building<=0;dropped<=dropped+1;end
                    else begin
                        if(!SERIAL_HEADER_STABLE && in_index<32)header_shift<=header_shift>>32;
                        expected<=expected+1;
                    end
                end
                if(commit)begin tail<=!tail;building<=0;end
            end
            case({commit,ack})
                2'b10:count<=count+1;
                2'b01:count<=count-1;
                default:count<=count;
            endcase
            if(ack)begin head<=!head;last_ack<=wdata;last_ack_valid<=1;end
            if(req)begin
                response<=1;register_rdata<=0;
                if(address[1:0]!=0)error<=1;
                else if(write_en)begin
                    if(address==16'h1010)begin
                        if(!ack && !(last_ack_valid && wdata==last_ack))error<=4;
                    end else if(address==16'h1050)begin
                        if(wdata==0 || (boot_cookie!=0 && boot_cookie!=wdata))error<=4;
                        else boot_cookie<=wdata;
                    end else if(address>=16'h1300 && address<16'h1344)begin
                        for(stage_word=0;stage_word<17;stage_word=stage_word+1)if(address[6:2]==stage_word)begin
                            staging[stage_word*32+:32]<=wdata;written[stage_word]<=1;
                        end
                    end else if(address==16'h1040 && wdata==32'h45434d54)begin
                        if(!local_permit && !initial_feature_permit)error<=3;
                        else if(engine_busy || building)error<=5;
                        else if(!(&written) || !config_valid)error<=2;
                        else begin config_words<=staging;config_changed<=1;written<=0;end
                    end else error<=1;
                end else begin
                    case(address)
                        16'h1000:register_rdata<=32'h45444731;
                        16'h1004:register_rdata<=32'h00010000;
                        16'h1008:register_rdata<={27'd0,engine_busy,building,1'b0,count};
                        16'h100c:register_rdata<=dropped;
                        16'h1010:register_rdata<=count!=0 ? head_id:0;
                        16'h1020:register_rdata<=config_words[0+:32];
                        16'h1024:register_rdata<=config_words[32+:32];
                        16'h1040:register_rdata<={(HAS_ENVIRONMENT != 0),14'd0,written};
                        16'h1050:register_rdata<=boot_cookie;
                        default:begin
                            if(memory_read)register_rdata<=0; // synchronous RAM drives rdata this cycle
                            else if(address>=16'h1300 && address<16'h1344)register_rdata<=staging[((address-16'h1300)>>2)*32+:32];
                            else if(address>=16'h1380 && address<16'h13c4)register_rdata<=config_words[((address-16'h1380)>>2)*32+:32];
                            else error<=1;
                        end
                    endcase
                end
            end
        end
    end
endmodule
