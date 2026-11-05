`timescale 1ns/1ps
// Radix-2 DIT FFT, real integer input. One reusable core, FFT output scaled by 1/1024.
// In-place dual-port memory; five cycles per butterfly. Reset aborts current frame.
module fft1024_iter (
    input wire clk, input wire rst_n, input wire start,
    input wire in_valid, output wire in_ready, input wire signed [31:0] in_data,
    output reg out_valid, input wire out_ready, output reg [9:0] out_bin,
    output reg signed [31:0] out_re, out_im,
    output wire busy, output reg done
);
    localparam IDLE=0, LOAD=1, READ=2, MUL=3, SUM=4, WRITE=5, FETCH=6, SEND=7,
        CAPTURE=8,FETCH_CAPTURE=9;
    reg [3:0] state;
    reg [9:0] load_count, base, offset;
    reg [3:0] stage;
    reg [10:0] half_size;
    reg signed [31:0] ur,ui,vr,vi,tr,ti;
    reg signed [47:0] rr,ii,ri,ir;
    wire [9:0] addr_u=base+offset;
    wire [9:0] addr_v=base+offset+half_size;
    wire [8:0] tw_addr=offset << (9-stage);
    wire signed [15:0] wr,wi;
    feature_twiddle_rom rom(.clk(clk),.addr(tw_addr),.re(wr),.im(wi));
    wire signed [48:0] prod_re=$signed({rr[47],rr})-$signed({ii[47],ii});
    wire signed [48:0] prod_im=$signed({ri[47],ri})+$signed({ir[47],ir});
    wire signed [32:0] plus_re=$signed({ur[31],ur})+$signed({tr[31],tr});
    wire signed [32:0] plus_im=$signed({ui[31],ui})+$signed({ti[31],ti});
    wire signed [32:0] minus_re=$signed({ur[31],ur})-$signed({tr[31],tr});
    wire signed [32:0] minus_im=$signed({ui[31],ui})-$signed({ti[31],ti});
    wire [9:0] reversed={load_count[0],load_count[1],load_count[2],load_count[3],
        load_count[4],load_count[5],load_count[6],load_count[7],load_count[8],load_count[9]};
    wire [9:0] ram_a_addr=state==LOAD ? reversed :
        ((state==FETCH || state==FETCH_CAPTURE || state==SEND) ? out_bin : addr_u);
    wire [63:0] ram_a_q,ram_b_q;
    wire [63:0] ram_a_data=state==LOAD ? {in_data,32'd0} : {round_half(plus_re),round_half(plus_im)};
    wire [63:0] ram_b_data={round_half(minus_re),round_half(minus_im)};
    feature_fft_ram buffer(.clk(clk),.a_addr(ram_a_addr),.b_addr(addr_v),
        .a_we((state==LOAD && in_valid) || state==WRITE),.b_we(state==WRITE),
        .a_wdata(ram_a_data),.b_wdata(ram_b_data),.a_rdata(ram_a_q),.b_rdata(ram_b_q));
    function signed [31:0] round_twiddle;
        input signed [48:0] x;
        reg signed [48:0] rounded;
        begin
            rounded=(x>>>15)+((x[14:0]>15'd16384 || (x[14:0]==15'd16384 && x[15])) ? 49'sd1 : 49'sd0);
            round_twiddle=rounded[31:0];
        end
    endfunction
    function signed [31:0] round_half;
        input signed [32:0] x;
        reg signed [32:0] rounded;
        begin rounded=(x>>>1)+((x[0] && x[1]) ? 33'sd1 : 33'sd0);round_half=rounded[31:0];end
    endfunction
    assign in_ready=state==LOAD;
    assign busy=state!=IDLE;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; done<=0; out_valid<=0; out_bin<=0; out_re<=0; out_im<=0;
            load_count<=0; base<=0; offset<=0; stage<=0; half_size<=1;
            ur<=0;ui<=0;vr<=0;vi<=0;tr<=0;ti<=0;rr<=0;ii<=0;ri<=0;ir<=0;
        end else begin
            done<=0;
            case (state)
                IDLE: if (start) begin state<=LOAD; load_count<=0; out_valid<=0; end
                LOAD: if (in_valid) begin
                    load_count<=load_count+1'b1;
                    if (load_count==1023) begin
                        stage<=0;half_size<=1;base<=0;offset<=0;state<=READ;
                    end
                end
                READ: state<=CAPTURE;
                CAPTURE: begin
                    ur<=ram_a_q[63:32];ui<=ram_a_q[31:0];
                    vr<=ram_b_q[63:32];vi<=ram_b_q[31:0];state<=MUL;
                end
                MUL: begin rr<=vr*wr;ii<=vi*wi;ri<=vr*wi;ir<=vi*wr;state<=SUM;end
                SUM: begin
                    // Unity twiddle is exact: +1 cannot be represented in signed Q1.15.
                    if (offset==0) begin tr<=vr;ti<=vi;end
                    else begin tr<=round_twiddle(prod_re);ti<=round_twiddle(prod_im);end
                    state<=WRITE;
                end
                WRITE: begin
                    if (offset+1 < half_size) begin offset<=offset+1'b1;state<=READ;end
                    else if ({1'b0,base}+(half_size<<1)<1024) begin
                        base<=base+(half_size<<1);offset<=0;state<=READ;
                    end else if (stage<9) begin
                        stage<=stage+1'b1;half_size<=half_size<<1;base<=0;offset<=0;state<=READ;
                    end else begin out_bin<=0;state<=FETCH;end
                end
                FETCH: state<=FETCH_CAPTURE;
                FETCH_CAPTURE: begin out_re<=ram_a_q[63:32];out_im<=ram_a_q[31:0];out_valid<=1;state<=SEND;end
                SEND: if (out_ready) begin
                    out_valid<=0;
                    if (out_bin==1023) begin state<=IDLE;done<=1;end
                    else begin out_bin<=out_bin+1'b1;state<=FETCH;end
                end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
