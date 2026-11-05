`timescale 1ns/1ps
// 39-feature frame engine. Axis-major raw input: Ax, Ay, Az, Bx, By, Bz.
// Each axis has exactly 1024 NEW signed ADC samples. Same frame_id means same time window.
// Backpressure requires an upstream frame buffer; do not connect live sensor pulses directly.
module feature_extract (
    input wire clk, input wire rst_n,
    input wire frame_start, output wire frame_ready, input wire [31:0] frame_id,
    input wire signed [31:0] current_q16, temp_q16, pressure_q16, rpm_q16,
    input wire [15:0] input_quality,
    input wire sample_valid, output wire sample_ready, input wire signed [15:0] sample_data,
    // Idle-only bin-edge configuration, edge[0]=1, edge[8]=513, strictly increasing.
    input wire cfg_we, input wire [3:0] cfg_index, input wire [9:0] cfg_edge,
    output wire busy, output wire out_valid, input wire out_ready,
    output reg [5:0] out_index, output wire signed [31:0] out_q16,
    output wire [31:0] out_fp32, output wire out_last,
    output reg [31:0] out_frame_id, output reg [15:0] out_quality,
    output reg frame_done
);
    localparam IDLE=0,COLLECT=1,SCAN_READ=2,SCAN_CALC=3,SCAN_FEED=4,
        ROOT_START=5,ROOT_WAIT=6,KURT_START=7,KURT_WAIT=8,FREQ=9,
        BAND_START=10,BAND_WAIT=11,RATIO_START=12,RATIO_WAIT=13,OUTPUT=14,
        SCAN_FOURTH=15,KURT_DEN_CAPTURE=16,OUTPUT_LOAD=17,OUTPUT_CONVERT=18,OUTPUT_WAIT=19,
        SCAN_CAPTURE=20,INIT_FRAME=21,PP_STORE=22,BAND_ACCUM=23,
        BAND_FETCH=24,OUTPUT_CAPTURE=25,FREQ_RE_WAIT=26,FREQ_IM_START=27,FREQ_IM_WAIT=28;
    reg [4:0] state;
    // Sample storage: single-clock simple dual port RAM. One write port used only
    // in COLLECT, one registered read port used only in the scan states. It is
    // deliberately NOT reset: block RAM has no reset, and resetting the array
    // would force it back into distributed registers instead of ERAM.
    (* ram_style="bram" *) reg signed [15:0] samples[0:1023];
    reg signed [15:0] sample_rd_data;
    // Unreset single-write memories. Every slot is initialized before use.
    (* ram_style="bram" *) reg signed [31:0] features[0:38];
    reg signed [31:0] feature_rd;
    reg [63:0] band_rd;
    reg [3:0] init_index,pending_band;
    reg [63:0] pending_power;
    reg signed [31:0] process_current,process_temp,process_pressure,process_rpm;
    (* ram_style="bram" *) reg [63:0] bands[0:15];
    reg [9:0] edges[0:8], active_edges[0:8];
    reg [2:0] axis;
    reg [9:0] collect_index,scan_index;
    wire [9:0] sample_rd_addr=scan_index;
    reg signed [31:0] sum;
    reg signed [15:0] minimum,maximum;
    reg signed [26:0] centered; // raw-code Q10: exact frame mean, no DC rounding
    reg signed [42:0] window_product;
    reg [63:0] sum_sq;
    // With 1024 signed 16-bit samples, abs(1024*x - sum(x)) < 2^26.
    // Hence sum(centered^4) < 2^114 and its Q16 kurtosis numerator < 2^140.
    reg [113:0] sum_fourth;
    wire signed [53:0] centered_square_signed=centered*centered;
    wire [53:0] centered_square=centered_square_signed;
    reg [53:0] square_register;
    reg [107:0] fourth_register;
    // One shared exact multi-cycle squarer for the whole module: it serves the
    // 54x54 fourth-moment square (SCAN_FOURTH) and the 64x64 kurtosis denominator
    // square (KURT_DEN_CAPTURE). The two uses live in disjoint phases, so a single
    // instance suffices. start is a one-cycle pulse decoded from state; it must be
    // asserted in the same cycle as the operand, so both are driven combinationally
    // from registers that already hold the right value in that state.
    reg [63:0] spectrum_im, spectrum_re_power;
    reg spectrum_nyquist;
    wire fft_out_valid;
    wire [9:0] fft_bin;
    wire signed [31:0] fft_re,fft_im;
    reg [3:0] matched_band;
    reg matched;
    wire spectrum_start=state==FREQ && fft_out_valid && fft_bin>=1 && fft_bin<=512 && matched;
    wire sq_start=(state==SCAN_CALC) || (state==KURT_START && sum_sq!=0) || spectrum_start || state==FREQ_IM_START;
    // Squaring a sign-extended two's-complement value gives the exact signed
    // 32-bit square in the low 64 bits. No unsigned magnitude conversion needed.
    wire [63:0] sq_operand=spectrum_start ? {{32{fft_re[31]}},fft_re} :
        (state==FREQ_IM_START ? spectrum_im : ((state==SCAN_CALC) ? {10'd0,centered_square} : sum_sq));
    wire sq_done;
    wire [127:0] sq_result;
    feature_square64 squarer(.clk(clk),.rst_n(rst_n),.start(sq_start),.operand(sq_operand),
        .busy(),.done(sq_done),.result(sq_result));
    // Same clock, no reset. Write port (COLLECT) and read port (scan) never touch
    // the same address in the same cycle. Read data appears one clock after
    // sample_rd_addr is presented, which is why SCAN_CAPTURE exists.
    always @(posedge clk) begin
        if (rst_n && state==COLLECT && sample_valid) samples[collect_index]<=sample_data;
        sample_rd_data<=samples[sample_rd_addr];
    end
    wire signed [31:0] sum_next=sum+{{16{sample_data[15]}},sample_data};
    wire [16:0] peak_to_peak=$signed({maximum[15],maximum})-$signed({minimum[15],minimum});
    wire signed [15:0] hann;
    feature_hann_rom window_rom(.clk(clk),.addr(scan_index),.value(hann));
    reg fft_start;
    wire fft_in_ready,fft_busy,fft_done;
    wire signed [31:0] fft_input_q12=window_product>>>13;
    fft1024_iter fft(.clk(clk),.rst_n(rst_n),.start(fft_start),
        .in_valid(state==SCAN_FEED),.in_ready(fft_in_ready),.in_data(fft_input_q12),
        .out_valid(fft_out_valid),.out_ready(state==FREQ),.out_bin(fft_bin),
        .out_re(fft_re),.out_im(fft_im),.busy(fft_busy),.done(fft_done));
    wire [63:0] serial_bin_power=spectrum_re_power+sq_result[63:0];
    wire [63:0] serial_one_sided_power=spectrum_nyquist ? serial_bin_power : (serial_bin_power<<1);
    reg root_start;
    wire root_busy,root_done;
    wire [31:0] root_result;
    feature_isqrt root(.clk(clk),.rst_n(rst_n),.start(root_start),
        .radicand(sum_sq>>6),.busy(root_busy),.done(root_done),.root(root_result));
    reg div_start;
    reg [139:0] div_num,div_den;
    wire div_busy,div_done,div_zero;
    wire [139:0] div_result;
    feature_udiv #(.WIDTH(140)) div(.clk(clk),.rst_n(rst_n),.start(div_start),
        .numerator(div_num),.denominator(div_den),.busy(div_busy),.done(div_done),
        .div_zero(div_zero),.quotient(div_result));
    reg [3:0] band_index;
    reg [63:0] total_a,total_b;
    reg [32:0] rms_a_sum,rms_b_sum;
    integer i;
    wire [1:0] axis_in_point=(axis<3) ? axis[1:0]:(axis-3'd3);
    wire [4:0] feature_base=(axis<3) ? 5'd0 : 5'd17;
    wire config_ok=edges[0]==1 && edges[8]==513 &&
        edges[0]<edges[1] && edges[1]<edges[2] && edges[2]<edges[3] && edges[3]<edges[4] &&
        edges[4]<edges[5] && edges[5]<edges[6] && edges[6]<edges[7] && edges[7]<edges[8];
    assign frame_ready=state==IDLE;
    assign busy=state!=IDLE;
    assign sample_ready=state==COLLECT;
    assign out_valid=state==OUTPUT;
    reg signed [31:0] output_value;
    reg [31:0] output_float;
    wire [31:0] converted_float;
    wire float_done;
    assign out_q16=output_value;
    assign out_fp32=output_float;
    assign out_last=out_index==38;
    feature_float_serial convert(.clk(clk),.rst_n(rst_n),.start(state==OUTPUT_CONVERT),.q16(output_value),.busy(),.done(float_done),.fp32(converted_float));
    // One band update per FFT bin replaces sixteen parallel 64-bit adders.
    // Hold the FFT output while the synchronous band read is accumulated.
    integer lookup;
    always @* begin
        matched=0;matched_band=0;
        for(lookup=0;lookup<8;lookup=lookup+1)
            if(fft_bin>=active_edges[lookup] && fft_bin<active_edges[lookup+1])begin
                matched=1;matched_band={axis>=3,3'b000}+lookup;
            end
    end
    wire [3:0] band_read_address=(state==FREQ) ? matched_band:
        ((state==BAND_ACCUM || state==FREQ_RE_WAIT || state==FREQ_IM_START || state==FREQ_IM_WAIT) ? pending_band:band_index);
    reg feature_we;
    reg [5:0] feature_write_address;
    reg signed [31:0] feature_write_data;
    always @* begin
        feature_we=0;feature_write_address=0;feature_write_data=0;
        case(state)
            INIT_FRAME:if(init_index<4)begin
                feature_we=1;feature_write_address=6'd35+{2'd0,init_index};
                case(init_index)
                    0:feature_write_data=process_current;
                    1:feature_write_data=process_temp;
                    2:feature_write_data=process_pressure;
                    default:feature_write_data=process_rpm;
                endcase
            end
            ROOT_WAIT:if(root_done)begin
                feature_we=1;feature_write_address=feature_base+axis_in_point;feature_write_data=root_result>>8;
            end
            PP_STORE:begin
                feature_we=1;feature_write_address=feature_base+3+axis_in_point;feature_write_data={15'd0,peak_to_peak}<<4;
            end
            KURT_START:if(sum_sq==0)begin feature_we=1;feature_write_address=feature_base+6+axis_in_point;end
            KURT_WAIT:if(div_done)begin feature_we=1;feature_write_address=feature_base+6+axis_in_point;feature_write_data=div_result[31:0];end
            BAND_WAIT:if(div_done)begin
                feature_we=1;feature_write_address=(band_index<8 ? 9 : 26)+band_index[2:0];feature_write_data=div_result[31:0];
            end
            RATIO_START:if(rms_b_sum==0)begin
                feature_we=1;feature_write_address=34;feature_write_data=(rms_a_sum==0) ? 32'd65536:32'd393216;
            end
            RATIO_WAIT:if(div_done)begin
                feature_we=1;feature_write_address=34;feature_write_data=div_result<19661 ? 32'd19661:
                    (div_result>393216 ? 32'd393216:div_result[31:0]);
            end
        endcase
    end
    always @(posedge clk)begin
        if(rst_n && feature_we)features[feature_write_address]<=feature_write_data;
        feature_rd<=features[out_index];
        if(rst_n && state==INIT_FRAME)bands[init_index]<=0;
        else if(rst_n && state==BAND_ACCUM)bands[pending_band]<=band_rd+pending_power;
        band_rd<=bands[band_read_address];
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE;axis<=0;collect_index<=0;scan_index<=0;
            sum<=0;minimum<=16'sh7fff;maximum<=16'sh8000;
            centered<=0;window_product<=0;sum_sq<=0;sum_fourth<=0;
            square_register<=0;fourth_register<=0;
            spectrum_im<=0;spectrum_re_power<=0;spectrum_nyquist<=0;
            fft_start<=0;root_start<=0;div_start<=0;div_num<=0;div_den<=0;
            band_index<=0;total_a<=0;total_b<=0;
            init_index<=0;pending_band<=0;pending_power<=0;rms_a_sum<=0;rms_b_sum<=0;
            process_current<=0;process_temp<=0;process_pressure<=0;process_rpm<=0;
            out_index<=0;out_frame_id<=0;out_quality<=0;frame_done<=0;
            output_value<=0;output_float<=0;
            // Provisional boundaries for Fs=4kHz; these are NOT model training definitions.
            edges[0]<=1;edges[1]<=13;edges[2]<=39;edges[3]<=65;edges[4]<=103;
            edges[5]<=154;edges[6]<=205;edges[7]<=257;edges[8]<=513;
            active_edges[0]<=1;active_edges[1]<=13;active_edges[2]<=39;active_edges[3]<=65;
            active_edges[4]<=103;active_edges[5]<=154;active_edges[6]<=205;
            active_edges[7]<=257;active_edges[8]<=513;

        end else begin
            fft_start<=0;root_start<=0;div_start<=0;frame_done<=0;
            if (cfg_we && frame_ready && cfg_index<9) edges[cfg_index]<=cfg_edge;
            case (state)
                IDLE: if (frame_start && !cfg_we) begin
                    axis<=0;collect_index<=0;scan_index<=0;sum<=0;sum_sq<=0;sum_fourth<=0;
                    minimum<=16'sh7fff;maximum<=16'sh8000;
                    total_a<=0;total_b<=0;rms_a_sum<=0;rms_b_sum<=0;init_index<=0;
                    if (config_ok) for (i=0;i<9;i=i+1) active_edges[i]<=edges[i];
                    out_frame_id<=frame_id;
                    out_quality<=input_quality | (config_ok ? 16'd0 : 16'h0002);
                    process_current<=current_q16;process_temp<=temp_q16;
                    process_pressure<=pressure_q16;process_rpm<=rpm_q16;
                    state<=INIT_FRAME;
                end
                INIT_FRAME:if(init_index==15)state<=COLLECT;else init_index<=init_index+1'b1;
                COLLECT: if (sample_valid) begin
                    sum<=sum_next;
                    if (sample_data<minimum) minimum<=sample_data;
                    if (sample_data>maximum) maximum<=sample_data;
                    if (sample_data==16'sh7fff || sample_data==16'sh8000) out_quality[2]<=1;
                    if (collect_index==1023) begin
                        scan_index<=0;fft_start<=1;state<=SCAN_READ;
                    end else collect_index<=collect_index+1'b1;
                end
                SCAN_READ: begin
                    state<=SCAN_CAPTURE;
                end
                SCAN_CAPTURE: begin
                    // Registered RAM read: sample_rd_data now holds samples[scan_index].
                    centered<=($signed(sample_rd_data)*32'sd1024)-sum;
                    state<=SCAN_CALC;
                end
                SCAN_CALC: begin
                    // hann is the ROM output addressed by scan_index, which has been
                    // held unchanged since SCAN_READ, so Hann alignment is preserved.
                    // sq_start/sq_operand are decoded from this state, so the squarer
                    // captures centered_square on the SCAN_CALC->SCAN_FOURTH edge.
                    window_product<=centered*hann;
                    square_register<=centered_square;
                    state<=SCAN_FOURTH;
                end
                SCAN_FOURTH: if (sq_done) begin // wait for the shared squarer
                    fourth_register<=sq_result[107:0];state<=SCAN_FEED;
                end
                SCAN_FEED: if (fft_in_ready) begin
                    sum_sq<=sum_sq+square_register;sum_fourth<=sum_fourth+fourth_register;
                    if (scan_index==1023) state<=ROOT_START;
                    else begin scan_index<=scan_index+1'b1;state<=SCAN_READ;end
                end
                ROOT_START: begin root_start<=1;state<=ROOT_WAIT;end
                ROOT_WAIT: if (root_done) begin
                    if(axis<2)rms_a_sum<=rms_a_sum+{1'b0,(root_result>>8)};
                    if(axis==3 || axis==4)rms_b_sum<=rms_b_sum+{1'b0,(root_result>>8)};
                    state<=PP_STORE;
                end
                PP_STORE:state<=KURT_START;
                KURT_START: begin
                    if (sum_sq==0) begin
                        out_quality[0]<=1;state<=FREQ;
                    end else begin
                        // sq_start/sq_operand are decoded from KURT_START, so the
                        // squarer captures sum_sq on the KURT_START->KURT_DEN_CAPTURE edge.
                        state<=KURT_DEN_CAPTURE;
                    end
                end
                KURT_DEN_CAPTURE: if (sq_done) begin // wait for the shared squarer
                    div_num<={sum_fourth,26'd0};div_den<=sq_result;
                    div_start<=1;state<=KURT_WAIT;
                end
                KURT_WAIT: if (div_done) begin
                    state<=FREQ;
                end
                FREQ: begin
                    if (fft_out_valid && fft_bin>=1 && fft_bin<=512) begin
                        if(matched)begin
                            pending_band<=matched_band;spectrum_im<={{32{fft_im[31]}},fft_im};
                            spectrum_nyquist<=fft_bin==512;state<=FREQ_RE_WAIT;
                        end
                    end
                    if (fft_done) begin
                        if (axis==5) begin
                            band_index<=0;state<=BAND_FETCH;
                        end else begin
                            axis<=axis+1'b1;collect_index<=0;sum<=0;sum_sq<=0;sum_fourth<=0;
                            minimum<=16'sh7fff;maximum<=16'sh8000;state<=COLLECT;
                        end
                    end
                end
                FREQ_RE_WAIT:if(sq_done)begin spectrum_re_power<=sq_result[63:0];state<=FREQ_IM_START;end
                FREQ_IM_START:state<=FREQ_IM_WAIT;
                FREQ_IM_WAIT:if(sq_done)begin pending_power<=serial_one_sided_power;state<=BAND_ACCUM;end
                BAND_ACCUM:begin
                    if(pending_band<8)total_a<=total_a+pending_power;
                    else total_b<=total_b+pending_power;
                    state<=FREQ;
                end
                BAND_FETCH:state<=BAND_START;
                BAND_START: begin
                    div_num<={16'd0,band_rd,16'd0};
                    div_den<=(band_index<8) ? total_a : total_b;
                    div_start<=1;state<=BAND_WAIT;
                end
                BAND_WAIT: if (div_done) begin
                    if (div_zero) out_quality[0]<=1;
                    if (band_index==15) state<=RATIO_START;
                    else begin band_index<=band_index+1'b1;state<=BAND_FETCH;end
                end
                RATIO_START: begin
                    if (rms_b_sum==0) begin
                        out_quality[0]<=1;out_index<=0;state<=OUTPUT_LOAD;
                    end else begin
                        div_num<={47'd0,rms_a_sum,16'd0};div_den<=rms_b_sum;
                        div_start<=1;state<=RATIO_WAIT;
                    end
                end
                RATIO_WAIT: if (div_done) begin
                    out_index<=0;state<=OUTPUT_LOAD;
                end
                OUTPUT_LOAD:state<=OUTPUT_CAPTURE;
                OUTPUT_CAPTURE:begin output_value<=feature_rd;state<=OUTPUT_CONVERT;end
                OUTPUT_CONVERT:state<=OUTPUT_WAIT;
                OUTPUT_WAIT:if(float_done)begin output_float<=converted_float;state<=OUTPUT;end
                OUTPUT: if (out_ready) begin
                    if (out_index==38) begin state<=IDLE;frame_done<=1;end
                    else begin out_index<=out_index+1'b1;state<=OUTPUT_LOAD;end
                end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
