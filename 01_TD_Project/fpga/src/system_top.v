

// Cabinet build: camera/ISP/DMA belong to the unused board demonstration.
// Keep the optional legacy generate block available; exclude it by default.
module system_top #(parameter ENABLE_CAMERA=0,ENABLE_EDGE_FEATURES=0,LINK_TEST_MODE=0,CONTROL_BENCH_ENABLE=1)(
    // HDMI interface 
    output [2:0] O_hdmi_tx_p,
    output  O_hdmi_clk_p,
  
    // PS I2C0 EMIO
    inout          SCL0,
    inout          SDA0,


    // Key input
//    inout    [3:0] key,
    // LED output
    output   [2:0] led,
    
	input  wire		    I_clk_hs_p  ,
	input  wire	[3:0]	I_data_hs_p , 
	input  wire	[3:0]	I_data_lp_p ,
	input  wire	[3:0]	I_data_lp_n ,

    output wire         O_imx334_clk_24m   ,
    output              O_imax334_rst_n

    //==============================================================
    // M1 merge: acquisition subsystem (subsys_acq) ports (v0.6.1)
    // 100MHz independent clock domain, zero interaction with the
    // video/NPU domain inside design_0 (no CDC path, see
    // README_HDMI.md 3.1). Pin assignment: constraint/top_merge.adc
    //==============================================================
    ,
    input  wire I_sysclk,          // 100MHz onboard oscillator (H16)

    // J12 GPIO header -- SPI sensor bus (ICM-20602 x2, Mode0)
    output wire O_spi_sclk,
    output wire O_spi_mosi,
    input  wire I_spi_miso,
    output wire O_cs_icm_a,
    output wire O_cs_icm_b,

    // J12 -- AD7606 serial interface (12.5MHz SCLK, DOUTA single-wire)
    output wire O_adc_convst,
    output wire O_adc_sclk,
    output wire O_adc_reset,
    input  wire I_adc_douta,
    output wire O_adc_cs,
    input  wire I_adc_busy,
    input  wire I_adc_frstdata,

    // J12 -- digital sensors / actuators
    inout  wire IO_j12_19_reserved,
    inout  wire IO_temp_core_dq,
    inout  wire IO_i2c_sda_ext,    // AHT20+BMP280 I2C SDA (0x38/0x76)
    inout  wire IO_i2c_scl_ext,    // AHT20+BMP280 I2C SCL
    input  wire I_fan_fg,          // fan FG (ext 10k pullup)
    inout wire IO_j12_22_reserved,
    output wire O_fan_pwm,         // fan PWM 20kHz
    output wire O_buzzer_en,       // Y13: active-low buzzer, high means silent
    output wire O_led_grn,         // external green LED = init_done
    output wire O_led_red,         // external red LED  = alarm

    // Onboard fixed resources
    output wire O_rs485_tx,        // RS485 (idle: TX=1, DE=0)
    input  wire I_rs485_rx,
    output wire O_rs485_de,
    output wire O_led3_hb,         // heartbeat 1Hz (J15)
    output wire O_led4_alm,        // alarm (M20)
    input  wire I_key1,            // leased local manual duty
    input  wire I_key2,            // local silence/reset/maintenance
    output wire O_pl_uart_tx,      // PL debug UART 115200 (dbg_uart frames)
    input  wire I_pl_uart_rx,
    inout  wire IO_iic_sda,        // onboard EEPROM/RTC I2C (released)
    inout  wire IO_iic_scl
 );
	
    parameter  AXI_ADDR_WIDTH = 33 ;
	parameter  AXI_DATA_WIDTH = 256  ;
    parameter    X_SIZE = 1920 ;
    parameter    Y_SIZE = 1080 ;


    
    /**********************************************************
            Signals Definition Connected to PS
    **********************************************************/
 

    wire       [32:0] slave_hp0_axi_awaddr ;
    wire        [1:0] slave_hp0_axi_awburst ;
    wire        [3:0] slave_hp0_axi_awcache ;
    wire        [5:0] slave_hp0_axi_awid ;
    wire        [3:0] slave_hp0_axi_awlen ;
    wire              slave_hp0_axi_awlock ;
    wire        [2:0] slave_hp0_axi_awprot ;
    wire        [3:0] slave_hp0_axi_awqos ;
    wire        [1:0] slave_hp0_axi_awsize ;
    wire              slave_hp0_axi_awvalid ;
    wire              slave_hp0_axi_awready;
    
    wire              slave_hp0_axi_bready ;
    wire        [5:0] slave_hp0_axi_bid ;
    wire        [1:0] slave_hp0_axi_bresp ;
    wire              slave_hp0_axi_bvalid ;
    
    wire       [63:0] slave_hp0_axi_wdata ;
    wire              slave_hp0_axi_wlast ;
    wire        [7:0] slave_hp0_axi_wstrb ;
    wire              slave_hp0_axi_wvalid ;
    wire              slave_hp0_axi_wready;

    wire              f2p_irq ;
    wire       [63:0] pl_gpio_in ;
    wire              i2c0_scl_in ;
    wire              i2c0_sda_in ;
    wire              i2c1_scl_in ;
    wire              i2c1_sda_in ;


    wire              pll_clk_150 ;//synthesis keep;
    wire              pll_clk_150_lock ;
    wire              pll_clk_150_aresetn ;
    
    wire       [63:0] pl_gpio_oe ;
    wire       [63:0] pl_gpio_out ;
	
    wire    [7:0]   mipi_diag_level_bursts;
   
    wire lock_pl ;
    
    
wire    [31:0]                            camera_base_addr; 
wire                                      camera_start; 
wire                                      camera_clear; 


wire p2f_clk0_50m;

    /**********************************************************
                        PS 
    **********************************************************/
    // EDGE_LINK_TOP_BEGIN
    wire edge_clk,edge_rst_n;
    wire [15:0] edge_awaddr;
    wire edge_awvalid;
    wire edge_awready;
    wire [31:0] edge_wdata;
    wire [3:0] edge_wstrb;
    wire edge_wvalid;
    wire edge_wready;
    wire [1:0] edge_bresp;
    wire edge_bvalid;
    wire edge_bready;
    wire [15:0] edge_araddr;
    wire edge_arvalid;
    wire edge_arready;
    wire [31:0] edge_rdata;
    wire [1:0] edge_rresp;
    wire edge_rvalid;
    wire edge_rready;
    design_0  design_0_inst (
        // hp0 aw 
        .hp1_w_us1_awaddr (slave_hp0_axi_awaddr ),
        .hp1_w_us1_awburst (slave_hp0_axi_awburst ),
        .hp1_w_us1_awcache (slave_hp0_axi_awcache ),
        .hp1_w_us1_awid (slave_hp0_axi_awid ),
        .hp1_w_us1_awlen (slave_hp0_axi_awlen ),
        .hp1_w_us1_awlock (slave_hp0_axi_awlock ),
        .hp1_w_us1_awprot (slave_hp0_axi_awprot ),
        .hp1_w_us1_awqos (slave_hp0_axi_awqos ),
        .hp1_w_us1_awsize (slave_hp0_axi_awsize ),
        .hp1_w_us1_awvalid (slave_hp0_axi_awvalid ),
        .hp1_w_us1_awready (slave_hp0_axi_awready ),
        // hp0 w
        .hp1_w_us1_wdata (slave_hp0_axi_wdata ),
        .hp1_w_us1_wlast (slave_hp0_axi_wlast ),
        .hp1_w_us1_wstrb (slave_hp0_axi_wstrb ),
        .hp1_w_us1_wvalid (slave_hp0_axi_wvalid ),
        .hp1_w_us1_wready (slave_hp0_axi_wready ),
        // hp0 b
        .hp1_w_us1_bid (slave_hp0_axi_bid ),
        .hp1_w_us1_bresp (slave_hp0_axi_bresp ),
        .hp1_w_us1_bvalid (slave_hp0_axi_bvalid ),
        .hp1_w_us1_bready (slave_hp0_axi_bready ),
        
        .f2p_irq (f2p_irq ),
        
        
        // iic0 and iic1
        .mipi_iic_i2c0_scl_io(SCL0),
        .mipi_iic_i2c0_sda_io(SDA0),
     
    
        // pl gpio
    
        
        // hdmi
        
        .O_hdmi_tx_p(O_hdmi_tx_p),
        .O_hdmi_clk_p(O_hdmi_clk_p),


        .clk_150m(pll_clk_150), 
        .p2f_clk0_50m(p2f_clk0_50m),
        .rstn_150m(pll_clk_150_aresetn), 
 
        
        // pwm output
        .pwm_out(led[0]),
        .vtg_lock                 (led[1] ), 
        .axis_to_video_lock       (led[2]),
        
        // 
        .camera_base_addr(camera_base_addr), 
        .camera_start(camera_start), 
        .camera_clear(camera_clear)

    ,
        .edge_clk(edge_clk),
        .edge_rst_n(edge_rst_n),
        .edge_awaddr(edge_awaddr),
        .edge_awvalid(edge_awvalid),
        .edge_awready(edge_awready),
        .edge_wdata(edge_wdata),
        .edge_wstrb(edge_wstrb),
        .edge_wvalid(edge_wvalid),
        .edge_wready(edge_wready),
        .edge_bresp(edge_bresp),
        .edge_bvalid(edge_bvalid),
        .edge_bready(edge_bready),
        .edge_araddr(edge_araddr),
        .edge_arvalid(edge_arvalid),
        .edge_arready(edge_arready),
        .edge_rdata(edge_rdata),
        .edge_rresp(edge_rresp),
        .edge_rvalid(edge_rvalid),
        .edge_rready(edge_rready)
);


    generate if(ENABLE_CAMERA)begin:g_camera
    // PLIO IO
//    assign pl_gpio_in[0] = key[0];
//    assign pl_gpio_in[1] = key[1];
//    assign pl_gpio_in[2] = key[2];
//    assign pl_gpio_in[3] = key[3];
//    assign key[0] = pl_gpio_oe[0] ? pl_gpio_out[0] : 1'bz;
//    assign key[1] = pl_gpio_oe[1] ? pl_gpio_out[1] : 1'bz;
//    assign key[2] = pl_gpio_oe[2] ? pl_gpio_out[2] : 1'bz;
//    assign key[3] = pl_gpio_oe[3] ? pl_gpio_out[3] : 1'bz;

    // SMA connector
    assign J10 = 'd0;
    assign J11 = 'd0;


    /**********************************************************
            ADI VDMA ( Connected to MIPI )
    **********************************************************/
    wire	[95:0]	m_axis_tdata		;//synthesis keep;
    wire			m_axis_tuser		;//synthesis keep;
    wire			m_axis_tlast		;//synthesis keep;
    wire			m_axis_tvalid		;//synthesis keep;
    wire			m_axis_tready		;//synthesis keep;
    //wire    [7:0]   mipi_diag_level_bursts;
    /**********************************************************
            MIPI INPUT
    **********************************************************/
	
	wire ud_wclk;//synthesis keep
	wire ud_wvs;//synthesis keep
	wire ud_wde;//synthesis keep
	//wire [256-1:0] ud_wdata;//synthesis keep
    wire [128-1:0] ud_wdata;
	
	wire        S_vi_256b_frame_start;   
    wire        S_vi_256b_valid;        
    wire[255:0] S_vi_256b_data;  
    
	
	
    wire            S_hs_rx_clk    ;
    wire            S_pll_lock     ;
    wire            S_axi_user     ;
    wire            S_axi_valid    ;
    wire            S_axi_last     ;
    wire   [127:0]  S_axi_data     ;
	
	wire   [ 127:0] S_ISP_O_tdata ;
    wire         	S_ISP_O_tlast ;
    wire  			S_ISP_O_tuser ;
    wire         	S_ISP_O_tvalid;
	
	assign ud_wclk   = S_hs_rx_clk;
	assign ud_wvs    = S_ISP_O_tuser ; 
	assign ud_wde    = S_ISP_O_tvalid ; 
	assign ud_wdata  = S_ISP_O_tdata; //{{8'd0, O_axi_data[8-1:0],O_axi_data[16-1:8],O_axi_data[23:16]}, {8'd0, O_axi_data[32-1:24],O_axi_data[40-1:32],O_axi_data[47:40]}, {8'd0, O_axi_data[56-1:48],O_axi_data[64-1:56],O_axi_data[71:64]}, {8'd0, O_axi_data[80-1:72],O_axi_data[88-1:80],O_axi_data[95:88]}} ;  //{{8'd0, O_axi_data[23:0]}, {8'd0, O_axi_data[47:24]}, {8'd0, O_axi_data[71:48]}, {8'd0, O_axi_data[95:72]}} ; //S_vi_256b_data ; //{S_vi_256b_data[96*1-1:96*0],S_vi_256b_data[96*2-1:96*1],S_vi_256b_data[96*3-1:96*2]，S_vi_256b_data[96*4-1:96*3]}; //synthesis keep
	
    wire    [3:0]   S_lane_error    ;

    reg [7:0] cnt_error = 0;
    always@(posedge S_hs_rx_clk)begin
        if(S_lane_error != 4'b0000)
            cnt_error <= cnt_error + 1;
    end

//    assign led[7:3] = cnt_error[4:0];
	assign O_imax334_rst_n = 1'b1;
	wire S_hs_rstn ;
	
  //isp_top u_isp_top (
	//.axi4s_video_aclk(S_hs_rx_clk),
	//.I_rst_n         (S_pll_lock),
	//.I_tlast         (S_axi_last ),
	//.I_tuser         (S_axi_user ),
	//.I_tdata         (S_axi_data ),
	//.I_tvalid        (S_axi_valid),
	//.O_tdata         (S_ISP_O_tdata ),
	//.O_tlast         (S_ISP_O_tlast ),
	//.O_tuser         (S_ISP_O_tuser ),
	//.O_tvalid        (S_ISP_O_tvalid)
  //);
	
    design_top_wrapper  design_top_wrapper_u
    (
    .I_sys_clk_156m     (p2f_clk0_50m     ),
	//.I_clk_hs_p         (I_clk_hs_p         ),
    //.I_clk_lp_p			(I_clk_lp_p			),
	//.I_data_hs_p        (I_data_hs_p        ), 
    //.I_data_lp_p        (I_data_lp_p        ),
    //.I_data_lp_n        (I_data_lp_n        ), 
    //.I_csi_lp_ck_dir	(I_csi_lp_ck_dir	),    
	//.I_csi_lp_d0_dir    (I_csi_lp_d0_dir    ),
    //.I_csi_lp_d1_dir    (I_csi_lp_d1_dir    ),
	//.I_csi_lp_d2_dir    (I_csi_lp_d2_dir    ),
    //.I_csi_lp_d3_dir    (I_csi_lp_d3_dir    ),    	    
	.O_imx334_clk_24m   (O_imx334_clk_24m   ),
	.I_clk_hs_p     	(I_clk_hs_p     ),
	.I_data_hs_p    	(I_data_hs_p    ),
	.I_data_lp_p    	(I_data_lp_p    ),
	.I_data_lp_n    	(I_data_lp_n    ),

    .S_lane_error       (S_lane_error   ),
    .S_hs_rx_clk        (S_hs_rx_clk    ),
	.S_pll_lock			(S_pll_lock		),
    .O_ISP_tdata        (S_ISP_O_tdata     ),
    .O_ISP_tlast        (S_ISP_O_tlast     ),
    .O_ISP_tuser        (S_ISP_O_tuser     ),
    .O_ISP_tvalid       (S_ISP_O_tvalid    )
    );
	
	/*data_96bit_to_256bit u_data_96bit_to_256bit(
	.I_clk                ( S_hs_rx_clk           ),
	.I_rst_n              ( S_hs_rstn                ),
	
	.I_96b_frame_start    ( O_axi_user     ),
	.I_96b_valid          ( O_axi_valid           ),
	.I_96b_data           ( {O_axi_data[24*1-1:24*0],O_axi_data[24*2-1:24*1],O_axi_data[24*3-1:24*2],O_axi_data[24*4-1:24*3]}            ),
	
	.O_256b_frame_start  ( S_vi_256b_frame_start ),
	.O_256b_valid         ( S_vi_256b_valid       ),
	.O_256b_data          ( S_vi_256b_data        )
	);*/
	
	wire [AXI_ADDR_WIDTH-1:  0]      fdma_waddr;   
	wire                             fdma_wareq;   
	wire [15: 0]                     fdma_wsize;                                 
	wire                             fdma_wbusy;   		
	wire [AXI_DATA_WIDTH/4-1 : 0]      fdma_wdata; 
	wire                             fdma_wvalid;  
	wire                             fdma_wready;  
	
	wire [AXI_ADDR_WIDTH-1:  0]      fdma_raddr;   
	wire                             fdma_rareq;   
	wire [15: 0]                     fdma_rsize;                                 
	wire                             fdma_rbusy;   			
	wire [AXI_DATA_WIDTH/4-1 : 0]      fdma_rdata; 
	wire                             fdma_rvalid;  
	wire                             fdma_rready;  
	wire wbuf_sync ;

	
	
	uidbuf_write# (
	.VIDEO_ENABLE(1'b1),  
	.ENABLE_WRITE(1'b1), 
	.ENABLE_READ(1'b1), 
	.AXI_DATA_WIDTH(AXI_DATA_WIDTH/4),
	.AXI_ADDR_WIDTH(AXI_ADDR_WIDTH),
	
	.W_BUFDEPTH(1024*4),
	.W_DATAWIDTH(128),//(256),//96->256
	//.W_BASEADDR(BASEADDR),
	.W_DSIZEBITS(25),
	/*.W_XSIZE(180),
	.W_XSTRIDE(180),
	.W_YSIZE(1080),*/
	.W_XDIV(1),
	//.W_BUFSIZE(BUFSIZE),
	
	.W_XSIZE(X_SIZE/(128/32)),//(120),
	.W_XSTRIDE(X_SIZE/(128/32)),//(120),
	.W_YSIZE(Y_SIZE)
	
	)
	uidbuf_write_u0
	(
	.W_BASEADDR({1'b0,camera_base_addr}),
	//.W_DSIZEBITS(DSIZEBITS),
	.W_BUFSIZE(6),
	
	.I_ui_clk(pll_clk_150),
	.I_ui_rstn(pll_clk_150_aresetn),
	
	.I_W_FS(ud_wvs),
	.I_W_clk(ud_wclk),
	.I_W_wren(ud_wde),
	.I_W_data(ud_wdata), 
	.O_W_sync_cnt(wbuf_sync),
	.I_W_buf(wbuf_sync),
	.O_W_full(),
	
		
	.O_fdma_waddr(fdma_waddr)  ,
	.O_fdma_wareq(fdma_wareq)  ,
	.O_fdma_wsize(fdma_wsize)  ,                                     
	.I_fdma_wbusy(fdma_wbusy)  ,			
	.O_fdma_wdata(fdma_wdata)	 ,
	.I_fdma_wvalid(fdma_wvalid),
	.O_fdma_wready(fdma_wready),
	.O_fmda_wbuf  (fdma_wbuf),	
	.O_fdma_wirq  (fdma_wirq),	
	
	.camera_start       ( camera_start ),
	.camera_done        ( f2p_irq       ),
	.camera_clear_intr  ( camera_clear)
	); 
	
	uiFDMA#
	(
	.M_AXI_ID_WIDTH(6)           ,//ID位宽
	.M_AXI_ADDR_WIDTH(AXI_ADDR_WIDTH)		,//内存地址位宽
	.M_AXI_DATA_WIDTH(AXI_DATA_WIDTH/4)		,//AXI总线的数据位宽
	.M_AXI_MAX_BURST_LEN (16)                //AXI总线的burst 大小，对于AXI4，支持任意长度，对于AXI3以下最大16
	)
	uiFDMA_inst
	(
	.I_fdma_waddr(fdma_waddr)          ,//FDMA写通道地址
	.I_fdma_wareq(fdma_wareq)          ,//FDMA写通道请求
	.I_fdma_wsize(fdma_wsize)          ,//FDMA写通道一次FDMA的传输大小                                            
	.O_fdma_wbusy(fdma_wbusy)          ,//FDMA处于BUSY状态，AXI总线正在写操作  
					
	.I_fdma_wdata(fdma_wdata)		    ,//FDMA写数据
	.O_fdma_wvalid(fdma_wvalid)        ,//FDMA 写有效
	.I_fdma_wready(1'b1)		       ,//FDMA写准备好，用户可以写数据
	
	.I_fdma_raddr(fdma_raddr)          ,// FDMA读通道地址
	.I_fdma_rareq(fdma_rareq)          ,// FDMA读通道请求
	.I_fdma_rsize(fdma_rsize)          ,// FDMA读通道一次FDMA的传输大小                                      
	.O_fdma_rbusy(fdma_rbusy)          ,// FDMA处于BUSY状态，AXI总线正在读操作 
					
	.O_fdma_rdata(fdma_rdata)		    ,// FDMA读数据
	.O_fdma_rvalid(fdma_rvalid)        ,// FDMA 读有效
	.I_fdma_rready(1'b1)		    ,// FDMA读准备好，用户可以读数据
	
	//以下为AXI总线信号		
	.M_AXI_ACLK                             (pll_clk_150),
	.M_AXI_ARESETN                          (pll_clk_150_aresetn),
	// Master Interface Write Address Ports
	
	.M_AXI_AWID                             (slave_hp0_axi_awid),
	.M_AXI_AWADDR                           (slave_hp0_axi_awaddr),
	.M_AXI_AWLEN                            (slave_hp0_axi_awlen),
	.M_AXI_AWSIZE                           (slave_hp0_axi_awsize),
	.M_AXI_AWBURST                          (slave_hp0_axi_awburst),
	.M_AXI_AWLOCK                           (slave_hp0_axi_awlock),
	.M_AXI_AWCACHE                          (slave_hp0_axi_awcache),
	.M_AXI_AWPROT                           (slave_hp0_axi_awprot),
	.M_AXI_AWQOS                            (),
	.M_AXI_AWVALID                          (slave_hp0_axi_awvalid),
	.M_AXI_AWREADY                          (slave_hp0_axi_awready),
	// Master Interface Write Data Ports
	.M_AXI_WDATA                            (slave_hp0_axi_wdata),
	.M_AXI_WSTRB                            (slave_hp0_axi_wstrb),
	.M_AXI_WLAST                            (slave_hp0_axi_wlast),
	.M_AXI_WVALID                           (slave_hp0_axi_wvalid),
	.M_AXI_WREADY                           (slave_hp0_axi_wready),
	
	// Master Interface Write Response Ports
	.M_AXI_BID                              (slave_hp0_axi_bid),
	.M_AXI_BRESP                            (slave_hp0_axi_bresp),
	.M_AXI_BVALID                           (slave_hp0_axi_bvalid),
	.M_AXI_BREADY                           (slave_hp0_axi_bready)
	
//	// Master Interface Read Address Ports
//	.M_AXI_ARID                             (slave_hp0_axi_arid),
//	.M_AXI_ARADDR                           (slave_hp0_axi_araddr),
//	.M_AXI_ARLEN                            (slave_hp0_axi_arlen),
//	.M_AXI_ARSIZE                           (slave_hp0_axi_arsize),
//	.M_AXI_ARBURST                          (slave_hp0_axi_arburst),
//	.M_AXI_ARLOCK                           (slave_hp0_axi_arlock),
//	.M_AXI_ARCACHE                          (slave_hp0_axi_arcache),
//	.M_AXI_ARPROT                           (slave_hp0_axi_arprot),
//	.M_AXI_ARQOS                            (),
//	.M_AXI_ARVALID                          (slave_hp0_axi_arvalid),
//	.M_AXI_ARREADY                          (slave_hp0_axi_arready),
//	// Master Interface Read Data Ports
//	.M_AXI_RID                              (slave_hp0_axi_rid),
//	.M_AXI_RDATA                            (slave_hp0_axi_rdata),
//	.M_AXI_RRESP                            (slave_hp0_axi_rresp),
//	.M_AXI_RLAST                            (slave_hp0_axi_rlast),
//	.M_AXI_RVALID                           (slave_hp0_axi_rvalid),
//	.M_AXI_RREADY                           (slave_hp0_axi_rready)
	
	
	);



    /**********************************************************
            M1 merge: Acquisition subsystem (subsys_acq, v0.6.1)
            - 100MHz independent clock domain (I_sysclk = H16)
            - zero interaction with design_0 / MIPI chain / uiFDMA
              (data leaves the chip via dbg_uart + status LEDs only)
            - LED1(T19)/LED2(R19) are used by the demo status lights
              (led[0]=pwm, led[1]=vtg_lock); LED3(J15)+LED4(M20) and
              the J12 header LEDs belong to this subsystem
            - source: src/acq/subsys_acq.v + 9 module files (copied
              unchanged from FU_Code/Code/rtl, v0.6.1)
    **********************************************************/
    end else begin:g_no_camera
        assign slave_hp0_axi_awaddr=0;assign slave_hp0_axi_awburst=0;assign slave_hp0_axi_awcache=0;
        assign slave_hp0_axi_awid=0;assign slave_hp0_axi_awlen=0;assign slave_hp0_axi_awlock=0;
        assign slave_hp0_axi_awprot=0;assign slave_hp0_axi_awqos=0;assign slave_hp0_axi_awsize=0;assign slave_hp0_axi_awvalid=0;
        assign slave_hp0_axi_wdata=0;assign slave_hp0_axi_wlast=0;assign slave_hp0_axi_wstrb=0;assign slave_hp0_axi_wvalid=0;assign slave_hp0_axi_bready=1;
        assign f2p_irq=0;assign O_imx334_clk_24m=0;assign O_imax334_rst_n=0;
    end endgenerate
    // The alarm logic uses 1 for an audible request. The fitted buzzer module
    // is low-level triggered: invert only at the physical output boundary.
    // alarm_outputs resets its request to 0, keeping Y13 high during reset.
    wire buzzer_active_high;
    assign O_buzzer_en = ~buzzer_active_high;
    subsys_acq #(.ENABLE_PS_LINK(1),.ENABLE_FEATURES(ENABLE_EDGE_FEATURES),.LINK_TEST_MODE(LINK_TEST_MODE),.CONTROL_BENCH_ENABLE(LINK_TEST_MODE ? 0:CONTROL_BENCH_ENABLE)) u_subsys_acq (
        .I_sysclk       (I_sysclk),

        // SPI sensor bus (ICM-20602 x2)
        .O_spi_sclk     (O_spi_sclk),
        .O_spi_mosi     (O_spi_mosi),
        .I_spi_miso     (I_spi_miso),
        .O_cs_icm_a     (O_cs_icm_a),
        .O_cs_icm_b     (O_cs_icm_b),

        // AD7606 serial interface
        .O_adc_convst   (O_adc_convst),
        .O_adc_sclk     (O_adc_sclk),
        .O_adc_reset    (O_adc_reset),
        .I_adc_douta    (I_adc_douta),
        .O_adc_cs       (O_adc_cs),
        .I_adc_busy     (I_adc_busy),
        .I_adc_frstdata (I_adc_frstdata),

        // Digital sensors / actuators
        .IO_j12_19_reserved(IO_j12_19_reserved),
        .IO_temp_core_dq(IO_temp_core_dq),
        .IO_i2c_sda_ext (IO_i2c_sda_ext),
        .IO_i2c_scl_ext (IO_i2c_scl_ext),
        .I_fan_fg       (I_fan_fg),
        .IO_j12_22_reserved(IO_j12_22_reserved),
        .O_fan_pwm      (O_fan_pwm),
        .O_buzzer_en    (buzzer_active_high),
        .O_led_grn      (O_led_grn),
        .O_led_red      (O_led_red),

        // Onboard fixed resources
        .O_rs485_tx     (O_rs485_tx),
        .I_rs485_rx     (I_rs485_rx),
        .O_rs485_de     (O_rs485_de),
        .O_led3_hb      (O_led3_hb),
        .O_led4_alm     (O_led4_alm),
        .I_key1         (I_key1),
        .I_key2         (I_key2),
        .O_pl_uart_tx   (O_pl_uart_tx),
        .I_pl_uart_rx   (I_pl_uart_rx),
        .IO_iic_sda     (IO_iic_sda),
        .IO_iic_scl     (IO_iic_scl)
    ,
        .edge_clk(edge_clk),
        .edge_rst_n(edge_rst_n),
        .edge_awaddr(edge_awaddr),
        .edge_awvalid(edge_awvalid),
        .edge_awready(edge_awready),
        .edge_wdata(edge_wdata),
        .edge_wstrb(edge_wstrb),
        .edge_wvalid(edge_wvalid),
        .edge_wready(edge_wready),
        .edge_bresp(edge_bresp),
        .edge_bvalid(edge_bvalid),
        .edge_bready(edge_bready),
        .edge_araddr(edge_araddr),
        .edge_arvalid(edge_arvalid),
        .edge_arready(edge_arready),
        .edge_rdata(edge_rdata),
        .edge_rresp(edge_rresp),
        .edge_rvalid(edge_rvalid),
        .edge_rready(edge_rready)
);


endmodule
