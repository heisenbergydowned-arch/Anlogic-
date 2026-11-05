
module design_top_wrapper (
    /*
        input 33MHz system clock
    */
    input wire       I_sys_clk_156m,
    
    /*
    	input hs clock
    */
	// input wire		 I_clk_hs_p,
	// input wire		 I_clk_lp_p,
    /*
    	input hs data
    */
	// input wire[3:0]	 I_data_hs_p, 
    // input wire[3:0]	 I_data_lp_p,
    // input wire[3:0]	 I_data_lp_n,   
    /*
    	output CSI LP DIR
    */
    // output wire		I_csi_lp_ck_dir,
	// output wire		I_csi_lp_d0_dir,
    // output wire 	I_csi_lp_d1_dir,
	// output wire		I_csi_lp_d2_dir,
    // output wire 	I_csi_lp_d3_dir,    	    
    /*
        camera imx334 iic configure interface
    */
    // inout wire       IO_imx334_scl,
    // inout wire       IO_imx334_sda,
	
    // output wire[3:0] O_led,
    /*
        camera imx334 24mhz clk
    */
	output wire      O_imx334_clk_24m,
    // output  [4:0]   row_err_cnt,
    //input           proc_en                 ,
    //input           resolution_sel          ,
    //output          [31:0]           gray_mean,
	
	input  wire		    I_clk_hs_p  ,
	input  wire	[3:0]	I_data_hs_p , 
	input  wire	[3:0]	I_data_lp_p ,
	input  wire	[3:0]	I_data_lp_n ,

	output			S_pll_lock,
    output          wire[3:0]	S_lane_error,
    output          S_hs_rx_clk         ,//synthesis keep  
    output  [127:0] O_ISP_tdata         ,//synthesis keep
    output		    O_ISP_tlast         ,//synthesis keep
    output		    O_ISP_tuser         ,//synthesis keep
    output	 		O_ISP_tvalid         //synthesis keep

);

    wire        S_clk_70m;
  //wire        S_hs_rx_clk;           //synthesis keep  
    wire        S_hs_rx_valid;         //synthesis keep  
    wire[31:0]  S_hs_rx_data;          //synthesis keep
	
	wire        S_csi_frame_start;     //synthesis keep  
    wire        S_csi_frame_end;       //synthesis keep  
    wire        S_csi_valid;           //synthesis keep  
    wire[31:0]  S_csi_data;            //synthesis keep
	
	wire          S_raw10_frame_start;//synthesis keep
	wire          S_raw10_frame_end;  //synthesis keep
	wire          S_raw10_valid;      //synthesis keep
	wire [39 : 0] S_raw10_data;       //synthesis keep
	
	wire [39:0]		S_axis_tdata ;//synthesis keep
	wire 			S_axis_tvalid;//synthesis keep  
	wire 			S_axis_tlast; //synthesis keep 
	wire 			S_axis_tuser; //synthesis keep

    assign S_rst = ~S_pll_lock;


	PLL U_PLL(
  		.refclk   ( I_sys_clk_156m         ),
  		.lock     ( S_pll_lock             ),
 
  		.clk0_out ( 					   ),
  		.clk1_out ( 		               ),
        .clk2_out ( S_clk_70m              ),
        .clk3_out ( O_imx334_clk_24m       )
	);

  mipi_dphy_rx_over_lvds_wrapper#(
    .DEVICE           ( "DR1" ),
    .LANE_NUM         ( 4    )
)u_mipi_dphy_rx_over_lvds_wrapper(
    .I_lp_clk         ( S_clk_70m    ),
    .I_rst            ( S_rst   	 ),

    .I_mipi_clk_p     ( I_clk_hs_p   ),
    .I_mipi_data_hs_p ( I_data_hs_p  ),
    .I_mipi_data_lp_p ( I_data_lp_p  ),
    .I_mipi_data_lp_n ( I_data_lp_n  ),

    .I_lane_hs_invert ( 4'b0000      ),
    .I_lane_lp_invert ( 4'b0000      ),

    .O_hs_rx_clk      ( S_hs_rx_clk   ),
    .O_hs_rx_valid    ( S_hs_rx_valid ),
    .O_hs_rx_data     ( S_hs_rx_data  ),

    .O_lp_rx_lane0_p  (),
    .O_lp_rx_lane0_n  (),

    .O_lane_error     ( S_lane_error  )
);


    csi_unpacket u_csi_unpacket(
        .I_clk             ( S_hs_rx_clk       ),
        .I_rst_n           ( ~S_rst            ),

        .I_hs_valid        ( S_hs_rx_valid     ),
        .I_hs_data         ( S_hs_rx_data      ),

        .O_csi_frame_start ( S_csi_frame_start ),
        .O_csi_frame_end   ( S_csi_frame_end   ),
        .O_csi_valid       ( S_csi_valid       ),
        .O_csi_data        ( S_csi_data        )
    );

// 解码RAW10
  raw10_unpacket_4lane u_raw10_unpacket (
	.I_clk  (S_hs_rx_clk),
	.I_rst_n(~S_rst ),
	
	.I_csi_frame_start(S_csi_frame_start),
	.I_csi_frame_end  (S_csi_frame_end),
	.I_csi_valid      (S_csi_valid),
	.I_csi_data       (S_csi_data),
	
	.O_raw10_frame_start(S_raw10_frame_start),
	.O_raw10_frame_end  (S_raw10_frame_end  ),
	.O_raw10_valid      (S_raw10_valid      ),
	.O_raw10_data       (S_raw10_data       )
  );

  image_correction #(
      .DATA_WIDTH  (40),
      .TDEST_WIDTH (10)
  )image_correction
  (
      .I_clk            (S_hs_rx_clk),
      .I_rst_n          (~S_rst ),
  
      .I_raw_data       (S_raw10_data       ),       
      .I_raw_valid      (S_raw10_valid      ),     
      .I_raw_frame_start(S_raw10_frame_start),
      .I_raw_frame_end  (S_raw10_frame_end  ),
      
      .O_raw_tdata (S_axis_tdata ),
      .O_raw_tlast (S_axis_tlast ),
      .O_raw_tdest (           ),
      .O_raw_tvalid(S_axis_tvalid),
      .O_raw_tuser (S_axis_tuser )
  );

  isp_top u_isp_top (
	.axi4s_video_aclk(S_hs_rx_clk),
	.I_rst_n         (~S_rst ),
	.I_tlast         (S_axis_tlast ),
	.I_tuser         (S_axis_tuser ),
	.I_tdata         (S_axis_tdata ),
	.I_tvalid        (S_axis_tvalid),
	.I_tdest         (),
	.O_tready        (O_ISP_tready),
	.O_tdata         (O_ISP_tdata ),
	.O_tlast         (O_ISP_tlast ),
	.O_tuser         (O_ISP_tuser ),
	.O_tvalid        (O_ISP_tvalid),
	.I_tready        ()
  );


endmodule