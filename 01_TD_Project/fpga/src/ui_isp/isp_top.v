module isp_top (
    input axi4s_video_aclk,
    input I_rst_n,
    input I_tlast,
    input I_tuser,
    input [39:0] I_tdata,
    input I_tvalid,
    input [9:0] I_tdest,
    input O_tready,
    output [127:0] O_tdata,
    output O_tlast,
    output O_tuser,
    output O_tvalid,
    output I_tready
);

//   wire         axi4s_video_aclk;
//   wire         I_rst_n;  //synthesis keep 
//   wire         I_tlast;  //synthesis keep 
//   wire         I_tuser;  //synthesis keep 
//   wire [ 39:0] I_tdata;  //synthesis keep 
//   wire         I_tvalid;  //synthesis keep 
//   wire [  9:0] I_tdest;  //synthesis keep 
//   wire         O_tready;  //synthesis keep 
//   wire [127:0] O_tdata;  //synthesis keep 
//   wire         O_tlast;  //synthesis keep 
//   wire         O_tuser;  //synthesis keep 
//   wire         O_tvalid;  //synthesis keep 
//   wire         I_tready;  //synthesis keep 


  wire         BLC_O_tlast;  //synthesis keep 
  wire         BLC_O_tuser;  //synthesis keep 
  wire [ 39:0] BLC_O_tdata;  //synthesis keep 
  wire         BLC_O_tvalid;  //synthesis keep 
  wire [  9:0] BLC_O_tdest;  //synthesis keep 
  wire         BLC_O_tready;  //synthesis keep 

  wire         m_aixs_tvalid;  //synthesis keep 
  wire [127:0] m_aixs_tdata;  //synthesis keep 
  wire         m_aixs_tuser;  //synthesis keep 
  wire         m_aixs_tlast;  //synthesis keep 
  wire         m_aixs_tready;  //synthesis keep 
  wire [ 95:0] m_aixs_tdata_96;

  wire         awb_O_tlast;  //synthesis keep 
  wire         awb_O_tuser;  //synthesis keep 
  wire [ 95:0] awb_O_tdata;  //synthesis keep 
  wire         awb_O_tvalid;  //synthesis keep 
  wire         awb_O_tready;  //synthesis keep 

  wire         gamma_O_tlast;  //synthesis keep 
  wire         gamma_O_tuser;  //synthesis keep 
  wire [ 95:0] gamma_O_tdata;  //synthesis keep 
  wire         gamma_O_tvalid;  //synthesis keep 
  wire         gamma_O_tready;  //synthesis keep 

  wire         cut_O_tlast;
  wire         cut_O_tuser;
  wire [ 95:0] cut_O_tdata;
  wire         cut_O_tvalid;
  wire         cut_O_tready;

  wire         contrast_O_tlast;
  wire         contrast_O_tuser;
  wire [ 95:0] contrast_O_tdata;
  wire         contrast_O_tvalid;
  wire         contrast_O_tready;

  wire         Brightness_O_tlast;
  wire         Brightness_O_tuser;
  wire [ 95:0] Brightness_O_tdata;
  wire         Brightness_O_tvalid;
  wire         Brightness_O_tready;

  wire         Saturation_O_tlast;
  wire         Saturation_O_tuser;
  wire [ 95:0] Saturation_O_tdata;
  wire         Saturation_O_tvalid;
  wire         Saturation_O_tready;

  wire [127:0] Brightness_O_tdata_128;  //synthesis keep 

  assign Brightness_O_tready = O_tready;
  assign O_tdata  = Brightness_O_tdata_128;
  assign O_tlast  = Brightness_O_tlast    ;
  assign O_tuser  = I_tuser    ;//此处直接把输出的tuser等于输入的tuser
  assign O_tvalid = Brightness_O_tvalid   ;

   //assign awb_O_tready = O_tready;
   //assign O_tdata  = awb_O_tdata_128;
   //assign O_tlast  = awb_O_tlast    ;
   //assign O_tuser  = awb_O_tuser    ;
   //assign O_tvalid = awb_O_tvalid   ;

   //assign m_aixs_tready = O_tready     ;
   //assign O_tdata       = m_aixs_tdata_r ;
   //assign O_tlast       = m_aixs_tlast ;
   //assign O_tuser       = m_aixs_tuser ;//此处直接把输出的tuser等于输入的tuser
   //assign O_tvalid      = m_aixs_tvalid;
  ////由于安路的行间距问题，后续的tuser全都不再同步，再后续的算法中，把它近似为vs，也就是帧同步信号，全部用最初始的I_tuser代替
  BLC #(
      .Black_level_offset_r0(50),
      .Black_level_offset_r1(50),
      .Black_level_offset_r2(50),
      .Black_level_offset_r3(50)
  ) u_BLC (
      .I_clk   (axi4s_video_aclk),
      .I_rst_n (I_rst_n),
      .I_tlast (I_tlast),
      .I_tuser (I_tuser),
      .I_tdata (I_tdata),
      .I_tvalid(I_tvalid),
      .I_tdest (I_tdest),
      .I_tready(),

      .O_tlast (BLC_O_tlast),
      .O_tuser (BLC_O_tuser),
      .O_tdata (BLC_O_tdata),
      .O_tvalid(BLC_O_tvalid),
      .O_tdest (BLC_O_tdest),
      .O_tready(BLC_O_tready)
  );

demosaic #(
    .IMG_HEIGHT          (1080),  // 图像高度
    .IMG_WIDTH           (1920),   // 图像宽度
    .data_complete_delay (50  ),
    .BAYER_MODE          ("RGGB")
)
u_demosaic
(
    .I_clk   			(axi4s_video_aclk)	,   // 时钟信号
    .I_rst_n 			(I_rst_n)	,   // 复位信号，低有效
    .axi4s_video_tdata 	(BLC_O_tdata)	,  // AXI4-Stream视频数据
    .axi4s_video_tdest 	(BLC_O_tdest)	,
    .axi4s_video_tlast 	(BLC_O_tlast)	,  // 行结束信号
    .axi4s_video_tvalid	(BLC_O_tvalid)	,  // 数据有效信号
    .axi4s_video_tuser 	(BLC_O_tuser)	,  // 帧开始信号
    .axi4s_video_tready	(BLC_O_tready)	,  // 从模块准备好接受数据
    .O_tlast  			(m_aixs_tlast)	,  // 输出行结束信号
    .O_tuser  			(m_aixs_tuser)	,  // 输出帧开始信号
    .O_tdata  			(m_aixs_tdata)	,  // 输出数据
    .O_tvalid 			(m_aixs_tvalid)	,  // 输出数据有效信号
    .O_tready   		(m_aixs_tready)	   // 输出数据准备好信号
);

data128_96 u_data128_96 (
    .I_tdata(m_aixs_tdata),
    .O_tdata(m_aixs_tdata_96)
);
	
    awb #(
        .IMG_HEIGHT(1080),
        .IMG_WIDTH (1920)
    ) u_awb (
        .I_clk   (axi4s_video_aclk),
        .I_rst_n (I_rst_n),
        .I_tlast (m_aixs_tlast),
        .I_tuser (m_aixs_tuser),
        .I_tdata (m_aixs_tdata_96),
        .I_tvalid(m_aixs_tvalid),
        .I_tready(m_aixs_tready),
        .O_tlast (awb_O_tlast ),
        .O_tuser (awb_O_tuser ),
        .O_tdata (awb_O_tdata ),
        .O_tvalid(awb_O_tvalid),
        .O_tready(awb_O_tready)
    );
	
    image_cut #(
        .IMG_WIDTH(1920),
        .IMG_HEIGHT(1080),
        .DATA_WIDTH(96),
        .SKIP_ROWS_top(0),
        .SKIP_ROWS_bottom(0),
        .SKIP_COLS_left(1),
        .SKIP_COLS_right(0)
    ) u_image_cut (
        .I_clk   (axi4s_video_aclk),
        .I_rst_n (I_rst_n),
        .I_tlast (awb_O_tlast),
        .I_tuser (awb_O_tuser),
        .I_tdata (awb_O_tdata),
        .I_tvalid(awb_O_tvalid),
        .I_tready(awb_O_tready),
        .O_tlast (cut_O_tlast),
        .O_tuser (cut_O_tuser),
        .O_tdata (cut_O_tdata),
        .O_tvalid(cut_O_tvalid),
        .O_tready(cut_O_tready)
    );
	
    gamma #(
        .GAMMA_10x(22)
    ) u_gamma (
        .I_clk   (axi4s_video_aclk),
        .I_rst_n (I_rst_n),
        .I_tlast (cut_O_tlast),
        .I_tuser (cut_O_tuser),
        .I_tdata (cut_O_tdata),
        .I_tvalid(cut_O_tvalid),
        .I_tready(cut_O_tready),
        .O_tlast (gamma_O_tlast ),
        .O_tuser (gamma_O_tuser ),
        .O_tdata (gamma_O_tdata ),
        .O_tvalid(gamma_O_tvalid),
        .O_tready(gamma_O_tready)
    );
	
	
    Saturation_adj #(
        .ADJUST_VAL(130)
    ) u_Saturation_adj (
        .I_clk   (axi4s_video_aclk),
        .I_rst_n (I_rst_n),
        .I_tlast (gamma_O_tlast      ),
        .I_tuser (gamma_O_tuser      ),
        .I_tdata (gamma_O_tdata      ),
        .I_tvalid(gamma_O_tvalid     ),
        .I_tready(gamma_O_tready     ),
        .O_tlast (Saturation_O_tlast ),
        .O_tuser (Saturation_O_tuser ),
        .O_tdata (Saturation_O_tdata ),
        .O_tvalid(Saturation_O_tvalid),
        .O_tready(Saturation_O_tready)
    );
	
    contrast_adj #(
        .contrast_level(140)  //对比度调节因子，定点数表示，128对应1.0
    ) u_contrast_adj (
        .I_clk   (axi4s_video_aclk),
        .I_rst_n (I_rst_n),
        .I_tlast (Saturation_O_tlast ),
        .I_tuser (Saturation_O_tuser ),
        .I_tdata (Saturation_O_tdata ),
        .I_tvalid(Saturation_O_tvalid),
        .I_tready(Saturation_O_tready),
        .O_tlast (contrast_O_tlast),
        .O_tuser (contrast_O_tuser),
        .O_tdata (contrast_O_tdata),
        .O_tvalid(contrast_O_tvalid),
        .O_tready(contrast_O_tready)
    );
	
    Brightness_adjustment #(
        .BRIGHTNESS_ADD  (5),
        .BRIGHTNESS_MINUS(0)
    ) u_Brightness_adjustment (
        .I_clk   (axi4s_video_aclk),
        .I_rst_n (I_rst_n),
        .I_tlast (contrast_O_tlast),
        .I_tuser (contrast_O_tuser),
        .I_tdata (contrast_O_tdata),
        .I_tvalid(contrast_O_tvalid),
        .I_tready(contrast_O_tready),
        .O_tlast (Brightness_O_tlast ),
        .O_tuser (Brightness_O_tuser ),
        .O_tdata (Brightness_O_tdata ),
        .O_tvalid(Brightness_O_tvalid),
        .O_tready(Brightness_O_tready)
    );
	
	
    data96_128 u_data96_128 (
        .I_tdata(Brightness_O_tdata),
        .O_tdata(Brightness_O_tdata_128)
    );

endmodule
