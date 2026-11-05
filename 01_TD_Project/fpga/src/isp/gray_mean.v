module gray_mean
(
    input           clk,
    input           rstn,

	input	[31:0]	s_axis_tdata	,
	input			s_axis_tvalid	,
	input			s_axis_tuser	,

    output  reg[31:0]   gray_mean   
);

reg [31:0] gray_sum = 0;

always@(posedge clk)begin
    if(s_axis_tuser)begin
        gray_sum <= 0;
        gray_mean <= gray_sum;
    end
    else if(s_axis_tvalid)begin
        gray_sum <= gray_sum + s_axis_tdata[7:0] + s_axis_tdata[15:8] + s_axis_tdata[23:16] + s_axis_tdata[31:24];
    end
end
endmodule
