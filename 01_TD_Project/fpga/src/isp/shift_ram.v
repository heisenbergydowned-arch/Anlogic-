
module shift_ram
#
(
	parameter RAM_DEPTH = 9
)
(
	input	clk,
	
	input	[31:0]	din,
	output	[31:0]	data0,
	output	[31:0]	data1,
	
	input	en
	
);

reg [RAM_DEPTH - 1:0] addr;

always@(posedge clk)begin
	if(en)begin
		addr <= addr + 1;
	end
	else begin
		addr <= 0;
	end
end
ram0 	ram_line0 (
  .clka		(clk),  
  .cea		(en),   
  // .wea		(1),   
  .addra	(addr), 
  .dia		(din),  
  
  .clkb		(clk),  
  .addrb	(addr + 1), 
  .dob	(data0)  
);
ram0 	ram_line1 (
  .clka		(clk),  
  .cea		(en),   
  // .wea		(1),   
  .addra	(addr + 1), 
  .dia		(data0),  
  
  .clkb		(clk),  
  .addrb	(addr + 2), 
  .dob	(data1)  
);
endmodule