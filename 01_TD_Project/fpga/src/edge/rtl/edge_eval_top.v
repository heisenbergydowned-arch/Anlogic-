// Isolated resource/timing evaluation. Synthetic feature source only; no PWM.
module edge_eval_top(
    input wire clk,rst_n,req,write_en,input wire [15:0] address,input wire [31:0] wdata,
    output wire response,output wire [31:0] rdata,output wire [7:0] error,output wire frame_available
);
    wire new_sample,adc_new,temp_new,fg_new;
    wire signed [15:0] ax,ay,az,bx,by,bz,ci,pr,tr;wire [15:0] seq;wire [31:0] period;
    reg [31:0] ms_div,now_ms;
    always @(posedge clk or negedge rst_n)if(!rst_n)begin ms_div<=0;now_ms<=0;end
    else if(ms_div==99999)begin ms_div<=0;now_ms<=now_ms+1;end else ms_div<=ms_div+1;
    edge_test_source source(.clk(clk),.rst_n(rst_n),.sample_new(new_sample),.adc_new(adc_new),.temp_new(temp_new),.fg_new(fg_new),
        .ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),.sample_seq(seq),.current_raw(ci),.pressure_raw(pr),.temp_raw(tr),.fg_period(period));
    edge_features #(.TEST_MODE(1)) features(.clk(clk),.rst_n(rst_n),.now_ms(now_ms),
        .a_new(new_sample),.b_new(new_sample),.ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),.a_seq(seq),.b_seq(seq),.a_bad(1'b0),.b_bad(1'b0),
        .adc_new(adc_new),.adc_bad(1'b0),.current_raw(ci),.pressure_raw(pr),.pressure_new(adc_new),.pressure_bad(1'b0),
        .temp_new(temp_new),.temp_bad(1'b0),.temp_raw(tr),
        .fg_new(fg_new),.fg_bad(1'b0),.fg_period(period),.control_mode(4'd3),.local_permit(1'b0),.initial_config_permit(1'b0),
        .req(req),.write_en(write_en),.address(address),.wdata(wdata),.response(response),.rdata(rdata),.error(error),.frame_available(frame_available),.busy());
endmodule
