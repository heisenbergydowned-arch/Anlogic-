// module rgb888_to_axi_stream(
//     input   wire       I_clk,
//     input   wire       I_rst_n,    
            
//     input   wire        I_rgb888_frame_start/*synthesis keep*/,
//     input   wire        I_rgb888_frame_end  /*synthesis keep*/,
//     input   wire        I_rgb888_valid      /*synthesis keep*/,
//     input   wire[95:0]  I_rgb888_data       /*synthesis keep*/,
    
//     output  reg [4:0] row_err_cnt, // debug 

//     output  reg   	    O_axi_user          /*synthesis keep*/,
//     output	wire		O_axi_valid         /*synthesis keep*/,
//     output	wire		O_axi_last          /*synthesis keep*/,
//     output	reg [95:0]	O_axi_data          /*synthesis keep*/
// );
//     /* ------ debug ------ */
//     reg [$clog2(1080)-1 : 0] last_cnt;
//     //reg [4:0] row_err_cnt;
//     /* ------------------- */
	
//     reg		S_frame_st_to_va;        //synthesis keep
//     wire	S_axi_user_pre;          //synthesis keep
//     reg		S_rgb888_valid_d;        //synthesis keep
//     wire	S_rgb888_valid_n_edge;   //synthesis keep

//     /* ------ debug ------ */
//     always@(posedge I_clk or negedge I_rst_n)begin
//         if(~I_rst_n)begin
//             last_cnt <= 0;
//         end
//         else begin
//             if(I_rgb888_frame_start)begin
//                 last_cnt <= 0;
//             end
//             else if(O_axi_last)begin
//                 last_cnt <= last_cnt + 1;
//             end
//         end
//     end
//     always@(posedge I_clk or negedge I_rst_n)begin
//         if(~I_rst_n)begin
//             row_err_cnt <= 0;
//         end
//         else begin
//             if(I_rgb888_frame_start && (last_cnt != 1079))begin
//                 row_err_cnt <= row_err_cnt + 1;
//             end
//             else begin
//                 row_err_cnt <= row_err_cnt;
//             end
//         end
//     end
//     /* ------------------- */

//     always@(posedge I_clk or negedge I_rst_n)begin
//     	if(~I_rst_n)
//           	S_frame_st_to_va <= 1'b0;
//         else if(I_rgb888_frame_start)
//         	S_frame_st_to_va <= 1'b1;
//         else if(I_rgb888_valid)	
//         	S_frame_st_to_va <= 1'b0;
//         else
//         	S_frame_st_to_va <= S_frame_st_to_va;
//     end
	
    
//     assign S_axi_user_pre = S_frame_st_to_va & I_rgb888_valid;
    
//     always@(posedge I_clk)begin
//     	O_axi_user       <= S_axi_user_pre;
//         S_rgb888_valid_d <= I_rgb888_valid;
//        	O_axi_data       <= I_rgb888_data;
//     end
 	
    
//     assign O_axi_last = ~I_rgb888_valid & S_rgb888_valid_d;
    
//     assign	O_axi_valid = S_rgb888_valid_d;
        
// endmodule

/*
	Description : RGB888 -> AXI Stream data format, 1080P cutting to 720P
	Date 		: 11/20/2023
*/
module rgb888_to_axi_stream(
    input   wire       	I_clk				,
    input   wire       	I_rst_n				,    
            
    input   wire       	I_rgb888_frame_start,
    input   wire       	I_rgb888_frame_end  ,
    input   wire       	I_rgb888_valid      ,
    input   wire[95:0] 	I_rgb888_data       ,
    
    input               resolution_sel      ,       // 0-720p 1-1080p
    output  wire   	    O_axi_user          ,
    output	wire		O_axi_valid         ,
    output	wire		O_axi_last          ,
    output	wire [95:0]	O_axi_data           
);

parameter X_1080P = 480;    // 1920 / 4 = 480, 4 pixel per clk
parameter Y_1080P = 1080;

reg [$clog2(X_1080P)-1:0]  x_cnt;
reg [$clog2(Y_1080P)-1:0]  y_cnt;

wire    user_720p;
wire    valid_720p;
wire    last_720p;

wire    user_1080p;
wire    valid_1080p;
wire    last_1080p;

reg     I_rgb888_valid_r;

wire I_valid_fall = ~I_rgb888_valid_r & I_rgb888_valid;

assign user_720p = I_rgb888_frame_start ; //(x_cnt == 80 && y_cnt == 180) && valid_720p;
assign valid_720p = (x_cnt >= 80 && x_cnt < 400) && (y_cnt >= 180 && y_cnt < 900) && I_rgb888_valid;
assign last_720p = (x_cnt == (400 - 1) && y_cnt == (900 - 1)) && valid_720p;

assign user_1080p = I_rgb888_frame_start ; //(x_cnt == 0 && y_cnt == 0) && valid_1080p;
assign valid_1080p = I_rgb888_valid;
assign last_1080p = (x_cnt == (X_1080P - 1) && y_cnt == (Y_1080P - 1));

assign O_axi_data = I_rgb888_data;

assign O_axi_user = resolution_sel ? user_1080p : user_720p;
assign O_axi_valid = resolution_sel ? valid_1080p : valid_720p;
assign O_axi_last = resolution_sel ? last_1080p : last_720p;

always@(posedge I_clk or negedge I_rst_n)begin
	if(~I_rst_n)begin
		I_rgb888_valid_r <= 0;
	end
	else begin
		I_rgb888_valid_r <= I_rgb888_valid;
	end	
end

always@(posedge I_clk or negedge I_rst_n)begin
	if(~I_rst_n)begin
		x_cnt <= 0;
	end
	else begin
		if(I_rgb888_valid)begin
			x_cnt <= x_cnt + 1;
		end
		else begin
			x_cnt <= 0;
		end
	end	
end

always@(posedge I_clk or negedge I_rst_n)begin
	if(~I_rst_n)begin
		y_cnt <= 0;
	end
	else begin
		if(I_valid_fall)begin
			y_cnt <= y_cnt + 1;
		end
		else if(I_rgb888_frame_start)begin
			y_cnt <= 0;
		end
	end	
end

endmodule

