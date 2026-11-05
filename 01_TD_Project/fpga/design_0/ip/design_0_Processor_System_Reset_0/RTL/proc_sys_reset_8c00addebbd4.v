
`timescale 1ns/1ns
module proc_sys_reset_8c00addebbd4#(
	parameter		EXTERNAL_RESET_PULSE_WIDTH				= 4,
	parameter		AUXILIARY_RESET_PULSE_WIDTH				= 4,
	parameter		EXTERNAL_RESET_IS_HIGH			= 1,
	parameter		AUXILIARY_RESET_IS_HIGH			= 1,
	parameter		NUMBER_BUS_OF_RESET				= 1,
	parameter		NUMBER_OF_PERIPHERALS_RESET				= 1,
	parameter		NUMBER_OF_INTERCONNECT_ARESETN	= 1,
	parameter		NUMBER_OF_PERIPHERALS_ARESETN			= 1
)(
	input			clk,
	input			external_reset,
	input			aux_rst,
	input			system_rst,
	input			pll_locked,
	output			soc_reset,
	output	[NUMBER_BUS_OF_RESET-1:0]						bus_reset,
	output	[NUMBER_OF_PERIPHERALS_RESET-1:0]					peripheral_reset,
	output	[NUMBER_OF_INTERCONNECT_ARESETN-1:0]		interconnect_aresetn,
	output	[NUMBER_OF_PERIPHERALS_ARESETN-1:0]				peripheral_aresetn
);

wire			core_out;
wire			peri_rst_out;
wire			bus_struc_reset_out;
wire			low_per_fun_rst;

reg				soc_reset_r			=1'b1;
assign			soc_reset				=soc_reset_r;
always@(posedge clk)begin
	soc_reset_r	<= core_out;
end

reg		[NUMBER_BUS_OF_RESET-1:0]	bus_reset_r	= {NUMBER_BUS_OF_RESET{1'b1}};
assign						bus_reset		=	bus_reset_r;
always@(posedge clk)begin
	bus_reset_r	<= {NUMBER_BUS_OF_RESET{bus_struc_reset_out}};
end

wire										bus_struc_reset_outn				=~(bus_struc_reset_out);
reg		[NUMBER_OF_INTERCONNECT_ARESETN-1:0]	interconnect_aresetn_r	={NUMBER_OF_INTERCONNECT_ARESETN{1'b0}};
assign										interconnect_aresetn	=interconnect_aresetn_r;
always@(posedge clk)begin
	interconnect_aresetn_r <= {NUMBER_OF_INTERCONNECT_ARESETN{bus_struc_reset_outn}};
end

reg		[NUMBER_OF_PERIPHERALS_RESET-1:0]				peripheral_reset_r		={NUMBER_OF_PERIPHERALS_RESET{1'b1}};
assign										peripheral_reset			=peripheral_reset_r;
always@(posedge clk)begin
	peripheral_reset_r	<=	{NUMBER_OF_PERIPHERALS_RESET{peri_rst_out}};
end

wire										peri_rst_outn					= ~(peri_rst_out);
reg		[NUMBER_OF_PERIPHERALS_ARESETN-1:0]			peripheral_aresetn_r	={NUMBER_OF_PERIPHERALS_ARESETN{1'b0}};
assign										peripheral_aresetn		=peripheral_aresetn_r;
always@(posedge clk)begin
	peripheral_aresetn_r	<={NUMBER_OF_PERIPHERALS_ARESETN{peri_rst_outn}};
end

low_per_fun_8c00addebbd4 #(
	.EXTERNAL_RESET_PULSE_WIDTH	(EXTERNAL_RESET_PULSE_WIDTH),
	.AUXILIARY_RESET_PULSE_WIDTH	(AUXILIARY_RESET_PULSE_WIDTH),
	.EXTERNAL_RESET_IS_HIGH	(EXTERNAL_RESET_IS_HIGH),
	.AUXILIARY_RESET_IS_HIGH	(AUXILIARY_RESET_IS_HIGH)
)	u_low_per_fun (
	.system_rst		(system_rst),
	.pll_locked		(pll_locked),
	.external_reset		(external_reset),
	.aux_rst		(aux_rst),
	.clk			(clk),
	.reset_out			(low_per_fun_rst)
);
sequence_psr_8c00addebbd4	u_sequence(
	.low_per_fun_reset		(low_per_fun_rst),
	.clk			(clk),
	.bus_struc_reset_out		(bus_struc_reset_out),
	.peri_rst_out			(peri_rst_out),
	.core_out			(core_out)
);

endmodule

module upcnt_n_8c00addebbd4#(
	parameter	WIDTH = 1
)(
	input	[WIDTH-1:0]		d,
	input					enable,
	input					load,
	input					clear,
	input					clk,
	output	[WIDTH-1:0]		q
);
	reg		[WIDTH-1:0]	cnt = {WIDTH{1'b1}};
	assign	q	=	cnt;
	always@(posedge clk)begin
		if(~clear)		cnt <= 0;
		else if(load)	cnt <= d;
		else if(enable)		cnt <= cnt + 1'b1;
	end
endmodule

module low_per_fun_8c00addebbd4#(
	parameter		EXTERNAL_RESET_PULSE_WIDTH		=4,
	parameter		AUXILIARY_RESET_PULSE_WIDTH		=4,
	parameter		EXTERNAL_RESET_IS_HIGH	=1'b1,
	parameter		AUXILIARY_RESET_IS_HIGH	=1'b1
)(
	input	system_rst,
	input	pll_locked,
	input	external_reset,
	input	aux_rst,
	input	clk,
	output	reset_out	
);
reg	[15:0]	soc_reset_time_out_r	= 16'hFFFF;
wire		soc_reset_time_out	= soc_reset_time_out_r[15];

wire						external_reset_low_per_fun			;
reg	[AUXILIARY_RESET_PULSE_WIDTH-1:0]	asr_low_per_fun			= 0;
reg			low_per_fun_int			= 0;
reg			low_per_fun_exr			= 0;
reg			low_per_fun_asr			= 0;

wire		aux_low_per_fun;
reg		[EXTERNAL_RESET_PULSE_WIDTH-1:0]	external_reset_low_per_fun_r	=	{EXTERNAL_RESET_PULSE_WIDTH{1'b0}};
reg		[AUXILIARY_RESET_PULSE_WIDTH-1:0]	aux_low_per_fun_r	=	{AUXILIARY_RESET_PULSE_WIDTH{1'b0}};

wire	external_reset_single_and_bit		=&external_reset_low_per_fun_r;
wire	external_reset_single_nand_bit	=&(~external_reset_low_per_fun_r);

wire	aux_single_reset_and_bit		=&aux_low_per_fun_r;
wire	aux_signle_reset_nand_bit	=&(~aux_low_per_fun_r);
assign	reset_out		=low_per_fun_int;

integer	index=0;
always@(posedge clk)begin
	for(index=0;index<15;index=index+1)
		soc_reset_time_out_r[index+1]	<=	soc_reset_time_out_r[index];
	soc_reset_time_out_r[0]	<= 1'b0;
end

always@(posedge clk)begin
	low_per_fun_int	<=  low_per_fun_exr | low_per_fun_asr | soc_reset_time_out | (~pll_locked);
end
always@(posedge clk)begin
	if(external_reset_single_and_bit)						low_per_fun_exr	<=1;
	else if(~external_reset_single_and_bit & external_reset_single_nand_bit)	low_per_fun_exr	<=0;
end
always@(posedge clk)begin
	if(aux_single_reset_and_bit)						low_per_fun_asr	<=1;
	else if(~aux_single_reset_and_bit & aux_signle_reset_nand_bit)	low_per_fun_asr <=0;
end

localparam	SYNCHRONIZATION_STAGE =4;
reg [SYNCHRONIZATION_STAGE-1:0]	cdc_synchronization_external	= {SYNCHRONIZATION_STAGE{1'b0}};
wire					external_reset_real			=	EXTERNAL_RESET_IS_HIGH	?	external_reset | system_rst	:
																	~external_reset | system_rst;
always@(posedge clk)begin
	for(index=0; index < SYNCHRONIZATION_STAGE-1; index = index+1)begin
		cdc_synchronization_external[index+1] <= cdc_synchronization_external[index];
	end
	cdc_synchronization_external[0] <= external_reset_real;
end
assign	external_reset_low_per_fun		=	cdc_synchronization_external[SYNCHRONIZATION_STAGE-1];

reg [SYNCHRONIZATION_STAGE-1:0]	cdc_synchronization_auxiliary	= {SYNCHRONIZATION_STAGE{1'b0}};
wire					aux_reset_real			=	AUXILIARY_RESET_IS_HIGH	?	aux_rst	:	~aux_rst;
always@(posedge clk)begin
	for(index=0; index < SYNCHRONIZATION_STAGE-1; index = index+1)begin
		cdc_synchronization_auxiliary[index+1] <= cdc_synchronization_auxiliary[index];
	end
	cdc_synchronization_auxiliary[0] <= aux_reset_real;
end
assign	aux_low_per_fun		=	cdc_synchronization_auxiliary[SYNCHRONIZATION_STAGE-1];

always@(posedge clk)begin
	for(index=0; index < EXTERNAL_RESET_PULSE_WIDTH-1; index = index +1 )begin
		external_reset_low_per_fun_r[index+1]	<= external_reset_low_per_fun_r[index];
	end
	external_reset_low_per_fun_r[0]	<=	external_reset_low_per_fun;
end

always@(posedge clk)begin
	for(index=0; index < AUXILIARY_RESET_PULSE_WIDTH-1; index = index +1 )begin
		aux_low_per_fun_r[index+1]	<= aux_low_per_fun_r[index];
	end
	aux_low_per_fun_r[0]	<=	aux_low_per_fun;
end

endmodule

module sequence_psr_8c00addebbd4(
	input		low_per_fun_reset,
	input		clk,
	output		bus_struc_reset_out,
	output		peri_rst_out,
	output		core_out
);

localparam [5:0] BUS_STRUC_RESET_END_LPF_CHIP  =6'b001100;//12
localparam [5:0] BUS_STRUC_RESET_END_SYS       =6'b011001;//25
localparam [5:0] PERIPHERALS_TO_LPF_CHIP   =6'b011100;//28
localparam [5:0] PERIPHERALS_TO_SYSTEM        =6'b101001;//41
localparam [5:0] CORE_TO_LOW_PER_FUN_CHIP =6'b101100;//44
localparam [5:0] CORE_TO_SYSTEM      =6'b111001;//57
localparam [5:0] CHIP_TO_LOW_PER_FUN_CHIP = BUS_STRUC_RESET_END_LPF_CHIP;
localparam [5:0] CHIP_TO_SYSTEM      = BUS_STRUC_RESET_END_SYS;
localparam [5:0] SYSTEM_TO_LPF       = BUS_STRUC_RESET_END_LPF_CHIP;
localparam [5:0] SYSTEM_TO_SYSTEM       = BUS_STRUC_RESET_END_SYS;

reg			from_system		=0;

reg [2:0]	core_dec		=0;
reg			core			=1;
reg	[2:0]	peri_rst_dec			=0;
reg			peri_rst				=1;
reg	[2:0]	bus_struc_reset_dec			=0;
reg			bus_struc_reset				=1;

reg			sequence_clr			=0;
reg			sequence_cnt_en		=0;
wire	[5:0]	sequence_cnt			;

assign		bus_struc_reset_out			=bus_struc_reset;
assign		peri_rst_out			=peri_rst;
assign		core_out			=core;

always@(posedge clk)begin
	if(low_per_fun_reset)			from_system <= 1'b1;
	else if(core == 1'b0)	from_system <= 1'b0;
end

always@(posedge clk)begin
	if(low_per_fun_reset)	sequence_cnt_en	<=1;
	else if(!core)	sequence_cnt_en	<=0;
end

always@(posedge clk)begin
	if(low_per_fun_reset)	sequence_clr<=1'b0;
	else			sequence_clr<=1'b1;
end

always@(posedge clk)begin
	if(low_per_fun_reset)		peri_rst<=1;
	else if(peri_rst_dec[2])	peri_rst<=0;
end

always@(posedge clk)begin
	if(	( sequence_cnt[5:3] == PERIPHERALS_TO_LPF_CHIP[5:3] & (~from_system) )  |
		( sequence_cnt[5:3] == PERIPHERALS_TO_SYSTEM[5:3] & from_system )			)
			peri_rst_dec[0]	<= 1;
	else	peri_rst_dec[0]	<= 0;
	if(	( sequence_cnt[2:0] == PERIPHERALS_TO_LPF_CHIP[2:0] & (~from_system) )  |
		( sequence_cnt[2:0] == PERIPHERALS_TO_SYSTEM[2:0] & from_system )			)
			peri_rst_dec[1]	<= 1;
	else	peri_rst_dec[1]	<= 0;
	peri_rst_dec[2]	<= &peri_rst_dec[1:0];
end

always@(posedge clk)begin
	if(low_per_fun_reset)		bus_struc_reset <= 1;
	else if(bus_struc_reset_dec[2])	bus_struc_reset <= 0;
end

always@(posedge clk)begin
	if(	( sequence_cnt[5:3] == BUS_STRUC_RESET_END_LPF_CHIP[5:3] & (~from_system) )  |
		( sequence_cnt[5:3] == BUS_STRUC_RESET_END_SYS[5:3] & from_system )			)
			bus_struc_reset_dec[0]	<= 1;
	else	bus_struc_reset_dec[0]	<= 0;
	if(	( sequence_cnt[2:0] == BUS_STRUC_RESET_END_LPF_CHIP[2:0] & (~from_system) )  |
		( sequence_cnt[2:0] == BUS_STRUC_RESET_END_SYS[2:0] & from_system )			)
			bus_struc_reset_dec[1]	<= 1;
	else	bus_struc_reset_dec[1]	<= 0;
	bus_struc_reset_dec[2]	<= &bus_struc_reset_dec[1:0];
end

always@(posedge clk)begin
	if(low_per_fun_reset)			core <= 1;
	else if(core_dec[2])	core <= 0;
end

always@(posedge clk)begin
	if(	( sequence_cnt[5:3] == CORE_TO_LOW_PER_FUN_CHIP[5:3] & (~from_system) )  |
		( sequence_cnt[5:3] == CORE_TO_SYSTEM[5:3] & from_system )			)
			core_dec[0]	<= 1;
	else	core_dec[0]	<= 0;
	if(	( sequence_cnt[2:0] == CORE_TO_LOW_PER_FUN_CHIP[2:0] & (~from_system) )  |
		( sequence_cnt[2:0] == CORE_TO_SYSTEM[2:0] & from_system )			)
			core_dec[1]	<= 1;
	else	core_dec[1]	<= 0;
	core_dec[2]	<= &core_dec[1:0];
end

upcnt_n_8c00addebbd4#(
	.WIDTH		(6)
)	u_upcnt_n (
	.d			(6'h00),
 	.enable			(sequence_cnt_en),
 	.load		(1'b0),
 	.clear		(sequence_clr),
 	.clk		(clk),
	.q			(sequence_cnt)
);
endmodule
