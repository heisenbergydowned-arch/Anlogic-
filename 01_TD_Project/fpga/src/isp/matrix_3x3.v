module matrix_3x3(
	input	clk,
	input	resetn,
	
	input	[31:0] din,
	input	en,
	
	output	reg [31:0] m_1x1, m_1x2, m_1x3,
	output	reg [31:0] m_2x1, m_2x2, m_2x3,
	output	reg [31:0] m_3x1, m_3x2, m_3x3
);

wire [31:0] data0;
wire [31:0] data1;

always@(posedge clk)begin
	if(~resetn)begin
		{m_1x1, m_1x2, m_1x3} <= {0, 0, 0};
		{m_2x1, m_2x2, m_2x3} <= {0, 0, 0};
		{m_3x1, m_3x2, m_3x3} <= {0, 0, 0};
	end
	else begin
		{m_1x1, m_1x2, m_1x3} <= {m_1x2, m_1x3, data1};
	    {m_2x1, m_2x2, m_2x3} <= {m_2x2, m_2x3, data0};
	    {m_3x1, m_3x2, m_3x3} <= {m_3x2, m_3x3, din};
	end
end

shift_ram		u_shift_ram
(
	.clk		(clk),

	.din		(din),
	.data0		(data0),
	.data1		(data1),

	.en         (en)
	
);
endmodule