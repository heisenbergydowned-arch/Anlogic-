/*
	rgb -> yuv, 4 pixel per clk 
*/
module rgb2yuv_4ppc(
	input	aclk,
	input	aresetn,
	
    input           proc_en         ,
	input	[96:0]	s_axis_tdata	,
	input			s_axis_tvalid	,
	input			s_axis_tlast	,
	input			s_axis_tuser	,
	output			s_axis_tready	,

	// output	[96:0]	m_axis_tdata	,
    output	[31:0]	m_axis_tdata	,
	output			m_axis_tvalid	,
	output			m_axis_tlast	,
	output			m_axis_tuser	,
	input			m_axis_tready
);

wire [23:0] p1_data = s_axis_tdata[95:72];
wire [23:0] p2_data = s_axis_tdata[71:48];
wire [23:0] p3_data = s_axis_tdata[47:24];
wire [23:0] p4_data = s_axis_tdata[23: 0];

// p1
wire [7:0] p1_r = p1_data[23:16];
wire [7:0] p1_g = p1_data[15:8];
wire [7:0] p1_b = p1_data[7:0];

reg [15:0] p1_r1, p1_g1, p1_b1;
reg [15:0] p1_r2, p1_g2, p1_b2;
reg [15:0] p1_r3, p1_g3, p1_b3;

reg [15:0] p1_y1;
reg [7:0]  p1_y2;

// p2
wire [7:0] p2_r = p2_data[23:16];
wire [7:0] p2_g = p2_data[15:8];
wire [7:0] p2_b = p2_data[7:0];

reg [15:0] p2_r1, p2_g1, p2_b1;
reg [15:0] p2_r2, p2_g2, p2_b2;
reg [15:0] p2_r3, p2_g3, p2_b3;

reg [15:0] p2_y1;
reg [7:0]  p2_y2;

// p3
wire [7:0] p3_r = p3_data[23:16];
wire [7:0] p3_g = p3_data[15:8];
wire [7:0] p3_b = p3_data[7:0];

reg [15:0] p3_r1, p3_g1, p3_b1;
reg [15:0] p3_r2, p3_g2, p3_b2;
reg [15:0] p3_r3, p3_g3, p3_b3;

reg [15:0] p3_y1;
reg [7:0]  p3_y2;

// p4
wire [7:0] p4_r = p4_data[23:16];
wire [7:0] p4_g = p4_data[15:8];
wire [7:0] p4_b = p4_data[7:0];

reg [15:0] p4_r1, p4_g1, p4_b1;
reg [15:0] p4_r2, p4_g2, p4_b2;
reg [15:0] p4_r3, p4_g3, p4_b3;

reg [15:0] p4_y1;
reg [7:0]  p4_y2;

reg [2:0] s_axis_tvalid_dly;
reg [2:0] s_axis_tlast_dly;	
reg [2:0] s_axis_tuser_dly;	
reg [2:0] proc_en_dly;
reg [95:0] s_axis_tdata_dly1;
reg [95:0] s_axis_tdata_dly2;

// assign m_axis_tdata = proc_en_dly[2] ? {{p1_y2, p1_y2, p1_y2}, {p2_y2, p2_y2, p2_y2}, {p3_y2, p3_y2, p3_y2}, {p4_y2, p4_y2, p4_y2}} : s_axis_tdata_dly2;
assign m_axis_tdata = {p1_y2, p2_y2, p3_y2, p4_y2};
assign m_axis_tvalid = s_axis_tvalid_dly[2];
assign m_axis_tlast = s_axis_tlast_dly[2];
assign m_axis_tuser = s_axis_tuser_dly[2];

always @(posedge aclk or negedge aresetn) begin
    if(~aresetn)begin
		// p1
        {p1_r1, p1_g1, p1_b1} <= {16'd0, 16'd0, 16'd0};
        {p1_r2, p1_g2, p1_b2} <= {16'd0, 16'd0, 16'd0};
        {p1_r3, p1_g3, p1_b3} <= {16'd0, 16'd0, 16'd0};
		// p2
        {p2_r1, p2_g1, p2_b1} <= {16'd0, 16'd0, 16'd0};
        {p2_r2, p2_g2, p2_b2} <= {16'd0, 16'd0, 16'd0};
        {p2_r3, p2_g3, p2_b3} <= {16'd0, 16'd0, 16'd0};
		// p3
        {p3_r1, p3_g1, p3_b1} <= {16'd0, 16'd0, 16'd0};
        {p3_r2, p3_g2, p3_b2} <= {16'd0, 16'd0, 16'd0};
        {p3_r3, p3_g3, p3_b3} <= {16'd0, 16'd0, 16'd0};
		// p4
        {p4_r1, p4_g1, p4_b1} <= {16'd0, 16'd0, 16'd0};
        {p4_r2, p4_g2, p4_b2} <= {16'd0, 16'd0, 16'd0};
        {p4_r3, p4_g3, p4_b3} <= {16'd0, 16'd0, 16'd0};
    end
    else begin
		// p1
        {p1_r1, p1_g1, p1_b1} <= { {p1_r * 16'd77},  {p1_g * 16'd150}, {p1_b * 16'd29 } };
        {p1_r2, p1_g2, p1_b2} <= { {p1_r * 16'd43},  {p1_g * 16'd85},  {p1_b * 16'd128} };
        {p1_r3, p1_g3, p1_b3} <= { {p1_r * 16'd128}, {p1_g * 16'd107}, {p1_b * 16'd21 } };
		// p2
        {p2_r1, p2_g1, p2_b1} <= { {p2_r * 16'd77},  {p2_g * 16'd150}, {p2_b * 16'd29 } };
        {p2_r2, p2_g2, p2_b2} <= { {p2_r * 16'd43},  {p2_g * 16'd85},  {p2_b * 16'd128} };
        {p2_r3, p2_g3, p2_b3} <= { {p2_r * 16'd128}, {p2_g * 16'd107}, {p2_b * 16'd21 } };
		// p3
        {p3_r1, p3_g1, p3_b1} <= { {p3_r * 16'd77},  {p3_g * 16'd150}, {p3_b * 16'd29 } };
        {p3_r2, p3_g2, p3_b2} <= { {p3_r * 16'd43},  {p3_g * 16'd85},  {p3_b * 16'd128} };
        {p3_r3, p3_g3, p3_b3} <= { {p3_r * 16'd128}, {p3_g * 16'd107}, {p3_b * 16'd21 } };
		// p4
        {p4_r1, p4_g1, p4_b1} <= { {p4_r * 16'd77},  {p4_g * 16'd150}, {p4_b * 16'd29 } };
        {p4_r2, p4_g2, p4_b2} <= { {p4_r * 16'd43},  {p4_g * 16'd85},  {p4_b * 16'd128} };
        {p4_r3, p4_g3, p4_b3} <= { {p4_r * 16'd128}, {p4_g * 16'd107}, {p4_b * 16'd21 } };
    end
end

always @(posedge aclk or negedge aresetn) begin
    if(~aresetn)begin
        p1_y1  <= 16'd0;	// p1
        p2_y1  <= 16'd0;	// p2
        p3_y1  <= 16'd0;	// p3
        p4_y1  <= 16'd0;	// p4
    end
    else begin
        p1_y1  <= p1_r1 + p1_g1 + p1_b1;// p1
		p2_y1  <= p2_r1 + p2_g1 + p2_b1;// p2
		p3_y1  <= p3_r1 + p3_g1 + p3_b1;// p3
		p4_y1  <= p4_r1 + p4_g1 + p4_b1;// p4
    end
end

always @(posedge aclk or negedge aresetn) begin
    if(~aresetn)begin
        p1_y2  <= 8'd0;
    end
    else begin
	    p1_y2  <= p1_y1[15:8];// p1
		p2_y2  <= p2_y1[15:8];// p2
		p3_y2  <= p3_y1[15:8];// p3
		p4_y2  <= p4_y1[15:8];// p4
    end
end

always @(posedge aclk or negedge aresetn) begin
    if(~aresetn)begin
        s_axis_tvalid_dly <= 0;
        s_axis_tlast_dly  <= 0;	
        s_axis_tuser_dly  <= 0;	
        proc_en_dly <= 0;
    end
    else begin
	    s_axis_tvalid_dly <= {s_axis_tvalid_dly[1:0], s_axis_tvalid};  
        s_axis_tlast_dly  <= {s_axis_tlast_dly[1:0], s_axis_tlast};  
        s_axis_tuser_dly  <= {s_axis_tuser_dly[1:0], s_axis_tuser}; 
        proc_en_dly <= {proc_en_dly[1:0], proc_en};
    end
end

always @(posedge aclk or negedge aresetn) begin
    if(~aresetn)begin
        s_axis_tdata_dly1 <= 0;
        s_axis_tdata_dly2 <= 0;
    end
    else begin
        s_axis_tdata_dly1 <= s_axis_tdata;
        s_axis_tdata_dly2 <= s_axis_tdata_dly1;
    end
end

endmodule