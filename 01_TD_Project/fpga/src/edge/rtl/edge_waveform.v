`timescale 1ns/1ps
// Single immutable event, two independently timestamped XYZ streams.
// All ports, including CSR/release, belong to clk (the acquisition domain).
// See ../WAVEFORM.md for ownership, timing, layout and quality semantics.
module edge_waveform #(
    parameter CLK_HZ=100000000,
    parameter SAMPLE_HZ=4000,
    parameter PRE_SAMPLES=128,
    parameter POST_SAMPLES=128,
    parameter TEST_MODE=0,
    parameter [63:0] POST_TIMEOUT_CYCLES=CLK_HZ/2,
    parameter [15:0] CSR_BASE=16'h2000
)(
    input wire clk,rst_n,
    input wire [63:0] now_cycles,
    input wire [31:0] now_ms,
    input wire enable,stop,
    input wire a_new,b_new,
    input wire signed [15:0] ax,ay,az,bx,by,bz,
    input wire [15:0] a_seq,b_seq,
    input wire a_bad,b_bad,
    input wire trigger,
    input wire [31:0] trigger_reason,trigger_frame_id,
    input wire [63:0] trigger_frame_start,trigger_frame_end,
    input wire release_req,
    input wire [31:0] release_id,
    output reg release_ack,
    output wire armed,capturing,event_available,
    output reg [31:0] event_id,dropped_triggers,
    input wire req,write_en,
    input wire [15:0] address,
    input wire [31:0] wdata,
    output reg response,
    output reg [31:0] rdata,
    output reg [7:0] error
);
    localparam DEPTH=PRE_SAMPLES+POST_SAMPLES;
    localparam PW=(DEPTH<=1) ? 1:$clog2(DEPTH);
    localparam CW=(DEPTH<=1) ? 1:$clog2(DEPTH+1);
    localparam [63:0] PERIOD=CLK_HZ/SAMPLE_HZ;
    localparam [2:0] HALTED=0,ARMED=1,CAPTURE=2,SCAN_READ=3,SCAN_USE=4,READY=5;
    localparam [31:0] Q_SHORT_PRE_A=32'h00000100,Q_SHORT_PRE_B=32'h00000200;
    localparam [31:0] Q_SHORT_POST_A=32'h00000400,Q_SHORT_POST_B=32'h00000800;
    localparam [31:0] Q_STOP=32'h00001000,Q_TIMEOUT=32'h00002000;
    localparam [31:0] Q_BAD_A=32'h00004000,Q_BAD_B=32'h00008000;
    reg [2:0] state;
    (* ram_style="bram" *) reg [143:0] ram_a[0:DEPTH-1],ram_b[0:DEPTH-1];
    reg [143:0] read_a,read_b;
    reg [PW-1:0] wa,wb,base_a,base_b,scan_addr_a,scan_addr_b;
    reg [CW-1:0] history_a,history_b,pre_a,pre_b,post_a,post_b,scan_index;
    wire [CW-1:0] count_a=pre_a+post_a,count_b=pre_b+post_b;
    reg seen_a,seen_b,bad_pending_a,bad_pending_b;
    reg [15:0] last_seq_a,last_seq_b;
    reg [63:0] last_time_a,last_time_b;
    reg [31:0] next_id,reason,frame_id,trigger_ms,quality,bad_count_a,bad_count_b,trigger_source;
    reg [31:0] gaps_a,gaps_b;
    reg [63:0] trigger_time,frame_start,frame_end,first_a,first_b,end_a,end_b;
    reg [15:0] first_seq_a,first_seq_b,end_seq_a,end_seq_b;

    assign armed=state==ARMED;
    assign capturing=state==CAPTURE || state==SCAN_READ || state==SCAN_USE;
    assign event_available=state==READY;
    reg software_stop;
    wire [15:0] offset=address-CSR_BASE;
    reg csr_pending,csr_sensor;
    reg [2:0] csr_word;
    reg [31:0] read_index;
    wire csr_access=req && !csr_pending && address>=CSR_BASE && offset<16'h1000 && address[1:0]==0;
    wire csr_arm=csr_access && write_en && offset==16'h00b0 && wdata==1 && (state==HALTED || armed);
    wire csr_stop=csr_access && write_en && offset==16'h00b4 && wdata==1;
    wire csr_release=csr_access && write_en && offset==16'h00b8;
    wire csr_manual=csr_access && write_en && offset==16'h00bc && wdata==1;
    wire halt_request=stop || csr_stop || (software_stop && !csr_arm);
    wire accept_trigger=(trigger || csr_manual) && armed && enable && !halt_request;
    wire release_match=event_available && ((release_req && release_id==event_id) || (csr_release && wdata==event_id));
    wire write_a=rst_n && enable && !halt_request && a_new && !a_bad &&
        ((armed && (!accept_trigger || POST_SAMPLES!=0)) || (state==CAPTURE && post_a<POST_SAMPLES));
    wire write_b=rst_n && enable && !halt_request && b_new && !b_bad &&
        ((armed && (!accept_trigger || POST_SAMPLES!=0)) || (state==CAPTURE && post_b<POST_SAMPLES));
    wire [15:0] expected_a=last_seq_a+16'd1,expected_b=last_seq_b+16'd1;
    wire seq_gap_a=seen_a && a_seq!=expected_a,seq_gap_b=seen_b && b_seq!=expected_b;
    wire time_gap_a=seen_a && ((now_cycles-last_time_a)<PERIOD/4 || (now_cycles-last_time_a)>PERIOD*7/4);
    wire time_gap_b=seen_b && ((now_cycles-last_time_b)<PERIOD/4 || (now_cycles-last_time_b)>PERIOD*7/4);
    wire rail_a=ax==16'sh7fff || ax==16'sh8000 || ay==16'sh7fff || ay==16'sh8000 || az==16'sh7fff || az==16'sh8000;
    wire rail_b=bx==16'sh7fff || bx==16'sh8000 || by==16'sh7fff || by==16'sh8000 || bz==16'sh7fff || bz==16'sh8000;
    wire [15:0] sample_quality_a={12'd0,bad_pending_a,rail_a,time_gap_a,seq_gap_a};
    wire [15:0] sample_quality_b={12'd0,bad_pending_b,rail_b,time_gap_b,seq_gap_b};

    function [PW-1:0] advance;
        input [PW-1:0] ptr;
        begin advance=(ptr==DEPTH-1) ? 0:ptr+1'b1;end
    endfunction
    function [PW-1:0] oldest;
        input [PW-1:0] ptr;input [CW-1:0] n;
        begin oldest=(ptr>=n) ? ptr-n:DEPTH+ptr-n;end
    endfunction
    function [PW-1:0] indexed;
        input [PW-1:0] base;input [9:0] n;
        reg [PW:0] sum;
        begin sum={1'b0,base}+n;indexed=(sum>=DEPTH) ? sum-DEPTH:sum;end
    endfunction

    // INDEX[31]=A/B, [12:3]=sample, [2:0]=word. DATA is strictly read-only.
    wire [9:0] record_index=read_index[12:3];
    wire [2:0] record_word=read_index[2:0];
    wire csr_ram_read=csr_access && !write_en && offset==16'h00c4 &&
        event_available && !release_match && record_word<5 &&
        (read_index[31] ? record_index<count_b:record_index<count_a);
    wire scan_read=state==SCAN_READ;
    wire [PW-1:0] read_address_a=scan_read ? scan_addr_a:indexed(base_a,record_index);
    wire [PW-1:0] read_address_b=scan_read ? scan_addr_b:indexed(base_b,record_index);
    // One unconditional synchronous read per stream, with address arbitration
    // before the RAM. Two conditional indexed reads can infer two RAM ports.
    // Contents and outputs are never reset; state/quality gates all visibility.
    always @(posedge clk)begin
        if(write_a)ram_a[wa]<={sample_quality_a,a_seq,now_cycles,az,ay,ax};
        read_a<=ram_a[read_address_a];
    end
    always @(posedge clk)begin
        if(write_b)ram_b[wb]<={sample_quality_b,b_seq,now_cycles,bz,by,bx};
        read_b<=ram_b[read_address_b];
    end
    wire [143:0] csr_record=csr_sensor ? read_b:read_a;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin response<=0;rdata<=0;error<=0;csr_pending<=0;csr_sensor<=0;csr_word<=0;read_index<=0;end
        else begin
            response<=0;error<=0;
            if(csr_pending)begin
                csr_pending<=0;response<=1;rdata<=0;
                case(csr_word)
                    0:rdata<=csr_record[31:0];
                    1:rdata<={csr_record[127:112],csr_record[47:32]};
                    2:rdata<=csr_record[79:48];
                    3:rdata<=csr_record[111:80];
                    4:rdata<={16'd0,csr_record[143:128]};
                endcase
            end else if(req)begin
                rdata<=0;
                if(csr_ram_read)begin csr_pending<=1;csr_sensor<=read_index[31];csr_word<=record_word;end
                else begin
                    response<=1;
                    if(!csr_access)error<=1;
                    else if(write_en)begin
                        case(offset)
                            16'h00b0:if(wdata!=1)error<=2;else if(!csr_arm || !enable || stop)error<=5;
                            16'h00b4:if(wdata!=1)error<=2;
                            16'h00b8:if(!event_available || wdata!=event_id)error<=4;
                            16'h00bc:if(wdata!=1)error<=2;else if(!accept_trigger)error<=5;
                            16'h00c0:if((wdata & 32'h7fffe000)!=0)error<=2;else read_index<=wdata;
                            default:error<=1;
                        endcase
                    end else if(release_match)error<=5;
                    else if(offset==16'h00c4)error<=event_available ? 1:5;
                    else case(offset)
                        16'h0000:rdata<=32'h57415631; // WAV1
                        16'h0004:rdata<=32'h00010000;
                        16'h0008:rdata<={26'd0,(TEST_MODE!=0),software_stop,state==HALTED,event_available,capturing,armed};
                        16'h000c:rdata<=event_id;
                        16'h0010:rdata<=dropped_triggers;
                        16'h0014:rdata<=SAMPLE_HZ;
                        16'h0018:rdata<=PRE_SAMPLES;
                        16'h001c:rdata<=POST_SAMPLES;
                        16'h0020:rdata<=quality;
                        16'h0024:rdata<=reason;
                        16'h0028:rdata<=frame_id;
                        16'h002c:rdata<=trigger_ms;
                        16'h0030:rdata<=trigger_time[31:0];
                        16'h0034:rdata<=trigger_time[63:32];
                        16'h0038:rdata<=frame_start[31:0];
                        16'h003c:rdata<=frame_start[63:32];
                        16'h0040:rdata<=frame_end[31:0];
                        16'h0044:rdata<=frame_end[63:32];
                        16'h0048:rdata<=count_a;
                        16'h004c:rdata<=count_b;
                        16'h0050:rdata<=pre_a;
                        16'h0054:rdata<=pre_b;
                        16'h0058:rdata<=post_a;
                        16'h005c:rdata<=post_b;
                        16'h0060:rdata<=first_a[31:0];
                        16'h0064:rdata<=first_a[63:32];
                        16'h0068:rdata<=end_a[31:0];
                        16'h006c:rdata<=end_a[63:32];
                        16'h0070:rdata<=first_b[31:0];
                        16'h0074:rdata<=first_b[63:32];
                        16'h0078:rdata<=end_b[31:0];
                        16'h007c:rdata<=end_b[63:32];
                        16'h0080:rdata<={end_seq_a,first_seq_a};
                        16'h0084:rdata<={end_seq_b,first_seq_b};
                        16'h0088:rdata<=bad_count_a;
                        16'h008c:rdata<=bad_count_b;
                        16'h0090:rdata<=gaps_a;
                        16'h0094:rdata<=gaps_b;
                        16'h0098:rdata<=CLK_HZ;
                        16'h009c:rdata<=POST_TIMEOUT_CYCLES[31:0];
                        16'h00a0:rdata<=POST_TIMEOUT_CYCLES[63:32];
                        16'h00a4:rdata<=trigger_source;
                        16'h00a8:rdata<=TEST_MODE!=0 ? 32'd1:32'd0;
                        16'h00c0:rdata<=read_index;
                        default:error<=1;
                    endcase
                end
            end
        end
    end

    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=HALTED;wa<=0;wb<=0;base_a<=0;base_b<=0;scan_addr_a<=0;scan_addr_b<=0;scan_index<=0;
            history_a<=0;history_b<=0;pre_a<=0;pre_b<=0;post_a<=0;post_b<=0;
            seen_a<=0;seen_b<=0;bad_pending_a<=0;bad_pending_b<=0;
            last_seq_a<=0;last_seq_b<=0;last_time_a<=0;last_time_b<=0;
            next_id<=0;event_id<=0;dropped_triggers<=0;release_ack<=0;
            reason<=0;frame_id<=0;trigger_ms<=0;quality<=0;bad_count_a<=0;bad_count_b<=0;gaps_a<=0;gaps_b<=0;
            software_stop<=0;trigger_source<=0;
            trigger_time<=0;frame_start<=0;frame_end<=0;first_a<=0;first_b<=0;end_a<=0;end_b<=0;
            first_seq_a<=0;first_seq_b<=0;end_seq_a<=0;end_seq_b<=0;
        end else begin
            release_ack<=0;
            if((trigger || csr_manual) && !accept_trigger)dropped_triggers<=dropped_triggers+1;
            if(csr_stop)software_stop<=1;
            else if(csr_arm && enable && !stop)software_stop<=0;
            if(armed || state==CAPTURE)begin
                if(a_bad)bad_pending_a<=1;
                if(b_bad)bad_pending_b<=1;
            end
            if(write_a)begin
                wa<=advance(wa);seen_a<=1;last_seq_a<=a_seq;last_time_a<=now_cycles;bad_pending_a<=0;
            end
            if(write_b)begin
                wb<=advance(wb);seen_b<=1;last_seq_b<=b_seq;last_time_b<=now_cycles;bad_pending_b<=0;
            end
            case(state)
                HALTED:if(enable && !halt_request)state<=ARMED;
                ARMED:begin
                    if(write_a && history_a<PRE_SAMPLES)history_a<=history_a+1'b1;
                    if(write_b && history_b<PRE_SAMPLES)history_b<=history_b+1'b1;
                    if(!enable || halt_request)begin
                        state<=HALTED;history_a<=0;history_b<=0;seen_a<=0;seen_b<=0;bad_pending_a<=0;bad_pending_b<=0;
                    end else if(accept_trigger)begin
                        next_id<=next_id+1;event_id<=next_id+1;
                        reason<=csr_manual && !trigger ? 32'h80000000:trigger_reason;
                        trigger_source<={30'd0,csr_manual,trigger};
                        frame_id<=trigger_frame_id;frame_start<=trigger_frame_start;frame_end<=trigger_frame_end;
                        trigger_ms<=now_ms;trigger_time<=now_cycles;
                        pre_a<=history_a;pre_b<=history_b;post_a<=write_a ? 1:0;post_b<=write_b ? 1:0;
                        base_a<=oldest(wa,history_a);base_b<=oldest(wb,history_b);
                        scan_addr_a<=oldest(wa,history_a);scan_addr_b<=oldest(wb,history_b);scan_index<=0;
                        quality<=(history_a<PRE_SAMPLES ? Q_SHORT_PRE_A:0) | (history_b<PRE_SAMPLES ? Q_SHORT_PRE_B:0)
                            | (a_bad || bad_pending_a ? Q_BAD_A:0) | (b_bad || bad_pending_b ? Q_BAD_B:0);
                        bad_count_a<=a_new && a_bad ? 1:0;bad_count_b<=b_new && b_bad ? 1:0;
                        gaps_a<=0;gaps_b<=0;first_a<=0;first_b<=0;end_a<=0;end_b<=0;
                        first_seq_a<=0;first_seq_b<=0;end_seq_a<=0;end_seq_b<=0;
                        if(POST_SAMPLES==0 || (POST_SAMPLES==1 && write_a && write_b))state<=SCAN_READ;
                        else state<=CAPTURE;
                    end
                end
                CAPTURE:begin
                    if(write_a)post_a<=post_a+1'b1;
                    if(write_b)post_b<=post_b+1'b1;
                    if(a_new && a_bad && post_a<POST_SAMPLES)bad_count_a<=bad_count_a+1;
                    if(b_new && b_bad && post_b<POST_SAMPLES)bad_count_b<=bad_count_b+1;
                    quality<=quality | (a_bad && post_a<POST_SAMPLES ? Q_BAD_A:0) | (b_bad && post_b<POST_SAMPLES ? Q_BAD_B:0);
                    if(!enable || halt_request || now_cycles-trigger_time>=POST_TIMEOUT_CYCLES ||
                        ((post_a>=POST_SAMPLES || (write_a && post_a==POST_SAMPLES-1)) &&
                         (post_b>=POST_SAMPLES || (write_b && post_b==POST_SAMPLES-1))))begin
                        state<=SCAN_READ;
                        quality<=quality | (a_bad && post_a<POST_SAMPLES ? Q_BAD_A:0) | (b_bad && post_b<POST_SAMPLES ? Q_BAD_B:0)
                            | ((post_a+(write_a ? 1:0))<POST_SAMPLES ? Q_SHORT_POST_A:0)
                            | ((post_b+(write_b ? 1:0))<POST_SAMPLES ? Q_SHORT_POST_B:0)
                            | (!enable || halt_request ? Q_STOP:0)
                            | (now_cycles-trigger_time>=POST_TIMEOUT_CYCLES ? Q_TIMEOUT:0);
                    end
                end
                SCAN_READ:begin
                    if(scan_index>=count_a && scan_index>=count_b)state<=READY;
                    else state<=SCAN_USE;
                end
                SCAN_USE:begin
                    // Aggregate only retained samples, never stale ring contents.
                    quality<=quality | (scan_index<count_a ? {28'd0,read_a[131:128]}:0)
                        | (scan_index<count_b ? {24'd0,read_b[131:128],4'd0}:0);
                    if(scan_index<count_a)begin
                        scan_addr_a<=advance(scan_addr_a);end_a<=read_a[111:48];end_seq_a<=read_a[127:112];
                        if(scan_index==0)begin first_a<=read_a[111:48];first_seq_a<=read_a[127:112];end
                        if(|read_a[129:128])gaps_a<=gaps_a+1;
                    end
                    if(scan_index<count_b)begin
                        scan_addr_b<=advance(scan_addr_b);end_b<=read_b[111:48];end_seq_b<=read_b[127:112];
                        if(scan_index==0)begin first_b<=read_b[111:48];first_seq_b<=read_b[127:112];end
                        if(|read_b[129:128])gaps_b<=gaps_b+1;
                    end
                    scan_index<=scan_index+1'b1;state<=SCAN_READ;
                end
                READY:if(release_match)begin
                    release_ack<=1;state<=enable && !halt_request ? ARMED:HALTED;
                    history_a<=0;history_b<=0;pre_a<=0;pre_b<=0;post_a<=0;post_b<=0;
                    seen_a<=0;seen_b<=0;bad_pending_a<=0;bad_pending_b<=0;
                end
                default:state<=HALTED;
            endcase
        end
    end
    // synthesis translate_off
    initial begin
        if(PRE_SAMPLES<0 || POST_SAMPLES<0 || DEPTH<1 || DEPTH>1024 ||
            CLK_HZ<1 || SAMPLE_HZ<1 || CLK_HZ/SAMPLE_HZ<4 || POST_TIMEOUT_CYCLES==0 ||
            CSR_BASE>16'hf000 || CSR_BASE[11:0]!=0)
            $fatal(1,"edge_waveform invalid parameters");
    end
    // synthesis translate_on
endmodule
