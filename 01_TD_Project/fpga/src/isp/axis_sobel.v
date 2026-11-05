
module axis_sobel(
	/* system signals */
	input	aclk,
	input	aresetn,
	
	/* input axis */
	input	[31:0]	s_axis_tdata	,
	input			s_axis_tvalid	,
	input			s_axis_tlast	,
	input			s_axis_tuser	,
	output			s_axis_tready	,
	/* output axis */
	output	[95:0]	m_axis_tdata	,
	output			m_axis_tvalid	,
	output			m_axis_tlast	,
	output			m_axis_tuser	,
	input			m_axis_tready
);

parameter THRO = 16384;
wire [31:0] m_1x1, m_1x2, m_1x3;
wire [31:0] m_2x1, m_2x2, m_2x3;
wire [31:0] m_3x1, m_3x2, m_3x3;

wire [7:0] p1_1x1, p1_1x2, p1_1x3;
wire [7:0] p1_2x1, p1_2x2, p1_2x3;
wire [7:0] p1_3x1, p1_3x2, p1_3x3; 

wire [7:0] p2_1x1, p2_1x2, p2_1x3;
wire [7:0] p2_2x1, p2_2x2, p2_2x3;
wire [7:0] p2_3x1, p2_3x2, p2_3x3; 

wire [7:0] p3_1x1, p3_1x2, p3_1x3;
wire [7:0] p3_2x1, p3_2x2, p3_2x3;
wire [7:0] p3_3x1, p3_3x2, p3_3x3; 

wire [7:0] p4_1x1, p4_1x2, p4_1x3;
wire [7:0] p4_2x1, p4_2x2, p4_2x3;
wire [7:0] p4_3x1, p4_3x2, p4_3x3;

assign {p1_1x1, p1_1x2, p1_1x3, p2_1x1, p2_1x2, p2_1x3, p3_1x1, p3_1x2, p3_1x3, p4_1x1, p4_1x2, p4_1x3} = {m_1x1, m_1x2, m_1x3};
assign {p1_2x1, p1_2x2, p1_2x3, p2_2x1, p2_2x2, p2_2x3, p3_2x1, p3_2x2, p3_2x3, p4_2x1, p4_2x2, p4_2x3} = {m_2x1, m_2x2, m_2x3};
assign {p1_3x1, p1_3x2, p1_3x3, p2_3x1, p2_3x2, p2_3x3, p3_3x1, p3_3x2, p3_3x3, p4_3x1, p4_3x2, p4_3x3} = {m_3x1, m_3x2, m_3x3};

reg [9:0] p1_gx0, p1_gx1;
reg [9:0] p1_gy0, p1_gy1;
reg [9:0] p1_gx, p1_gy;
reg [20:0] p1_gxy;

reg [9:0] p2_gx0, p2_gx1;
reg [9:0] p2_gy0, p2_gy1;
reg [9:0] p2_gx, p2_gy;
reg [20:0] p2_gxy;

reg [9:0] p3_gx0, p3_gx1;
reg [9:0] p3_gy0, p3_gy1;
reg [9:0] p3_gx, p3_gy;
reg [20:0] p3_gxy;

reg [9:0] p4_gx0, p4_gx1;
reg [9:0] p4_gy0, p4_gy1;
reg [9:0] p4_gx, p4_gy;
reg [20:0] p4_gxy;

wire [7:0] p1_data;
wire [7:0] p2_data;
wire [7:0] p3_data;
wire [7:0] p4_data;

reg [3:0] s_axis_tvalid_dly;
reg [3:0] s_axis_tlast_dly ;
reg [3:0] s_axis_tuser_dly ;
reg [3:0] m_axis_tready_dly;

assign m_axis_tvalid = s_axis_tvalid_dly[3];
assign m_axis_tlast = s_axis_tlast_dly[3];
assign m_axis_tuser = s_axis_tuser_dly[3];
assign s_axis_tready = m_axis_tready_dly[3];

assign p1_data = (p1_gxy > THRO) ? 8'hff : 8'h00;
assign p2_data = (p2_gxy > THRO) ? 8'hff : 8'h00;
assign p3_data = (p3_gxy > THRO) ? 8'hff : 8'h00;
assign p4_data = (p4_gxy > THRO) ? 8'hff : 8'h00;

assign m_axis_tdata = {p1_data, p1_data, p1_data, p2_data, p2_data, p2_data, p3_data, p3_data, p3_data, p4_data, p4_data, p4_data};
always@(posedge aclk)begin
	if(~aresetn)begin
		p1_gx0 <= 0;
		p1_gx1 <= 0;
		p1_gy0 <= 0;
		p1_gy1 <= 0;
		
		p2_gx0 <= 0;
		p2_gx1 <= 0;
		p2_gy0 <= 0;
		p2_gy1 <= 0;
		
		p3_gx0 <= 0;
		p3_gx1 <= 0;
		p3_gy0 <= 0;
		p3_gy1 <= 0;
		
		p4_gx0 <= 0;
		p4_gx1 <= 0;
		p4_gy0 <= 0;
		p4_gy1 <= 0;
	end
	else begin
		p1_gx0 <= p1_1x1 + (p1_1x2 << 1) + p1_1x3;
		p1_gx1 <= p1_3x1 + (p1_3x2 << 1) + p1_3x3;
		p1_gy0 <= p1_1x1 + (p1_2x1 << 1) + p1_3x1;
		p1_gy1 <= p1_1x3 + (p1_2x3 << 1) + p1_3x3;
		
		p2_gx0 <= p2_1x1 + (p2_1x2 << 1) + p2_1x3;
		p2_gx1 <= p2_3x1 + (p2_3x2 << 1) + p2_3x3;
		p2_gy0 <= p2_1x1 + (p2_2x1 << 1) + p2_3x1;
		p2_gy1 <= p2_1x3 + (p2_2x3 << 1) + p2_3x3;
		
		p3_gx0 <= p3_1x1 + (p3_1x2 << 1) + p3_1x3;
		p3_gx1 <= p3_3x1 + (p3_3x2 << 1) + p3_3x3;
		p3_gy0 <= p3_1x1 + (p3_2x1 << 1) + p3_3x1;
		p3_gy1 <= p3_1x3 + (p3_2x3 << 1) + p3_3x3;
		
		p4_gx0 <= p4_1x1 + (p4_1x2 << 1) + p4_1x3;
		p4_gx1 <= p4_3x1 + (p4_3x2 << 1) + p4_3x3;
		p4_gy0 <= p4_1x1 + (p4_2x1 << 1) + p4_3x1;
		p4_gy1 <= p4_1x3 + (p4_2x3 << 1) + p4_3x3;
	end
end
always@(posedge aclk)begin
	if(~aresetn)begin
		p1_gx <= 0;
		p1_gy <= 0;
		
		p2_gx <= 0;
		p2_gy <= 0;
		
		p3_gx <= 0;
		p3_gy <= 0;
		
		p4_gx <= 0;
		p4_gy <= 0;
	end
	else begin
		p1_gx <= (p1_gx0 > p1_gx1) ? (p1_gx0 - p1_gx1) : (p1_gx1 - p1_gx0);
		p1_gy <= (p1_gy0 > p1_gy1) ? (p1_gy0 - p1_gy1) : (p1_gy1 - p1_gy0);
		
		p2_gx <= (p2_gx0 > p2_gx1) ? (p2_gx0 - p2_gx1) : (p2_gx1 - p2_gx0);
		p2_gy <= (p2_gy0 > p2_gy1) ? (p2_gy0 - p2_gy1) : (p2_gy1 - p2_gy0);
		
		p3_gx <= (p3_gx0 > p3_gx1) ? (p3_gx0 - p3_gx1) : (p3_gx1 - p3_gx0);
		p3_gy <= (p3_gy0 > p3_gy1) ? (p3_gy0 - p3_gy1) : (p3_gy1 - p3_gy0);
		
		p4_gx <= (p4_gx0 > p4_gx1) ? (p4_gx0 - p4_gx1) : (p4_gx1 - p4_gx0);
		p4_gy <= (p4_gy0 > p4_gy1) ? (p4_gy0 - p4_gy1) : (p4_gy1 - p4_gy0);
	end	
end
always@(posedge aclk)begin
	if(~aresetn)begin
		p1_gxy <= 0;
		p2_gxy <= 0;
		p3_gxy <= 0;
		p4_gxy <= 0;
	end
	else begin
		p1_gxy <= p1_gx * p1_gx + p1_gy * p1_gy;
		p2_gxy <= p2_gx * p2_gx + p2_gy * p2_gy;
		p3_gxy <= p3_gx * p3_gx + p3_gy * p3_gy;
		p4_gxy <= p4_gx * p4_gx + p4_gy * p4_gy;
	end
end

always@(posedge aclk)begin
	if(~aresetn)begin
		s_axis_tvalid_dly	<= 0;
	    s_axis_tlast_dly 	<= 0;
	    s_axis_tuser_dly 	<= 0;
	    m_axis_tready_dly	<= 0;
	end
	else begin
		s_axis_tvalid_dly	<= {s_axis_tvalid_dly[2:0], s_axis_tvalid};
		s_axis_tlast_dly 	<= {s_axis_tlast_dly[2:0], s_axis_tlast};
		s_axis_tuser_dly 	<= {s_axis_tuser_dly[2:0], s_axis_tuser};
		m_axis_tready_dly	<= {m_axis_tready_dly[2:0], m_axis_tready};
	end
end
matrix_3x3		u_matrix_3x3
(
	.clk		(aclk),
	.resetn		(aresetn),
	
	.din		(s_axis_tdata),
	.en			(s_axis_tvalid),
	
	.m_1x1		(m_1x1		), 
	.m_1x2		(m_1x2		), 
	.m_1x3		(m_1x3		),
	.m_2x1		(m_2x1		), 
	.m_2x2		(m_2x2		), 
	.m_2x3		(m_2x3		),
	.m_3x1		(m_3x1		), 
	.m_3x2		(m_3x2		), 
	.m_3x3		(m_3x3		)
);
endmodule
