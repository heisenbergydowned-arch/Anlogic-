/************************************************************\
**	Copyright (c) 2012-2025 anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Gen time	:	2025-11-26 10:54:13
**	DI version	:	174302 2025/09/09
**	TD version	:	6.2.1(build number:175876)
\************************************************************/

module design_0 (
    inout     wire              mipi_iic_i2c0_scl_io ,
    inout     wire              mipi_iic_i2c0_sda_io ,
    input     wire              f2p_irq ,
    input     wire       [31:0] hp1_w_us1_araddr ,
    input     wire        [1:0] hp1_w_us1_arburst ,
    input     wire        [3:0] hp1_w_us1_arcache ,
    input     wire        [4:0] hp1_w_us1_arid ,
    input     wire        [7:0] hp1_w_us1_arlen ,
    input     wire        [0:0] hp1_w_us1_arlock ,
    input     wire        [2:0] hp1_w_us1_arprot ,
    input     wire        [3:0] hp1_w_us1_arqos ,
    input     wire        [2:0] hp1_w_us1_arsize ,
    input     wire              hp1_w_us1_arvalid ,
    input     wire       [31:0] hp1_w_us1_awaddr ,
    input     wire        [1:0] hp1_w_us1_awburst ,
    input     wire        [3:0] hp1_w_us1_awcache ,
    input     wire        [4:0] hp1_w_us1_awid ,
    input     wire        [7:0] hp1_w_us1_awlen ,
    input     wire        [0:0] hp1_w_us1_awlock ,
    input     wire        [2:0] hp1_w_us1_awprot ,
    input     wire        [3:0] hp1_w_us1_awqos ,
    input     wire        [2:0] hp1_w_us1_awsize ,
    input     wire              hp1_w_us1_awvalid ,
    input     wire              hp1_w_us1_bready ,
    input     wire              hp1_w_us1_rready ,
    input     wire       [63:0] hp1_w_us1_wdata ,
    input     wire              hp1_w_us1_wlast ,
    input     wire        [7:0] hp1_w_us1_wstrb ,
    input     wire              hp1_w_us1_wvalid ,
    output    wire              clk_150m ,
    output    wire              rstn_150m ,
    output    wire              pwm_out ,
    output    wire       [31:0] camera_base_addr ,
    output    wire              camera_start ,
    output    wire              camera_clear ,
    output    wire              vtg_lock ,
    output    wire              axis_to_video_lock ,
    output    wire              hp1_w_us1_arready ,
    output    wire              hp1_w_us1_awready ,
    output    wire        [4:0] hp1_w_us1_bid ,
    output    wire        [1:0] hp1_w_us1_bresp ,
    output    wire              hp1_w_us1_bvalid ,
    output    wire       [63:0] hp1_w_us1_rdata ,
    output    wire        [4:0] hp1_w_us1_rid ,
    output    wire              hp1_w_us1_rlast ,
    output    wire        [1:0] hp1_w_us1_rresp ,
    output    wire              hp1_w_us1_rvalid ,
    output    wire              hp1_w_us1_wready ,
    output    wire              O_hdmi_clk_p ,
    output    wire        [2:0] O_hdmi_tx_p ,
    output    wire              p2f_clk0_50m
,
    output wire edge_clk,edge_rst_n,
    output wire [15:0] edge_awaddr,
    output wire edge_awvalid,
    input wire edge_awready,
    output wire [31:0] edge_wdata,
    output wire [3:0] edge_wstrb,
    output wire edge_wvalid,
    input wire edge_wready,
    input wire [1:0] edge_bresp,
    input wire edge_bvalid,
    output wire edge_bready,
    output wire [15:0] edge_araddr,
    output wire edge_arvalid,
    input wire edge_arready,
    input wire [31:0] edge_rdata,
    input wire [1:0] edge_rresp,
    input wire edge_rvalid,
    output wire edge_rready
);
// GP0 extension: declare before converter/router instances.
wire [31:0] edge_gp0_awaddr;
wire [2:0] edge_gp0_awprot;
wire edge_gp0_awvalid;
wire edge_gp0_awready;
wire [31:0] edge_gp0_wdata;
wire [3:0] edge_gp0_wstrb;
wire edge_gp0_wvalid;
wire edge_gp0_wready;
wire [1:0] edge_gp0_bresp;
wire edge_gp0_bvalid;
wire edge_gp0_bready;
wire [31:0] edge_gp0_araddr;
wire [2:0] edge_gp0_arprot;
wire edge_gp0_arvalid;
wire edge_gp0_arready;
wire [31:0] edge_gp0_rdata;
wire [1:0] edge_gp0_rresp;
wire edge_gp0_rvalid;
wire edge_gp0_rready;
 
    wire              w_port__ARM_Processor_System_0__i2c0_scl_oe ;
    wire              w_net__ARM_Processor_System_0__i2c0_scl_oe ; 

    wire              w_port__ARM_Processor_System_0__i2c0_sda_oe ;
    wire              w_net__ARM_Processor_System_0__i2c0_sda_oe ; 

    wire [32:0]       w_port__ARM_Processor_System_0__master_gp0_axi_araddr ;
    wire [32:0]       w_port__AXI_Protocol_Converter_0__us_axi_araddr ;
    wire [32:0]       w_net__ARM_Processor_System_0__master_gp0_axi_araddr ; 

    wire [1:0]        w_port__ARM_Processor_System_0__master_gp0_axi_arburst ;
    wire [1:0]        w_port__AXI_Protocol_Converter_0__us_axi_arburst ;
    wire [1:0]        w_net__ARM_Processor_System_0__master_gp0_axi_arburst ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp0_axi_arcache ;
    wire [3:0]        w_port__AXI_Protocol_Converter_0__us_axi_arcache ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp0_axi_arcache ; 

    wire [11:0]       w_port__ARM_Processor_System_0__master_gp0_axi_arid ;
    wire [11:0]       w_port__AXI_Protocol_Converter_0__us_axi_arid ;
    wire [11:0]       w_net__ARM_Processor_System_0__master_gp0_axi_arid ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp0_axi_arlen ;
    wire [7:0]        w_port__AXI_Protocol_Converter_0__us_axi_arlen ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp0_axi_arlen ; 

    wire              w_port__ARM_Processor_System_0__master_gp0_axi_arlock ;
    wire [0:0]        w_port__AXI_Protocol_Converter_0__us_axi_arlock ;
    wire              w_net__ARM_Processor_System_0__master_gp0_axi_arlock ; 

    wire [2:0]        w_port__ARM_Processor_System_0__master_gp0_axi_arprot ;
    wire [2:0]        w_port__AXI_Protocol_Converter_0__us_axi_arprot ;
    wire [2:0]        w_net__ARM_Processor_System_0__master_gp0_axi_arprot ; 

    wire [1:0]        w_port__ARM_Processor_System_0__master_gp0_axi_arsize ;
    wire [2:0]        w_port__AXI_Protocol_Converter_0__us_axi_arsize ;
    wire [1:0]        w_net__ARM_Processor_System_0__master_gp0_axi_arsize ; 

    wire              w_port__ARM_Processor_System_0__master_gp0_axi_arvalid ;
    wire              w_port__AXI_Protocol_Converter_0__us_axi_arvalid ;
    wire              w_net__ARM_Processor_System_0__master_gp0_axi_arvalid ; 

    wire [32:0]       w_port__ARM_Processor_System_0__master_gp0_axi_awaddr ;
    wire [32:0]       w_port__AXI_Protocol_Converter_0__us_axi_awaddr ;
    wire [32:0]       w_net__ARM_Processor_System_0__master_gp0_axi_awaddr ; 

    wire [1:0]        w_port__ARM_Processor_System_0__master_gp0_axi_awburst ;
    wire [1:0]        w_port__AXI_Protocol_Converter_0__us_axi_awburst ;
    wire [1:0]        w_net__ARM_Processor_System_0__master_gp0_axi_awburst ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp0_axi_awcache ;
    wire [3:0]        w_port__AXI_Protocol_Converter_0__us_axi_awcache ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp0_axi_awcache ; 

    wire [11:0]       w_port__ARM_Processor_System_0__master_gp0_axi_awid ;
    wire [11:0]       w_port__AXI_Protocol_Converter_0__us_axi_awid ;
    wire [11:0]       w_net__ARM_Processor_System_0__master_gp0_axi_awid ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp0_axi_awlen ;
    wire [7:0]        w_port__AXI_Protocol_Converter_0__us_axi_awlen ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp0_axi_awlen ; 

    wire              w_port__ARM_Processor_System_0__master_gp0_axi_awlock ;
    wire [0:0]        w_port__AXI_Protocol_Converter_0__us_axi_awlock ;
    wire              w_net__ARM_Processor_System_0__master_gp0_axi_awlock ; 

    wire [2:0]        w_port__ARM_Processor_System_0__master_gp0_axi_awprot ;
    wire [2:0]        w_port__AXI_Protocol_Converter_0__us_axi_awprot ;
    wire [2:0]        w_net__ARM_Processor_System_0__master_gp0_axi_awprot ; 

    wire [1:0]        w_port__ARM_Processor_System_0__master_gp0_axi_awsize ;
    wire [2:0]        w_port__AXI_Protocol_Converter_0__us_axi_awsize ;
    wire [1:0]        w_net__ARM_Processor_System_0__master_gp0_axi_awsize ; 

    wire              w_port__ARM_Processor_System_0__master_gp0_axi_awvalid ;
    wire              w_port__AXI_Protocol_Converter_0__us_axi_awvalid ;
    wire              w_net__ARM_Processor_System_0__master_gp0_axi_awvalid ; 

    wire              w_port__ARM_Processor_System_0__master_gp0_axi_bready ;
    wire              w_port__AXI_Protocol_Converter_0__us_axi_bready ;
    wire              w_net__ARM_Processor_System_0__master_gp0_axi_bready ; 

    wire              w_port__ARM_Processor_System_0__master_gp0_axi_rready ;
    wire              w_port__AXI_Protocol_Converter_0__us_axi_rready ;
    wire              w_net__ARM_Processor_System_0__master_gp0_axi_rready ; 

    wire [31:0]       w_port__ARM_Processor_System_0__master_gp0_axi_wdata ;
    wire [31:0]       w_port__AXI_Protocol_Converter_0__us_axi_wdata ;
    wire [31:0]       w_net__ARM_Processor_System_0__master_gp0_axi_wdata ; 

    wire              w_port__ARM_Processor_System_0__master_gp0_axi_wlast ;
    wire              w_port__AXI_Protocol_Converter_0__us_axi_wlast ;
    wire              w_net__ARM_Processor_System_0__master_gp0_axi_wlast ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp0_axi_wstrb ;
    wire [3:0]        w_port__AXI_Protocol_Converter_0__us_axi_wstrb ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp0_axi_wstrb ; 

    wire              w_port__ARM_Processor_System_0__master_gp0_axi_wvalid ;
    wire              w_port__AXI_Protocol_Converter_0__us_axi_wvalid ;
    wire              w_net__ARM_Processor_System_0__master_gp0_axi_wvalid ; 

    wire [32:0]       w_port__ARM_Processor_System_0__master_gp1_axi_araddr ;
    wire [32:0]       w_port__AXI_Matrix_1__us0_araddr ;
    wire [32:0]       w_net__ARM_Processor_System_0__master_gp1_axi_araddr ; 

    wire [1:0]        w_port__ARM_Processor_System_0__master_gp1_axi_arburst ;
    wire [1:0]        w_port__AXI_Matrix_1__us0_arburst ;
    wire [1:0]        w_net__ARM_Processor_System_0__master_gp1_axi_arburst ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp1_axi_arcache ;
    wire [3:0]        w_port__AXI_Matrix_1__us0_arcache ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp1_axi_arcache ; 

    wire [11:0]       w_port__ARM_Processor_System_0__master_gp1_axi_arid ;
    wire [11:0]       w_port__AXI_Matrix_1__us0_arid ;
    wire [11:0]       w_net__ARM_Processor_System_0__master_gp1_axi_arid ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp1_axi_arlen ;
    wire [7:0]        w_port__AXI_Matrix_1__us0_arlen ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp1_axi_arlen ; 

    wire              w_port__ARM_Processor_System_0__master_gp1_axi_arlock ;
    wire [0:0]        w_port__AXI_Matrix_1__us0_arlock ;
    wire              w_net__ARM_Processor_System_0__master_gp1_axi_arlock ; 

    wire [2:0]        w_port__ARM_Processor_System_0__master_gp1_axi_arprot ;
    wire [2:0]        w_port__AXI_Matrix_1__us0_arprot ;
    wire [2:0]        w_net__ARM_Processor_System_0__master_gp1_axi_arprot ; 

    wire [1:0]        w_port__ARM_Processor_System_0__master_gp1_axi_arsize ;
    wire [2:0]        w_port__AXI_Matrix_1__us0_arsize ;
    wire [1:0]        w_net__ARM_Processor_System_0__master_gp1_axi_arsize ; 

    wire              w_port__ARM_Processor_System_0__master_gp1_axi_arvalid ;
    wire              w_port__AXI_Matrix_1__us0_arvalid ;
    wire              w_net__ARM_Processor_System_0__master_gp1_axi_arvalid ; 

    wire [32:0]       w_port__ARM_Processor_System_0__master_gp1_axi_awaddr ;
    wire [32:0]       w_port__AXI_Matrix_1__us0_awaddr ;
    wire [32:0]       w_net__ARM_Processor_System_0__master_gp1_axi_awaddr ; 

    wire [1:0]        w_port__ARM_Processor_System_0__master_gp1_axi_awburst ;
    wire [1:0]        w_port__AXI_Matrix_1__us0_awburst ;
    wire [1:0]        w_net__ARM_Processor_System_0__master_gp1_axi_awburst ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp1_axi_awcache ;
    wire [3:0]        w_port__AXI_Matrix_1__us0_awcache ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp1_axi_awcache ; 

    wire [11:0]       w_port__ARM_Processor_System_0__master_gp1_axi_awid ;
    wire [11:0]       w_port__AXI_Matrix_1__us0_awid ;
    wire [11:0]       w_net__ARM_Processor_System_0__master_gp1_axi_awid ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp1_axi_awlen ;
    wire [7:0]        w_port__AXI_Matrix_1__us0_awlen ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp1_axi_awlen ; 

    wire              w_port__ARM_Processor_System_0__master_gp1_axi_awlock ;
    wire [0:0]        w_port__AXI_Matrix_1__us0_awlock ;
    wire              w_net__ARM_Processor_System_0__master_gp1_axi_awlock ; 

    wire [2:0]        w_port__ARM_Processor_System_0__master_gp1_axi_awprot ;
    wire [2:0]        w_port__AXI_Matrix_1__us0_awprot ;
    wire [2:0]        w_net__ARM_Processor_System_0__master_gp1_axi_awprot ; 

    wire [1:0]        w_port__ARM_Processor_System_0__master_gp1_axi_awsize ;
    wire [2:0]        w_port__AXI_Matrix_1__us0_awsize ;
    wire [1:0]        w_net__ARM_Processor_System_0__master_gp1_axi_awsize ; 

    wire              w_port__ARM_Processor_System_0__master_gp1_axi_awvalid ;
    wire              w_port__AXI_Matrix_1__us0_awvalid ;
    wire              w_net__ARM_Processor_System_0__master_gp1_axi_awvalid ; 

    wire              w_port__ARM_Processor_System_0__master_gp1_axi_bready ;
    wire              w_port__AXI_Matrix_1__us0_bready ;
    wire              w_net__ARM_Processor_System_0__master_gp1_axi_bready ; 

    wire              w_port__ARM_Processor_System_0__master_gp1_axi_rready ;
    wire              w_port__AXI_Matrix_1__us0_rready ;
    wire              w_net__ARM_Processor_System_0__master_gp1_axi_rready ; 

    wire [31:0]       w_port__ARM_Processor_System_0__master_gp1_axi_wdata ;
    wire [31:0]       w_port__AXI_Matrix_1__us0_wdata ;
    wire [31:0]       w_net__ARM_Processor_System_0__master_gp1_axi_wdata ; 

    wire              w_port__ARM_Processor_System_0__master_gp1_axi_wlast ;
    wire              w_port__AXI_Matrix_1__us0_wlast ;
    wire              w_net__ARM_Processor_System_0__master_gp1_axi_wlast ; 

    wire [3:0]        w_port__ARM_Processor_System_0__master_gp1_axi_wstrb ;
    wire [3:0]        w_port__AXI_Matrix_1__us0_wstrb ;
    wire [3:0]        w_net__ARM_Processor_System_0__master_gp1_axi_wstrb ; 

    wire              w_port__ARM_Processor_System_0__master_gp1_axi_wvalid ;
    wire              w_port__AXI_Matrix_1__us0_wvalid ;
    wire              w_net__ARM_Processor_System_0__master_gp1_axi_wvalid ; 

    wire              w_port__ARM_Processor_System_0__p2f_clk0 ;
    // PS AXI clocks share PLL_0 C0=75MHz/C1=150MHz. TD 6.2.2 cannot
    // derive the native PS AXI clocks reliably with separate returning PLLs.
    // Reuse the existing C1 output; nominal clock frequencies are unchanged.
    // Both 150MHz reset sequencers now use the lock from the shared PLL.
    wire w_shared_fabric_clk150;

    wire              w_port__pll_75m__refclk ;
    wire              w_port__PLL_npu__refclk ;
    wire              w_port__pll_150m__refclk ;
    wire              w_port__video_timing_generator_v01_0__ref_clk ;
    wire              w_net__ARM_Processor_System_0__p2f_clk0 ; 

    wire              w_port__ARM_Processor_System_0__p2f_rst0_n ;
    wire              w_port__rst_n_75m__aux_rst ;
    wire              w_port__rstn_150m__aux_rst ;
    wire              w_port__rstn_npu__aux_rst ;
    wire              w_net__ARM_Processor_System_0__p2f_rst0_n ; 

    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_arready ;
    wire              w_port__Video_NPU_0__m_axi_arready_soft_i ;
    wire              w_net__ARM_Processor_System_0__slave_hp0_axi_arready ; 

    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_awready ;
    wire              w_port__Video_NPU_0__m_axi_awready_soft_i ;
    wire              w_net__ARM_Processor_System_0__slave_hp0_axi_awready ; 

    wire [5:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_bid ;
    wire [5:0]        w_port__Video_NPU_0__m_axi_bid_soft_i ;
    wire [5:0]        w_net__ARM_Processor_System_0__slave_hp0_axi_bid ; 

    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_bresp ;
    wire [1:0]        w_port__Video_NPU_0__m_axi_bresp_soft_i ;
    wire [1:0]        w_net__ARM_Processor_System_0__slave_hp0_axi_bresp ; 

    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_bvalid ;
    wire              w_port__Video_NPU_0__m_axi_bvalid_soft_i ;
    wire              w_net__ARM_Processor_System_0__slave_hp0_axi_bvalid ; 

    wire [63:0]       w_port__ARM_Processor_System_0__slave_hp0_axi_rdata ;
    wire [63:0]       w_port__Video_NPU_0__m_axi_rdata_soft_i ;
    wire [63:0]       w_net__ARM_Processor_System_0__slave_hp0_axi_rdata ; 

    wire [5:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_rid ;
    wire [5:0]        w_port__Video_NPU_0__m_axi_rid_soft_i ;
    wire [5:0]        w_net__ARM_Processor_System_0__slave_hp0_axi_rid ; 

    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_rlast ;
    wire              w_port__Video_NPU_0__m_axi_rlast_soft_i ;
    wire              w_net__ARM_Processor_System_0__slave_hp0_axi_rlast ; 

    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_rresp ;
    wire [1:0]        w_port__Video_NPU_0__m_axi_rresp_soft_i ;
    wire [1:0]        w_net__ARM_Processor_System_0__slave_hp0_axi_rresp ; 

    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_rvalid ;
    wire              w_port__Video_NPU_0__m_axi_rvalid_soft_i ;
    wire              w_net__ARM_Processor_System_0__slave_hp0_axi_rvalid ; 

    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_wready ;
    wire              w_port__Video_NPU_0__m_axi_wready_soft_i ;
    wire              w_net__ARM_Processor_System_0__slave_hp0_axi_wready ; 

    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_arready ;
    wire              w_port__AXI_Matrix_2__ds0_arready ;
    wire              w_net__ARM_Processor_System_0__slave_hp1_axi_arready ; 

    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_awready ;
    wire              w_port__AXI_Matrix_2__ds0_awready ;
    wire              w_net__ARM_Processor_System_0__slave_hp1_axi_awready ; 

    wire [5:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_bid ;
    wire [5:0]        w_port__AXI_Matrix_2__ds0_bid ;
    wire [5:0]        w_net__ARM_Processor_System_0__slave_hp1_axi_bid ; 

    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_bresp ;
    wire [1:0]        w_port__AXI_Matrix_2__ds0_bresp ;
    wire [1:0]        w_net__ARM_Processor_System_0__slave_hp1_axi_bresp ; 

    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_bvalid ;
    wire              w_port__AXI_Matrix_2__ds0_bvalid ;
    wire              w_net__ARM_Processor_System_0__slave_hp1_axi_bvalid ; 

    wire [63:0]       w_port__ARM_Processor_System_0__slave_hp1_axi_rdata ;
    wire [63:0]       w_port__AXI_Matrix_2__ds0_rdata ;
    wire [63:0]       w_net__ARM_Processor_System_0__slave_hp1_axi_rdata ; 

    wire [5:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_rid ;
    wire [5:0]        w_port__AXI_Matrix_2__ds0_rid ;
    wire [5:0]        w_net__ARM_Processor_System_0__slave_hp1_axi_rid ; 

    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_rlast ;
    wire              w_port__AXI_Matrix_2__ds0_rlast ;
    wire              w_net__ARM_Processor_System_0__slave_hp1_axi_rlast ; 

    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_rresp ;
    wire [1:0]        w_port__AXI_Matrix_2__ds0_rresp ;
    wire [1:0]        w_net__ARM_Processor_System_0__slave_hp1_axi_rresp ; 

    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_rvalid ;
    wire              w_port__AXI_Matrix_2__ds0_rvalid ;
    wire              w_net__ARM_Processor_System_0__slave_hp1_axi_rvalid ; 

    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_wready ;
    wire              w_port__AXI_Matrix_2__ds0_wready ;
    wire              w_net__ARM_Processor_System_0__slave_hp1_axi_wready ; 

    wire              w_port__AXI4_Stream_to_Video_Out_0__locked ;
    wire              w_port__pwm_0_1__rst_n ;
    wire              w_net__AXI4_Stream_to_Video_Out_0__locked ; 

    wire              w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tready ;
    wire              w_port__VDMA_0__m_axis_mm2s_tready ;
    wire              w_net__AXI4_Stream_to_Video_Out_0__s_axis_video_tready ; 

    wire              w_port__AXI4_Stream_to_Video_Out_0__vid_active_video ;
    wire              w_port__uihdmi_tx_0__I_video_in_de ;
    wire              w_net__AXI4_Stream_to_Video_Out_0__vid_active_video ; 

    wire [23:0]       w_port__AXI4_Stream_to_Video_Out_0__vid_data ;
    wire [23:0]       w_port__uihdmi_tx_0__I_video_in_data ;
    wire [23:0]       w_net__AXI4_Stream_to_Video_Out_0__vid_data ; 

    wire              w_port__AXI4_Stream_to_Video_Out_0__vid_hsync ;
    wire              w_port__uihdmi_tx_0__I_video_in_hs ;
    wire              w_net__AXI4_Stream_to_Video_Out_0__vid_hsync ; 

    wire              w_port__AXI4_Stream_to_Video_Out_0__vid_vsync ;
    wire              w_port__uihdmi_tx_0__I_video_in_vs ;
    wire              w_net__AXI4_Stream_to_Video_Out_0__vid_vsync ; 

    wire              w_port__AXI4_Stream_to_Video_Out_0__vtg_ce ;
    wire              w_port__video_timing_generator_v01_0__vtg_ce ;
    wire              w_net__AXI4_Stream_to_Video_Out_0__vtg_ce ; 

    wire [32:0]       w_port__AXI_Matrix_0__ds0_araddr ;
    wire [8:0]        w_port__VDMA_0__axi_lite_araddr ;
    wire [32:0]       w_net__AXI_Matrix_0__ds0_araddr ; 

    wire              w_port__AXI_Matrix_0__ds0_arvalid ;
    wire              w_port__VDMA_0__axi_lite_arvalid ;
    wire              w_net__AXI_Matrix_0__ds0_arvalid ; 

    wire [32:0]       w_port__AXI_Matrix_0__ds0_awaddr ;
    wire [8:0]        w_port__VDMA_0__axi_lite_awaddr ;
    wire [32:0]       w_net__AXI_Matrix_0__ds0_awaddr ; 

    wire              w_port__AXI_Matrix_0__ds0_awvalid ;
    wire              w_port__VDMA_0__axi_lite_awvalid ;
    wire              w_net__AXI_Matrix_0__ds0_awvalid ; 

    wire              w_port__AXI_Matrix_0__ds0_bready ;
    wire              w_port__VDMA_0__axi_lite_bready ;
    wire              w_net__AXI_Matrix_0__ds0_bready ; 

    wire              w_port__AXI_Matrix_0__ds0_rready ;
    wire              w_port__VDMA_0__axi_lite_rready ;
    wire              w_net__AXI_Matrix_0__ds0_rready ; 

    wire [31:0]       w_port__AXI_Matrix_0__ds0_wdata ;
    wire [31:0]       w_port__VDMA_0__axi_lite_wdata ;
    wire [31:0]       w_net__AXI_Matrix_0__ds0_wdata ; 

    wire              w_port__AXI_Matrix_0__ds0_wvalid ;
    wire              w_port__VDMA_0__axi_lite_wvalid ;
    wire              w_net__AXI_Matrix_0__ds0_wvalid ; 

    wire [32:0]       w_port__AXI_Matrix_0__ds1_araddr ;
    wire [12:0]       w_port__video_timing_generator_v01_0__s_axi_araddr ;
    wire [32:0]       w_net__AXI_Matrix_0__ds1_araddr ; 

    wire              w_port__AXI_Matrix_0__ds1_arvalid ;
    wire              w_port__video_timing_generator_v01_0__s_axi_arvalid ;
    wire              w_net__AXI_Matrix_0__ds1_arvalid ; 

    wire [32:0]       w_port__AXI_Matrix_0__ds1_awaddr ;
    wire [12:0]       w_port__video_timing_generator_v01_0__s_axi_awaddr ;
    wire [32:0]       w_net__AXI_Matrix_0__ds1_awaddr ; 

    wire              w_port__AXI_Matrix_0__ds1_awvalid ;
    wire              w_port__video_timing_generator_v01_0__s_axi_awvalid ;
    wire              w_net__AXI_Matrix_0__ds1_awvalid ; 

    wire              w_port__AXI_Matrix_0__ds1_bready ;
    wire              w_port__video_timing_generator_v01_0__s_axi_bready ;
    wire              w_net__AXI_Matrix_0__ds1_bready ; 

    wire              w_port__AXI_Matrix_0__ds1_rready ;
    wire              w_port__video_timing_generator_v01_0__s_axi_rready ;
    wire              w_net__AXI_Matrix_0__ds1_rready ; 

    wire [31:0]       w_port__AXI_Matrix_0__ds1_wdata ;
    wire [31:0]       w_port__video_timing_generator_v01_0__s_axi_wdata ;
    wire [31:0]       w_net__AXI_Matrix_0__ds1_wdata ; 

    wire [3:0]        w_port__AXI_Matrix_0__ds1_wstrb ;
    wire [3:0]        w_port__video_timing_generator_v01_0__s_axi_wstrb ;
    wire [3:0]        w_net__AXI_Matrix_0__ds1_wstrb ; 

    wire              w_port__AXI_Matrix_0__ds1_wvalid ;
    wire              w_port__video_timing_generator_v01_0__s_axi_wvalid ;
    wire              w_net__AXI_Matrix_0__ds1_wvalid ; 

    wire [32:0]       w_port__AXI_Matrix_0__ds2_araddr ;
    wire [3:0]        w_port__fvdma_ctrl_0__s_axi_araddr ;
    wire [32:0]       w_net__AXI_Matrix_0__ds2_araddr ; 

    wire [2:0]        w_port__AXI_Matrix_0__ds2_arprot ;
    wire [2:0]        w_port__fvdma_ctrl_0__s_axi_arprot ;
    wire [2:0]        w_net__AXI_Matrix_0__ds2_arprot ; 

    wire              w_port__AXI_Matrix_0__ds2_arvalid ;
    wire              w_port__fvdma_ctrl_0__s_axi_arvalid ;
    wire              w_net__AXI_Matrix_0__ds2_arvalid ; 

    wire [32:0]       w_port__AXI_Matrix_0__ds2_awaddr ;
    wire [3:0]        w_port__fvdma_ctrl_0__s_axi_awaddr ;
    wire [32:0]       w_net__AXI_Matrix_0__ds2_awaddr ; 

    wire [2:0]        w_port__AXI_Matrix_0__ds2_awprot ;
    wire [2:0]        w_port__fvdma_ctrl_0__s_axi_awprot ;
    wire [2:0]        w_net__AXI_Matrix_0__ds2_awprot ; 

    wire              w_port__AXI_Matrix_0__ds2_awvalid ;
    wire              w_port__fvdma_ctrl_0__s_axi_awvalid ;
    wire              w_net__AXI_Matrix_0__ds2_awvalid ; 

    wire              w_port__AXI_Matrix_0__ds2_bready ;
    wire              w_port__fvdma_ctrl_0__s_axi_bready ;
    wire              w_net__AXI_Matrix_0__ds2_bready ; 

    wire              w_port__AXI_Matrix_0__ds2_rready ;
    wire              w_port__fvdma_ctrl_0__s_axi_rready ;
    wire              w_net__AXI_Matrix_0__ds2_rready ; 

    wire [31:0]       w_port__AXI_Matrix_0__ds2_wdata ;
    wire [31:0]       w_port__fvdma_ctrl_0__s_axi_wdata ;
    wire [31:0]       w_net__AXI_Matrix_0__ds2_wdata ; 

    wire [3:0]        w_port__AXI_Matrix_0__ds2_wstrb ;
    wire [3:0]        w_port__fvdma_ctrl_0__s_axi_wstrb ;
    wire [3:0]        w_net__AXI_Matrix_0__ds2_wstrb ; 

    wire              w_port__AXI_Matrix_0__ds2_wvalid ;
    wire              w_port__fvdma_ctrl_0__s_axi_wvalid ;
    wire              w_net__AXI_Matrix_0__ds2_wvalid ; 

    wire              w_port__AXI_Matrix_0__us0_arready ;
    wire              w_port__AXI_Protocol_Converter_0__ds_axi_arready ;
    wire              w_net__AXI_Matrix_0__us0_arready ; 

    wire              w_port__AXI_Matrix_0__us0_awready ;
    wire              w_port__AXI_Protocol_Converter_0__ds_axi_awready ;
    wire              w_net__AXI_Matrix_0__us0_awready ; 

    wire [1:0]        w_port__AXI_Matrix_0__us0_bresp ;
    wire [1:0]        w_port__AXI_Protocol_Converter_0__ds_axi_bresp ;
    wire [1:0]        w_net__AXI_Matrix_0__us0_bresp ; 

    wire              w_port__AXI_Matrix_0__us0_bvalid ;
    wire              w_port__AXI_Protocol_Converter_0__ds_axi_bvalid ;
    wire              w_net__AXI_Matrix_0__us0_bvalid ; 

    wire [31:0]       w_port__AXI_Matrix_0__us0_rdata ;
    wire [31:0]       w_port__AXI_Protocol_Converter_0__ds_axi_rdata ;
    wire [31:0]       w_net__AXI_Matrix_0__us0_rdata ; 

    wire [1:0]        w_port__AXI_Matrix_0__us0_rresp ;
    wire [1:0]        w_port__AXI_Protocol_Converter_0__ds_axi_rresp ;
    wire [1:0]        w_net__AXI_Matrix_0__us0_rresp ; 

    wire              w_port__AXI_Matrix_0__us0_rvalid ;
    wire              w_port__AXI_Protocol_Converter_0__ds_axi_rvalid ;
    wire              w_net__AXI_Matrix_0__us0_rvalid ; 

    wire              w_port__AXI_Matrix_0__us0_wready ;
    wire              w_port__AXI_Protocol_Converter_0__ds_axi_wready ;
    wire              w_net__AXI_Matrix_0__us0_wready ; 

    wire [32:0]       w_port__AXI_Matrix_1__ds0_araddr ;
    wire [32:0]       w_port__AXI_Protocol_Converter_1__us_axi_araddr ;
    wire [32:0]       w_net__AXI_Matrix_1__ds0_araddr ; 

    wire [1:0]        w_port__AXI_Matrix_1__ds0_arburst ;
    wire [1:0]        w_port__AXI_Protocol_Converter_1__us_axi_arburst ;
    wire [1:0]        w_net__AXI_Matrix_1__ds0_arburst ; 

    wire [3:0]        w_port__AXI_Matrix_1__ds0_arcache ;
    wire [3:0]        w_port__AXI_Protocol_Converter_1__us_axi_arcache ;
    wire [3:0]        w_net__AXI_Matrix_1__ds0_arcache ; 

    wire [12:0]       w_port__AXI_Matrix_1__ds0_arid ;
    wire [12:0]       w_port__AXI_Protocol_Converter_1__us_axi_arid ;
    wire [12:0]       w_net__AXI_Matrix_1__ds0_arid ; 

    wire [7:0]        w_port__AXI_Matrix_1__ds0_arlen ;
    wire [7:0]        w_port__AXI_Protocol_Converter_1__us_axi_arlen ;
    wire [7:0]        w_net__AXI_Matrix_1__ds0_arlen ; 

    wire [0:0]        w_port__AXI_Matrix_1__ds0_arlock ;
    wire [0:0]        w_port__AXI_Protocol_Converter_1__us_axi_arlock ;
    wire [0:0]        w_net__AXI_Matrix_1__ds0_arlock ; 

    wire [2:0]        w_port__AXI_Matrix_1__ds0_arprot ;
    wire [2:0]        w_port__AXI_Protocol_Converter_1__us_axi_arprot ;
    wire [2:0]        w_net__AXI_Matrix_1__ds0_arprot ; 

    wire [3:0]        w_port__AXI_Matrix_1__ds0_arqos ;
    wire [3:0]        w_port__AXI_Protocol_Converter_1__us_axi_arqos ;
    wire [3:0]        w_net__AXI_Matrix_1__ds0_arqos ; 

    wire [2:0]        w_port__AXI_Matrix_1__ds0_arsize ;
    wire [2:0]        w_port__AXI_Protocol_Converter_1__us_axi_arsize ;
    wire [2:0]        w_net__AXI_Matrix_1__ds0_arsize ; 

    wire              w_port__AXI_Matrix_1__ds0_arvalid ;
    wire              w_port__AXI_Protocol_Converter_1__us_axi_arvalid ;
    wire              w_net__AXI_Matrix_1__ds0_arvalid ; 

    wire [32:0]       w_port__AXI_Matrix_1__ds0_awaddr ;
    wire [32:0]       w_port__AXI_Protocol_Converter_1__us_axi_awaddr ;
    wire [32:0]       w_net__AXI_Matrix_1__ds0_awaddr ; 

    wire [1:0]        w_port__AXI_Matrix_1__ds0_awburst ;
    wire [1:0]        w_port__AXI_Protocol_Converter_1__us_axi_awburst ;
    wire [1:0]        w_net__AXI_Matrix_1__ds0_awburst ; 

    wire [3:0]        w_port__AXI_Matrix_1__ds0_awcache ;
    wire [3:0]        w_port__AXI_Protocol_Converter_1__us_axi_awcache ;
    wire [3:0]        w_net__AXI_Matrix_1__ds0_awcache ; 

    wire [12:0]       w_port__AXI_Matrix_1__ds0_awid ;
    wire [12:0]       w_port__AXI_Protocol_Converter_1__us_axi_awid ;
    wire [12:0]       w_net__AXI_Matrix_1__ds0_awid ; 

    wire [7:0]        w_port__AXI_Matrix_1__ds0_awlen ;
    wire [7:0]        w_port__AXI_Protocol_Converter_1__us_axi_awlen ;
    wire [7:0]        w_net__AXI_Matrix_1__ds0_awlen ; 

    wire [0:0]        w_port__AXI_Matrix_1__ds0_awlock ;
    wire [0:0]        w_port__AXI_Protocol_Converter_1__us_axi_awlock ;
    wire [0:0]        w_net__AXI_Matrix_1__ds0_awlock ; 

    wire [2:0]        w_port__AXI_Matrix_1__ds0_awprot ;
    wire [2:0]        w_port__AXI_Protocol_Converter_1__us_axi_awprot ;
    wire [2:0]        w_net__AXI_Matrix_1__ds0_awprot ; 

    wire [3:0]        w_port__AXI_Matrix_1__ds0_awqos ;
    wire [3:0]        w_port__AXI_Protocol_Converter_1__us_axi_awqos ;
    wire [3:0]        w_net__AXI_Matrix_1__ds0_awqos ; 

    wire [2:0]        w_port__AXI_Matrix_1__ds0_awsize ;
    wire [2:0]        w_port__AXI_Protocol_Converter_1__us_axi_awsize ;
    wire [2:0]        w_net__AXI_Matrix_1__ds0_awsize ; 

    wire              w_port__AXI_Matrix_1__ds0_awvalid ;
    wire              w_port__AXI_Protocol_Converter_1__us_axi_awvalid ;
    wire              w_net__AXI_Matrix_1__ds0_awvalid ; 

    wire              w_port__AXI_Matrix_1__ds0_bready ;
    wire              w_port__AXI_Protocol_Converter_1__us_axi_bready ;
    wire              w_net__AXI_Matrix_1__ds0_bready ; 

    wire              w_port__AXI_Matrix_1__ds0_rready ;
    wire              w_port__AXI_Protocol_Converter_1__us_axi_rready ;
    wire              w_net__AXI_Matrix_1__ds0_rready ; 

    wire [31:0]       w_port__AXI_Matrix_1__ds0_wdata ;
    wire [31:0]       w_port__AXI_Protocol_Converter_1__us_axi_wdata ;
    wire [31:0]       w_net__AXI_Matrix_1__ds0_wdata ; 

    wire              w_port__AXI_Matrix_1__ds0_wlast ;
    wire              w_port__AXI_Protocol_Converter_1__us_axi_wlast ;
    wire              w_net__AXI_Matrix_1__ds0_wlast ; 

    wire [3:0]        w_port__AXI_Matrix_1__ds0_wstrb ;
    wire [3:0]        w_port__AXI_Protocol_Converter_1__us_axi_wstrb ;
    wire [3:0]        w_net__AXI_Matrix_1__ds0_wstrb ; 

    wire              w_port__AXI_Matrix_1__ds0_wvalid ;
    wire              w_port__AXI_Protocol_Converter_1__us_axi_wvalid ;
    wire              w_net__AXI_Matrix_1__ds0_wvalid ; 

    wire              w_port__AXI_Matrix_1__us0_arready ;
    wire              w_port__ARM_Processor_System_0__master_gp1_axi_arready ;
    wire              w_net__AXI_Matrix_1__us0_arready ; 

    wire              w_port__AXI_Matrix_1__us0_awready ;
    wire              w_port__ARM_Processor_System_0__master_gp1_axi_awready ;
    wire              w_net__AXI_Matrix_1__us0_awready ; 

    wire [11:0]       w_port__AXI_Matrix_1__us0_bid ;
    wire [11:0]       w_port__ARM_Processor_System_0__master_gp1_axi_bid ;
    wire [11:0]       w_net__AXI_Matrix_1__us0_bid ; 

    wire [1:0]        w_port__AXI_Matrix_1__us0_bresp ;
    wire [1:0]        w_port__ARM_Processor_System_0__master_gp1_axi_bresp ;
    wire [1:0]        w_net__AXI_Matrix_1__us0_bresp ; 

    wire              w_port__AXI_Matrix_1__us0_bvalid ;
    wire              w_port__ARM_Processor_System_0__master_gp1_axi_bvalid ;
    wire              w_net__AXI_Matrix_1__us0_bvalid ; 

    wire [31:0]       w_port__AXI_Matrix_1__us0_rdata ;
    wire [31:0]       w_port__ARM_Processor_System_0__master_gp1_axi_rdata ;
    wire [31:0]       w_net__AXI_Matrix_1__us0_rdata ; 

    wire [11:0]       w_port__AXI_Matrix_1__us0_rid ;
    wire [11:0]       w_port__ARM_Processor_System_0__master_gp1_axi_rid ;
    wire [11:0]       w_net__AXI_Matrix_1__us0_rid ; 

    wire              w_port__AXI_Matrix_1__us0_rlast ;
    wire              w_port__ARM_Processor_System_0__master_gp1_axi_rlast ;
    wire              w_net__AXI_Matrix_1__us0_rlast ; 

    wire [1:0]        w_port__AXI_Matrix_1__us0_rresp ;
    wire [1:0]        w_port__ARM_Processor_System_0__master_gp1_axi_rresp ;
    wire [1:0]        w_net__AXI_Matrix_1__us0_rresp ; 

    wire              w_port__AXI_Matrix_1__us0_rvalid ;
    wire              w_port__ARM_Processor_System_0__master_gp1_axi_rvalid ;
    wire              w_net__AXI_Matrix_1__us0_rvalid ; 

    wire              w_port__AXI_Matrix_1__us0_wready ;
    wire              w_port__ARM_Processor_System_0__master_gp1_axi_wready ;
    wire              w_net__AXI_Matrix_1__us0_wready ; 

    wire [31:0]       w_port__AXI_Matrix_2__ds0_araddr ;
    wire [32:0]       w_port__ARM_Processor_System_0__slave_hp1_axi_araddr ;
    wire [31:0]       w_net__AXI_Matrix_2__ds0_araddr ; 

    wire [1:0]        w_port__AXI_Matrix_2__ds0_arburst ;
    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_arburst ;
    wire [1:0]        w_net__AXI_Matrix_2__ds0_arburst ; 

    wire [3:0]        w_port__AXI_Matrix_2__ds0_arcache ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_arcache ;
    wire [3:0]        w_net__AXI_Matrix_2__ds0_arcache ; 

    wire [5:0]        w_port__AXI_Matrix_2__ds0_arid ;
    wire [5:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_arid ;
    wire [5:0]        w_net__AXI_Matrix_2__ds0_arid ; 

    wire [7:0]        w_port__AXI_Matrix_2__ds0_arlen ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_arlen ;
    wire [7:0]        w_net__AXI_Matrix_2__ds0_arlen ; 

    wire [0:0]        w_port__AXI_Matrix_2__ds0_arlock ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_arlock ;
    wire [0:0]        w_net__AXI_Matrix_2__ds0_arlock ; 

    wire [2:0]        w_port__AXI_Matrix_2__ds0_arprot ;
    wire [2:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_arprot ;
    wire [2:0]        w_net__AXI_Matrix_2__ds0_arprot ; 

    wire [3:0]        w_port__AXI_Matrix_2__ds0_arqos ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_arqos ;
    wire [3:0]        w_net__AXI_Matrix_2__ds0_arqos ; 

    wire [2:0]        w_port__AXI_Matrix_2__ds0_arsize ;
    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_arsize ;
    wire [2:0]        w_net__AXI_Matrix_2__ds0_arsize ; 

    wire              w_port__AXI_Matrix_2__ds0_arvalid ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_arvalid ;
    wire              w_net__AXI_Matrix_2__ds0_arvalid ; 

    wire [31:0]       w_port__AXI_Matrix_2__ds0_awaddr ;
    wire [32:0]       w_port__ARM_Processor_System_0__slave_hp1_axi_awaddr ;
    wire [31:0]       w_net__AXI_Matrix_2__ds0_awaddr ; 

    wire [1:0]        w_port__AXI_Matrix_2__ds0_awburst ;
    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_awburst ;
    wire [1:0]        w_net__AXI_Matrix_2__ds0_awburst ; 

    wire [3:0]        w_port__AXI_Matrix_2__ds0_awcache ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_awcache ;
    wire [3:0]        w_net__AXI_Matrix_2__ds0_awcache ; 

    wire [5:0]        w_port__AXI_Matrix_2__ds0_awid ;
    wire [5:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_awid ;
    wire [5:0]        w_net__AXI_Matrix_2__ds0_awid ; 

    wire [7:0]        w_port__AXI_Matrix_2__ds0_awlen ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_awlen ;
    wire [7:0]        w_net__AXI_Matrix_2__ds0_awlen ; 

    wire [0:0]        w_port__AXI_Matrix_2__ds0_awlock ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_awlock ;
    wire [0:0]        w_net__AXI_Matrix_2__ds0_awlock ; 

    wire [2:0]        w_port__AXI_Matrix_2__ds0_awprot ;
    wire [2:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_awprot ;
    wire [2:0]        w_net__AXI_Matrix_2__ds0_awprot ; 

    wire [3:0]        w_port__AXI_Matrix_2__ds0_awqos ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_awqos ;
    wire [3:0]        w_net__AXI_Matrix_2__ds0_awqos ; 

    wire [2:0]        w_port__AXI_Matrix_2__ds0_awsize ;
    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_awsize ;
    wire [2:0]        w_net__AXI_Matrix_2__ds0_awsize ; 

    wire              w_port__AXI_Matrix_2__ds0_awvalid ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_awvalid ;
    wire              w_net__AXI_Matrix_2__ds0_awvalid ; 

    wire              w_port__AXI_Matrix_2__ds0_bready ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_bready ;
    wire              w_net__AXI_Matrix_2__ds0_bready ; 

    wire              w_port__AXI_Matrix_2__ds0_rready ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_rready ;
    wire              w_net__AXI_Matrix_2__ds0_rready ; 

    wire [63:0]       w_port__AXI_Matrix_2__ds0_wdata ;
    wire [63:0]       w_port__ARM_Processor_System_0__slave_hp1_axi_wdata ;
    wire [63:0]       w_net__AXI_Matrix_2__ds0_wdata ; 

    wire              w_port__AXI_Matrix_2__ds0_wlast ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_wlast ;
    wire              w_net__AXI_Matrix_2__ds0_wlast ; 

    wire [7:0]        w_port__AXI_Matrix_2__ds0_wstrb ;
    wire [7:0]        w_port__ARM_Processor_System_0__slave_hp1_axi_wstrb ;
    wire [7:0]        w_net__AXI_Matrix_2__ds0_wstrb ; 

    wire              w_port__AXI_Matrix_2__ds0_wvalid ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_wvalid ;
    wire              w_net__AXI_Matrix_2__ds0_wvalid ; 

    wire              w_port__AXI_Matrix_2__us0_arready ;
    wire              w_port__VDMA_0__m_axi_mm2s_arready ;
    wire              w_net__AXI_Matrix_2__us0_arready ; 

    wire [63:0]       w_port__AXI_Matrix_2__us0_rdata ;
    wire [63:0]       w_port__VDMA_0__m_axi_mm2s_rdata ;
    wire [63:0]       w_net__AXI_Matrix_2__us0_rdata ; 

    wire              w_port__AXI_Matrix_2__us0_rlast ;
    wire              w_port__VDMA_0__m_axi_mm2s_rlast ;
    wire              w_net__AXI_Matrix_2__us0_rlast ; 

    wire [1:0]        w_port__AXI_Matrix_2__us0_rresp ;
    wire [1:0]        w_port__VDMA_0__m_axi_mm2s_rresp ;
    wire [1:0]        w_net__AXI_Matrix_2__us0_rresp ; 

    wire              w_port__AXI_Matrix_2__us0_rvalid ;
    wire              w_port__VDMA_0__m_axi_mm2s_rvalid ;
    wire              w_net__AXI_Matrix_2__us0_rvalid ; 

    wire              w_port__AXI_Matrix_2__us1_arready ;
    wire              w_net__AXI_Matrix_2__us1_arready ; 

    wire              w_port__AXI_Matrix_2__us1_awready ;
    wire              w_net__AXI_Matrix_2__us1_awready ; 

    wire [4:0]        w_port__AXI_Matrix_2__us1_bid ;
    wire [4:0]        w_net__AXI_Matrix_2__us1_bid ; 

    wire [1:0]        w_port__AXI_Matrix_2__us1_bresp ;
    wire [1:0]        w_net__AXI_Matrix_2__us1_bresp ; 

    wire              w_port__AXI_Matrix_2__us1_bvalid ;
    wire              w_net__AXI_Matrix_2__us1_bvalid ; 

    wire [63:0]       w_port__AXI_Matrix_2__us1_rdata ;
    wire [63:0]       w_net__AXI_Matrix_2__us1_rdata ; 

    wire [4:0]        w_port__AXI_Matrix_2__us1_rid ;
    wire [4:0]        w_net__AXI_Matrix_2__us1_rid ; 

    wire              w_port__AXI_Matrix_2__us1_rlast ;
    wire              w_net__AXI_Matrix_2__us1_rlast ; 

    wire [1:0]        w_port__AXI_Matrix_2__us1_rresp ;
    wire [1:0]        w_net__AXI_Matrix_2__us1_rresp ; 

    wire              w_port__AXI_Matrix_2__us1_rvalid ;
    wire              w_net__AXI_Matrix_2__us1_rvalid ; 

    wire              w_port__AXI_Matrix_2__us1_wready ;
    wire              w_net__AXI_Matrix_2__us1_wready ; 

    wire [32:0]       w_port__AXI_Protocol_Converter_0__ds_axi_araddr ;
    wire [32:0]       w_port__AXI_Matrix_0__us0_araddr ;
    wire [32:0]       w_net__AXI_Protocol_Converter_0__ds_axi_araddr ; 

    wire [2:0]        w_port__AXI_Protocol_Converter_0__ds_axi_arprot ;
    wire [2:0]        w_port__AXI_Matrix_0__us0_arprot ;
    wire [2:0]        w_net__AXI_Protocol_Converter_0__ds_axi_arprot ; 

    wire              w_port__AXI_Protocol_Converter_0__ds_axi_arvalid ;
    wire              w_port__AXI_Matrix_0__us0_arvalid ;
    wire              w_net__AXI_Protocol_Converter_0__ds_axi_arvalid ; 

    wire [32:0]       w_port__AXI_Protocol_Converter_0__ds_axi_awaddr ;
    wire [32:0]       w_port__AXI_Matrix_0__us0_awaddr ;
    wire [32:0]       w_net__AXI_Protocol_Converter_0__ds_axi_awaddr ; 

    wire [2:0]        w_port__AXI_Protocol_Converter_0__ds_axi_awprot ;
    wire [2:0]        w_port__AXI_Matrix_0__us0_awprot ;
    wire [2:0]        w_net__AXI_Protocol_Converter_0__ds_axi_awprot ; 

    wire              w_port__AXI_Protocol_Converter_0__ds_axi_awvalid ;
    wire              w_port__AXI_Matrix_0__us0_awvalid ;
    wire              w_net__AXI_Protocol_Converter_0__ds_axi_awvalid ; 

    wire              w_port__AXI_Protocol_Converter_0__ds_axi_bready ;
    wire              w_port__AXI_Matrix_0__us0_bready ;
    wire              w_net__AXI_Protocol_Converter_0__ds_axi_bready ; 

    wire              w_port__AXI_Protocol_Converter_0__ds_axi_rready ;
    wire              w_port__AXI_Matrix_0__us0_rready ;
    wire              w_net__AXI_Protocol_Converter_0__ds_axi_rready ; 

    wire [31:0]       w_port__AXI_Protocol_Converter_0__ds_axi_wdata ;
    wire [31:0]       w_port__AXI_Matrix_0__us0_wdata ;
    wire [31:0]       w_net__AXI_Protocol_Converter_0__ds_axi_wdata ; 

    wire [3:0]        w_port__AXI_Protocol_Converter_0__ds_axi_wstrb ;
    wire [3:0]        w_port__AXI_Matrix_0__us0_wstrb ;
    wire [3:0]        w_net__AXI_Protocol_Converter_0__ds_axi_wstrb ; 

    wire              w_port__AXI_Protocol_Converter_0__ds_axi_wvalid ;
    wire              w_port__AXI_Matrix_0__us0_wvalid ;
    wire              w_net__AXI_Protocol_Converter_0__ds_axi_wvalid ; 

    wire              w_port__AXI_Protocol_Converter_0__us_axi_arready ;
    wire              w_port__ARM_Processor_System_0__master_gp0_axi_arready ;
    wire              w_net__AXI_Protocol_Converter_0__us_axi_arready ; 

    wire              w_port__AXI_Protocol_Converter_0__us_axi_awready ;
    wire              w_port__ARM_Processor_System_0__master_gp0_axi_awready ;
    wire              w_net__AXI_Protocol_Converter_0__us_axi_awready ; 

    wire [11:0]       w_port__AXI_Protocol_Converter_0__us_axi_bid ;
    wire [11:0]       w_port__ARM_Processor_System_0__master_gp0_axi_bid ;
    wire [11:0]       w_net__AXI_Protocol_Converter_0__us_axi_bid ; 

    wire [1:0]        w_port__AXI_Protocol_Converter_0__us_axi_bresp ;
    wire [1:0]        w_port__ARM_Processor_System_0__master_gp0_axi_bresp ;
    wire [1:0]        w_net__AXI_Protocol_Converter_0__us_axi_bresp ; 

    wire              w_port__AXI_Protocol_Converter_0__us_axi_bvalid ;
    wire              w_port__ARM_Processor_System_0__master_gp0_axi_bvalid ;
    wire              w_net__AXI_Protocol_Converter_0__us_axi_bvalid ; 

    wire [31:0]       w_port__AXI_Protocol_Converter_0__us_axi_rdata ;
    wire [31:0]       w_port__ARM_Processor_System_0__master_gp0_axi_rdata ;
    wire [31:0]       w_net__AXI_Protocol_Converter_0__us_axi_rdata ; 

    wire [11:0]       w_port__AXI_Protocol_Converter_0__us_axi_rid ;
    wire [11:0]       w_port__ARM_Processor_System_0__master_gp0_axi_rid ;
    wire [11:0]       w_net__AXI_Protocol_Converter_0__us_axi_rid ; 

    wire              w_port__AXI_Protocol_Converter_0__us_axi_rlast ;
    wire              w_port__ARM_Processor_System_0__master_gp0_axi_rlast ;
    wire              w_net__AXI_Protocol_Converter_0__us_axi_rlast ; 

    wire [1:0]        w_port__AXI_Protocol_Converter_0__us_axi_rresp ;
    wire [1:0]        w_port__ARM_Processor_System_0__master_gp0_axi_rresp ;
    wire [1:0]        w_net__AXI_Protocol_Converter_0__us_axi_rresp ; 

    wire              w_port__AXI_Protocol_Converter_0__us_axi_rvalid ;
    wire              w_port__ARM_Processor_System_0__master_gp0_axi_rvalid ;
    wire              w_net__AXI_Protocol_Converter_0__us_axi_rvalid ; 

    wire              w_port__AXI_Protocol_Converter_0__us_axi_wready ;
    wire              w_port__ARM_Processor_System_0__master_gp0_axi_wready ;
    wire              w_net__AXI_Protocol_Converter_0__us_axi_wready ; 

    wire [32:0]       w_port__AXI_Protocol_Converter_1__ds_axi_araddr ;
    wire [32:0]       w_port__Video_NPU_0__s_axilite_araddr_i ;
    wire [32:0]       w_net__AXI_Protocol_Converter_1__ds_axi_araddr ; 

    wire [2:0]        w_port__AXI_Protocol_Converter_1__ds_axi_arprot ;
    wire [2:0]        w_port__Video_NPU_0__s_axilite_arprot_i ;
    wire [2:0]        w_net__AXI_Protocol_Converter_1__ds_axi_arprot ; 

    wire              w_port__AXI_Protocol_Converter_1__ds_axi_arvalid ;
    wire              w_port__Video_NPU_0__s_axilite_arvalid_i ;
    wire              w_net__AXI_Protocol_Converter_1__ds_axi_arvalid ; 

    wire [32:0]       w_port__AXI_Protocol_Converter_1__ds_axi_awaddr ;
    wire [32:0]       w_port__Video_NPU_0__s_axilite_awaddr_i ;
    wire [32:0]       w_net__AXI_Protocol_Converter_1__ds_axi_awaddr ; 

    wire [2:0]        w_port__AXI_Protocol_Converter_1__ds_axi_awprot ;
    wire [2:0]        w_port__Video_NPU_0__s_axilite_awprot_i ;
    wire [2:0]        w_net__AXI_Protocol_Converter_1__ds_axi_awprot ; 

    wire              w_port__AXI_Protocol_Converter_1__ds_axi_awvalid ;
    wire              w_port__Video_NPU_0__s_axilite_awvalid_i ;
    wire              w_net__AXI_Protocol_Converter_1__ds_axi_awvalid ; 

    wire              w_port__AXI_Protocol_Converter_1__ds_axi_bready ;
    wire              w_port__Video_NPU_0__s_axilite_bready_i ;
    wire              w_net__AXI_Protocol_Converter_1__ds_axi_bready ; 

    wire              w_port__AXI_Protocol_Converter_1__ds_axi_rready ;
    wire              w_port__Video_NPU_0__s_axilite_rready_i ;
    wire              w_net__AXI_Protocol_Converter_1__ds_axi_rready ; 

    wire [31:0]       w_port__AXI_Protocol_Converter_1__ds_axi_wdata ;
    wire [31:0]       w_port__Video_NPU_0__s_axilite_wdata_i ;
    wire [31:0]       w_net__AXI_Protocol_Converter_1__ds_axi_wdata ; 

    wire [3:0]        w_port__AXI_Protocol_Converter_1__ds_axi_wstrb ;
    wire [3:0]        w_port__Video_NPU_0__s_axilite_wstrb_i ;
    wire [3:0]        w_net__AXI_Protocol_Converter_1__ds_axi_wstrb ; 

    wire              w_port__AXI_Protocol_Converter_1__ds_axi_wvalid ;
    wire              w_port__Video_NPU_0__s_axilite_wvalid_i ;
    wire              w_net__AXI_Protocol_Converter_1__ds_axi_wvalid ; 

    wire              w_port__AXI_Protocol_Converter_1__us_axi_arready ;
    wire              w_port__AXI_Matrix_1__ds0_arready ;
    wire              w_net__AXI_Protocol_Converter_1__us_axi_arready ; 

    wire              w_port__AXI_Protocol_Converter_1__us_axi_awready ;
    wire              w_port__AXI_Matrix_1__ds0_awready ;
    wire              w_net__AXI_Protocol_Converter_1__us_axi_awready ; 

    wire [12:0]       w_port__AXI_Protocol_Converter_1__us_axi_bid ;
    wire [12:0]       w_port__AXI_Matrix_1__ds0_bid ;
    wire [12:0]       w_net__AXI_Protocol_Converter_1__us_axi_bid ; 

    wire [1:0]        w_port__AXI_Protocol_Converter_1__us_axi_bresp ;
    wire [1:0]        w_port__AXI_Matrix_1__ds0_bresp ;
    wire [1:0]        w_net__AXI_Protocol_Converter_1__us_axi_bresp ; 

    wire              w_port__AXI_Protocol_Converter_1__us_axi_bvalid ;
    wire              w_port__AXI_Matrix_1__ds0_bvalid ;
    wire              w_net__AXI_Protocol_Converter_1__us_axi_bvalid ; 

    wire [31:0]       w_port__AXI_Protocol_Converter_1__us_axi_rdata ;
    wire [31:0]       w_port__AXI_Matrix_1__ds0_rdata ;
    wire [31:0]       w_net__AXI_Protocol_Converter_1__us_axi_rdata ; 

    wire [12:0]       w_port__AXI_Protocol_Converter_1__us_axi_rid ;
    wire [12:0]       w_port__AXI_Matrix_1__ds0_rid ;
    wire [12:0]       w_net__AXI_Protocol_Converter_1__us_axi_rid ; 

    wire              w_port__AXI_Protocol_Converter_1__us_axi_rlast ;
    wire              w_port__AXI_Matrix_1__ds0_rlast ;
    wire              w_net__AXI_Protocol_Converter_1__us_axi_rlast ; 

    wire [1:0]        w_port__AXI_Protocol_Converter_1__us_axi_rresp ;
    wire [1:0]        w_port__AXI_Matrix_1__ds0_rresp ;
    wire [1:0]        w_net__AXI_Protocol_Converter_1__us_axi_rresp ; 

    wire              w_port__AXI_Protocol_Converter_1__us_axi_rvalid ;
    wire              w_port__AXI_Matrix_1__ds0_rvalid ;
    wire              w_net__AXI_Protocol_Converter_1__us_axi_rvalid ; 

    wire              w_port__AXI_Protocol_Converter_1__us_axi_wready ;
    wire              w_port__AXI_Matrix_1__ds0_wready ;
    wire              w_net__AXI_Protocol_Converter_1__us_axi_wready ; 

    wire [15:0]       w_port__Concat_0__Dout ;
    wire [15:0]       w_port__ARM_Processor_System_0__f2p_irq ;
    wire [15:0]       w_net__Concat_0__Dout ; 

    wire              w_port__PLL_3__clk0_out ;
    wire              w_port__uihdmi_tx_0__I_serial_clk ;
    wire              w_net__PLL_3__clk0_out ; 

    wire              w_port__PLL_3__lock ;
    wire [0:0]        w_port__Utility_Vector_Logic_1__vector_a ;
    wire              w_net__PLL_3__lock ; 

    wire              w_port__PLL_npu__clk0_out ;
    wire              w_port__ARM_Processor_System_0__master_gp1_axi_aclk ;
    wire              w_port__pwm_0__clk ;
    wire              w_port__rstn_npu__clk ;
    wire              w_port__AXI_Protocol_Converter_1__aclk ;
    wire              w_port__AXI_Matrix_1__aclk ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_aclk ;
    wire              w_port__Video_NPU_0__S_AXILite_ACLK ;
    wire              w_port__Video_NPU_0__M_AXI_ACLK ;
    wire              w_port__pwm_0_0__clk ;
    wire              w_port__pwm_0_1__clk ;
    wire              w_net__PLL_npu__clk0_out ; 

    wire              w_port__PLL_npu__lock ;
    wire              w_port__rstn_npu__pll_locked ;
    wire              w_net__PLL_npu__lock ; 

    wire [0:0]        w_port__Utility_Vector_Logic_0__result_vector ;
    wire              w_port__PLL_3__reset ;
    wire [0:0]        w_net__Utility_Vector_Logic_0__result_vector ; 

    wire [0:0]        w_port__Utility_Vector_Logic_1__result_vector ;
    wire              w_port__uihdmi_tx_0__I_rst ;
    wire [0:0]        w_net__Utility_Vector_Logic_1__result_vector ; 

    wire              w_port__VDMA_0__axi_lite_arready ;
    wire              w_port__AXI_Matrix_0__ds0_arready ;
    wire              w_net__VDMA_0__axi_lite_arready ; 

    wire              w_port__VDMA_0__axi_lite_awready ;
    wire              w_port__AXI_Matrix_0__ds0_awready ;
    wire              w_net__VDMA_0__axi_lite_awready ; 

    wire [1:0]        w_port__VDMA_0__axi_lite_bresp ;
    wire [1:0]        w_port__AXI_Matrix_0__ds0_bresp ;
    wire [1:0]        w_net__VDMA_0__axi_lite_bresp ; 

    wire              w_port__VDMA_0__axi_lite_bvalid ;
    wire              w_port__AXI_Matrix_0__ds0_bvalid ;
    wire              w_net__VDMA_0__axi_lite_bvalid ; 

    wire [31:0]       w_port__VDMA_0__axi_lite_rdata ;
    wire [31:0]       w_port__AXI_Matrix_0__ds0_rdata ;
    wire [31:0]       w_net__VDMA_0__axi_lite_rdata ; 

    wire [1:0]        w_port__VDMA_0__axi_lite_rresp ;
    wire [1:0]        w_port__AXI_Matrix_0__ds0_rresp ;
    wire [1:0]        w_net__VDMA_0__axi_lite_rresp ; 

    wire              w_port__VDMA_0__axi_lite_rvalid ;
    wire              w_port__AXI_Matrix_0__ds0_rvalid ;
    wire              w_net__VDMA_0__axi_lite_rvalid ; 

    wire              w_port__VDMA_0__axi_lite_wready ;
    wire              w_port__AXI_Matrix_0__ds0_wready ;
    wire              w_net__VDMA_0__axi_lite_wready ; 

    wire [31:0]       w_port__VDMA_0__m_axi_mm2s_araddr ;
    wire [31:0]       w_port__AXI_Matrix_2__us0_araddr ;
    wire [31:0]       w_net__VDMA_0__m_axi_mm2s_araddr ; 

    wire [1:0]        w_port__VDMA_0__m_axi_mm2s_arburst ;
    wire [1:0]        w_port__AXI_Matrix_2__us0_arburst ;
    wire [1:0]        w_net__VDMA_0__m_axi_mm2s_arburst ; 

    wire [3:0]        w_port__VDMA_0__m_axi_mm2s_arcache ;
    wire [3:0]        w_port__AXI_Matrix_2__us0_arcache ;
    wire [3:0]        w_net__VDMA_0__m_axi_mm2s_arcache ; 

    wire [7:0]        w_port__VDMA_0__m_axi_mm2s_arlen ;
    wire [7:0]        w_port__AXI_Matrix_2__us0_arlen ;
    wire [7:0]        w_net__VDMA_0__m_axi_mm2s_arlen ; 

    wire [2:0]        w_port__VDMA_0__m_axi_mm2s_arprot ;
    wire [2:0]        w_port__AXI_Matrix_2__us0_arprot ;
    wire [2:0]        w_net__VDMA_0__m_axi_mm2s_arprot ; 

    wire [2:0]        w_port__VDMA_0__m_axi_mm2s_arsize ;
    wire [2:0]        w_port__AXI_Matrix_2__us0_arsize ;
    wire [2:0]        w_net__VDMA_0__m_axi_mm2s_arsize ; 

    wire              w_port__VDMA_0__m_axi_mm2s_arvalid ;
    wire              w_port__AXI_Matrix_2__us0_arvalid ;
    wire              w_net__VDMA_0__m_axi_mm2s_arvalid ; 

    wire              w_port__VDMA_0__m_axi_mm2s_rready ;
    wire              w_port__AXI_Matrix_2__us0_rready ;
    wire              w_net__VDMA_0__m_axi_mm2s_rready ; 

    wire [23:0]       w_port__VDMA_0__m_axis_mm2s_tdata ;
    wire [23:0]       w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tdata ;
    wire [23:0]       w_net__VDMA_0__m_axis_mm2s_tdata ; 

    wire              w_port__VDMA_0__m_axis_mm2s_tlast ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tlast ;
    wire              w_net__VDMA_0__m_axis_mm2s_tlast ; 

    wire [0:0]        w_port__VDMA_0__m_axis_mm2s_tuser ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tuser ;
    wire [0:0]        w_net__VDMA_0__m_axis_mm2s_tuser ; 

    wire              w_port__VDMA_0__m_axis_mm2s_tvalid ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tvalid ;
    wire              w_net__VDMA_0__m_axis_mm2s_tvalid ; 

    wire              w_port__VDMA_0__mm2s_introut ;
    wire [0:0]        w_port__Concat_0__In2 ;
    wire              w_net__VDMA_0__mm2s_introut ; 

    wire [32:0]       w_port__Video_NPU_0__m_axi_araddr_soft_o ;
    wire [32:0]       w_port__ARM_Processor_System_0__slave_hp0_axi_araddr ;
    wire [32:0]       w_net__Video_NPU_0__m_axi_araddr_soft_o ; 

    wire [1:0]        w_port__Video_NPU_0__m_axi_arburst_soft_o ;
    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_arburst ;
    wire [1:0]        w_net__Video_NPU_0__m_axi_arburst_soft_o ; 

    wire [3:0]        w_port__Video_NPU_0__m_axi_arcache_soft_o ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_arcache ;
    wire [3:0]        w_net__Video_NPU_0__m_axi_arcache_soft_o ; 

    wire [5:0]        w_port__Video_NPU_0__m_axi_arid_soft_o ;
    wire [5:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_arid ;
    wire [5:0]        w_net__Video_NPU_0__m_axi_arid_soft_o ; 

    wire [3:0]        w_port__Video_NPU_0__m_axi_arlen_soft_o ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_arlen ;
    wire [3:0]        w_net__Video_NPU_0__m_axi_arlen_soft_o ; 

    wire              w_port__Video_NPU_0__m_axi_arlock_soft_o ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_arlock ;
    wire              w_net__Video_NPU_0__m_axi_arlock_soft_o ; 

    wire [2:0]        w_port__Video_NPU_0__m_axi_arprot_soft_o ;
    wire [2:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_arprot ;
    wire [2:0]        w_net__Video_NPU_0__m_axi_arprot_soft_o ; 

    wire [1:0]        w_port__Video_NPU_0__m_axi_arsize_soft_o ;
    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_arsize ;
    wire [1:0]        w_net__Video_NPU_0__m_axi_arsize_soft_o ; 

    wire              w_port__Video_NPU_0__m_axi_arvalid_soft_o ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_arvalid ;
    wire              w_net__Video_NPU_0__m_axi_arvalid_soft_o ; 

    wire [32:0]       w_port__Video_NPU_0__m_axi_awaddr_soft_o ;
    wire [32:0]       w_port__ARM_Processor_System_0__slave_hp0_axi_awaddr ;
    wire [32:0]       w_net__Video_NPU_0__m_axi_awaddr_soft_o ; 

    wire [1:0]        w_port__Video_NPU_0__m_axi_awburst_soft_o ;
    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_awburst ;
    wire [1:0]        w_net__Video_NPU_0__m_axi_awburst_soft_o ; 

    wire [3:0]        w_port__Video_NPU_0__m_axi_awcache_soft_o ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_awcache ;
    wire [3:0]        w_net__Video_NPU_0__m_axi_awcache_soft_o ; 

    wire [5:0]        w_port__Video_NPU_0__m_axi_awid_soft_o ;
    wire [5:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_awid ;
    wire [5:0]        w_net__Video_NPU_0__m_axi_awid_soft_o ; 

    wire [3:0]        w_port__Video_NPU_0__m_axi_awlen_soft_o ;
    wire [3:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_awlen ;
    wire [3:0]        w_net__Video_NPU_0__m_axi_awlen_soft_o ; 

    wire              w_port__Video_NPU_0__m_axi_awlock_soft_o ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_awlock ;
    wire              w_net__Video_NPU_0__m_axi_awlock_soft_o ; 

    wire [2:0]        w_port__Video_NPU_0__m_axi_awprot_soft_o ;
    wire [2:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_awprot ;
    wire [2:0]        w_net__Video_NPU_0__m_axi_awprot_soft_o ; 

    wire [1:0]        w_port__Video_NPU_0__m_axi_awsize_soft_o ;
    wire [1:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_awsize ;
    wire [1:0]        w_net__Video_NPU_0__m_axi_awsize_soft_o ; 

    wire              w_port__Video_NPU_0__m_axi_awvalid_soft_o ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_awvalid ;
    wire              w_net__Video_NPU_0__m_axi_awvalid_soft_o ; 

    wire              w_port__Video_NPU_0__m_axi_bready_soft_o ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_bready ;
    wire              w_net__Video_NPU_0__m_axi_bready_soft_o ; 

    wire              w_port__Video_NPU_0__m_axi_rready_soft_o ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_rready ;
    wire              w_net__Video_NPU_0__m_axi_rready_soft_o ; 

    wire [63:0]       w_port__Video_NPU_0__m_axi_wdata_soft_o ;
    wire [63:0]       w_port__ARM_Processor_System_0__slave_hp0_axi_wdata ;
    wire [63:0]       w_net__Video_NPU_0__m_axi_wdata_soft_o ; 

    wire              w_port__Video_NPU_0__m_axi_wlast_soft_o ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_wlast ;
    wire              w_net__Video_NPU_0__m_axi_wlast_soft_o ; 

    wire [7:0]        w_port__Video_NPU_0__m_axi_wstrb_soft_o ;
    wire [7:0]        w_port__ARM_Processor_System_0__slave_hp0_axi_wstrb ;
    wire [7:0]        w_net__Video_NPU_0__m_axi_wstrb_soft_o ; 

    wire              w_port__Video_NPU_0__m_axi_wvalid_soft_o ;
    wire              w_port__ARM_Processor_System_0__slave_hp0_axi_wvalid ;
    wire              w_net__Video_NPU_0__m_axi_wvalid_soft_o ; 

    wire              w_port__Video_NPU_0__npu_soft_intr ;
    wire [0:0]        w_port__Concat_0__In15 ;
    wire              w_net__Video_NPU_0__npu_soft_intr ; 

    wire              w_port__Video_NPU_0__s_axilite_arready_o ;
    wire              w_port__AXI_Protocol_Converter_1__ds_axi_arready ;
    wire              w_net__Video_NPU_0__s_axilite_arready_o ; 

    wire              w_port__Video_NPU_0__s_axilite_awready_o ;
    wire              w_port__AXI_Protocol_Converter_1__ds_axi_awready ;
    wire              w_net__Video_NPU_0__s_axilite_awready_o ; 

    wire [1:0]        w_port__Video_NPU_0__s_axilite_bresp_o ;
    wire [1:0]        w_port__AXI_Protocol_Converter_1__ds_axi_bresp ;
    wire [1:0]        w_net__Video_NPU_0__s_axilite_bresp_o ; 

    wire              w_port__Video_NPU_0__s_axilite_bvalid_o ;
    wire              w_port__AXI_Protocol_Converter_1__ds_axi_bvalid ;
    wire              w_net__Video_NPU_0__s_axilite_bvalid_o ; 

    wire [31:0]       w_port__Video_NPU_0__s_axilite_rdata_o ;
    wire [31:0]       w_port__AXI_Protocol_Converter_1__ds_axi_rdata ;
    wire [31:0]       w_net__Video_NPU_0__s_axilite_rdata_o ; 

    wire [1:0]        w_port__Video_NPU_0__s_axilite_rresp_o ;
    wire [1:0]        w_port__AXI_Protocol_Converter_1__ds_axi_rresp ;
    wire [1:0]        w_net__Video_NPU_0__s_axilite_rresp_o ; 

    wire              w_port__Video_NPU_0__s_axilite_rvalid_o ;
    wire              w_port__AXI_Protocol_Converter_1__ds_axi_rvalid ;
    wire              w_net__Video_NPU_0__s_axilite_rvalid_o ; 

    wire              w_port__Video_NPU_0__s_axilite_wready_o ;
    wire              w_port__AXI_Protocol_Converter_1__ds_axi_wready ;
    wire              w_net__Video_NPU_0__s_axilite_wready_o ; 

    wire [0:0]        w_port__Concat_0__In0 ;
    wire [0:0]        w_net__f2p_irq ; 

    wire [31:0]       w_port__fvdma_ctrl_0__camera_base_addr ;
    wire [31:0]       w_net__fvdma_ctrl_0__camera_base_addr ; 

    wire              w_port__fvdma_ctrl_0__camera_clear ;
    wire              w_net__fvdma_ctrl_0__camera_clear ; 

    wire              w_port__fvdma_ctrl_0__camera_start ;
    wire              w_net__fvdma_ctrl_0__camera_start ; 

    wire              w_port__fvdma_ctrl_0__s_axi_arready ;
    wire              w_port__AXI_Matrix_0__ds2_arready ;
    wire              w_net__fvdma_ctrl_0__s_axi_arready ; 

    wire              w_port__fvdma_ctrl_0__s_axi_awready ;
    wire              w_port__AXI_Matrix_0__ds2_awready ;
    wire              w_net__fvdma_ctrl_0__s_axi_awready ; 

    wire [1:0]        w_port__fvdma_ctrl_0__s_axi_bresp ;
    wire [1:0]        w_port__AXI_Matrix_0__ds2_bresp ;
    wire [1:0]        w_net__fvdma_ctrl_0__s_axi_bresp ; 

    wire              w_port__fvdma_ctrl_0__s_axi_bvalid ;
    wire              w_port__AXI_Matrix_0__ds2_bvalid ;
    wire              w_net__fvdma_ctrl_0__s_axi_bvalid ; 

    wire [31:0]       w_port__fvdma_ctrl_0__s_axi_rdata ;
    wire [31:0]       w_port__AXI_Matrix_0__ds2_rdata ;
    wire [31:0]       w_net__fvdma_ctrl_0__s_axi_rdata ; 

    wire [1:0]        w_port__fvdma_ctrl_0__s_axi_rresp ;
    wire [1:0]        w_port__AXI_Matrix_0__ds2_rresp ;
    wire [1:0]        w_net__fvdma_ctrl_0__s_axi_rresp ; 

    wire              w_port__fvdma_ctrl_0__s_axi_rvalid ;
    wire              w_port__AXI_Matrix_0__ds2_rvalid ;
    wire              w_net__fvdma_ctrl_0__s_axi_rvalid ; 

    wire              w_port__fvdma_ctrl_0__s_axi_wready ;
    wire              w_port__AXI_Matrix_0__ds2_wready ;
    wire              w_net__fvdma_ctrl_0__s_axi_wready ; 

    wire [31:0]       w_port__AXI_Matrix_2__us1_araddr ;
    wire [31:0]       w_net__hp1_w_us1_araddr ; 

    wire [1:0]        w_port__AXI_Matrix_2__us1_arburst ;
    wire [1:0]        w_net__hp1_w_us1_arburst ; 

    wire [3:0]        w_port__AXI_Matrix_2__us1_arcache ;
    wire [3:0]        w_net__hp1_w_us1_arcache ; 

    wire [4:0]        w_port__AXI_Matrix_2__us1_arid ;
    wire [4:0]        w_net__hp1_w_us1_arid ; 

    wire [7:0]        w_port__AXI_Matrix_2__us1_arlen ;
    wire [7:0]        w_net__hp1_w_us1_arlen ; 

    wire [0:0]        w_port__AXI_Matrix_2__us1_arlock ;
    wire [0:0]        w_net__hp1_w_us1_arlock ; 

    wire [2:0]        w_port__AXI_Matrix_2__us1_arprot ;
    wire [2:0]        w_net__hp1_w_us1_arprot ; 

    wire [3:0]        w_port__AXI_Matrix_2__us1_arqos ;
    wire [3:0]        w_net__hp1_w_us1_arqos ; 

    wire [2:0]        w_port__AXI_Matrix_2__us1_arsize ;
    wire [2:0]        w_net__hp1_w_us1_arsize ; 

    wire              w_port__AXI_Matrix_2__us1_arvalid ;
    wire              w_net__hp1_w_us1_arvalid ; 

    wire [31:0]       w_port__AXI_Matrix_2__us1_awaddr ;
    wire [31:0]       w_net__hp1_w_us1_awaddr ; 

    wire [1:0]        w_port__AXI_Matrix_2__us1_awburst ;
    wire [1:0]        w_net__hp1_w_us1_awburst ; 

    wire [3:0]        w_port__AXI_Matrix_2__us1_awcache ;
    wire [3:0]        w_net__hp1_w_us1_awcache ; 

    wire [4:0]        w_port__AXI_Matrix_2__us1_awid ;
    wire [4:0]        w_net__hp1_w_us1_awid ; 

    wire [7:0]        w_port__AXI_Matrix_2__us1_awlen ;
    wire [7:0]        w_net__hp1_w_us1_awlen ; 

    wire [0:0]        w_port__AXI_Matrix_2__us1_awlock ;
    wire [0:0]        w_net__hp1_w_us1_awlock ; 

    wire [2:0]        w_port__AXI_Matrix_2__us1_awprot ;
    wire [2:0]        w_net__hp1_w_us1_awprot ; 

    wire [3:0]        w_port__AXI_Matrix_2__us1_awqos ;
    wire [3:0]        w_net__hp1_w_us1_awqos ; 

    wire [2:0]        w_port__AXI_Matrix_2__us1_awsize ;
    wire [2:0]        w_net__hp1_w_us1_awsize ; 

    wire              w_port__AXI_Matrix_2__us1_awvalid ;
    wire              w_net__hp1_w_us1_awvalid ; 

    wire              w_port__AXI_Matrix_2__us1_bready ;
    wire              w_net__hp1_w_us1_bready ; 

    wire              w_port__AXI_Matrix_2__us1_rready ;
    wire              w_net__hp1_w_us1_rready ; 

    wire [63:0]       w_port__AXI_Matrix_2__us1_wdata ;
    wire [63:0]       w_net__hp1_w_us1_wdata ; 

    wire              w_port__AXI_Matrix_2__us1_wlast ;
    wire              w_net__hp1_w_us1_wlast ; 

    wire [7:0]        w_port__AXI_Matrix_2__us1_wstrb ;
    wire [7:0]        w_net__hp1_w_us1_wstrb ; 

    wire              w_port__AXI_Matrix_2__us1_wvalid ;
    wire              w_net__hp1_w_us1_wvalid ; 

    wire              w_port__ARM_Processor_System_0__i2c0_scl_in ;
    wire              w_net__mipi_iic_i2c0_scl_in ; 

    wire              w_port__ARM_Processor_System_0__i2c0_sda_in ;
    wire              w_net__mipi_iic_i2c0_sda_in ; 

    wire              w_port__pll_150m__clk0_out ;
    wire              w_port__ARM_Processor_System_0__slave_hp1_axi_aclk ;
    wire              w_port__rstn_150m__clk ;
    wire              w_port__VDMA_0__m_axi_mm2s_aclk ;
    wire              w_port__VDMA_0__m_axis_mm2s_aclk ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__aclk ;
    wire              w_port__AXI_Matrix_2__aclk ;
    wire              w_net__pll_150m__clk0_out ; 

    wire              w_port__pll_150m__lock ;
    wire              w_port__rstn_150m__pll_locked ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__aclken ;
    wire              w_net__pll_150m__lock ; 

    wire              w_port__pll_75m__clk0_out ;
    wire              w_port__AXI_Protocol_Converter_0__aclk ;
    wire              w_port__ARM_Processor_System_0__master_gp0_axi_aclk ;
    wire              w_port__AXI_Matrix_0__aclk ;
    wire              w_port__rst_n_75m__clk ;
    wire              w_port__fvdma_ctrl_0__s_axi_aclk ;
    wire              w_port__VDMA_0__s_axi_lite_aclk ;
    wire              w_port__video_timing_generator_v01_0__aclk ;
    wire              w_net__pll_75m__clk0_out ; 

    wire              w_port__pll_75m__lock ;
    wire              w_port__rst_n_75m__pll_locked ;
    wire              w_net__pll_75m__lock ; 

    wire              w_port__pwm_0_0__pwm_out ;
    wire              w_net__pwm_0_0__pwm_out ; 

    wire              w_port__pwm_0_1__pwm_out ;
    wire              w_net__pwm_0_1__pwm_out ; 

    wire              w_port__pwm_0__pwm_out ;
    wire              w_net__pwm_0__pwm_out ; 

    wire [0:0]        w_port__rst_n_75m__interconnect_aresetn ;
    wire              w_port__AXI_Protocol_Converter_0__aresetn ;
    wire              w_port__AXI_Matrix_0__aresetn ;
    wire              w_port__fvdma_ctrl_0__s_axi_aresetn ;
    wire              w_port__VDMA_0__resetn ;
    wire              w_port__video_timing_generator_v01_0__arst_n ;
    wire [0:0]        w_net__rst_n_75m__interconnect_aresetn ; 

    wire [0:0]        w_port__rstn_150m__peripheral_aresetn ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__aresetn ;
    wire              w_port__AXI_Matrix_2__aresetn ;
    wire [0:0]        w_net__rstn_150m__peripheral_aresetn ; 

    wire [0:0]        w_port__rstn_npu__interconnect_aresetn ;
    wire              w_port__pwm_0__rst_n ;
    wire [0:0]        w_net__rstn_npu__interconnect_aresetn ; 

    wire [0:0]        w_port__rstn_npu__peripheral_aresetn ;
    wire              w_port__Video_NPU_0__S_AXILite_AResetn ;
    wire              w_port__Video_NPU_0__M_AXI_AResetn ;
    wire              w_port__AXI_Protocol_Converter_1__aresetn ;
    wire              w_port__AXI_Matrix_1__aresetn ;
    wire [0:0]        w_net__rstn_npu__peripheral_aresetn ; 

    wire              w_port__uihdmi_tx_0__O_hdmi_clk_p ;
    wire              w_net__uihdmi_tx_0__O_hdmi_clk_p ; 

    wire [2:0]        w_port__uihdmi_tx_0__O_hdmi_tx_p ;
    wire [2:0]        w_net__uihdmi_tx_0__O_hdmi_tx_p ; 

    wire              w_port__video_timing_generator_v01_0__s_axi_arready ;
    wire              w_port__AXI_Matrix_0__ds1_arready ;
    wire              w_net__video_timing_generator_v01_0__s_axi_arready ; 

    wire              w_port__video_timing_generator_v01_0__s_axi_awready ;
    wire              w_port__AXI_Matrix_0__ds1_awready ;
    wire              w_net__video_timing_generator_v01_0__s_axi_awready ; 

    wire [1:0]        w_port__video_timing_generator_v01_0__s_axi_bresp ;
    wire [1:0]        w_port__AXI_Matrix_0__ds1_bresp ;
    wire [1:0]        w_net__video_timing_generator_v01_0__s_axi_bresp ; 

    wire              w_port__video_timing_generator_v01_0__s_axi_bvalid ;
    wire              w_port__AXI_Matrix_0__ds1_bvalid ;
    wire              w_net__video_timing_generator_v01_0__s_axi_bvalid ; 

    wire [31:0]       w_port__video_timing_generator_v01_0__s_axi_rdata ;
    wire [31:0]       w_port__AXI_Matrix_0__ds1_rdata ;
    wire [31:0]       w_net__video_timing_generator_v01_0__s_axi_rdata ; 

    wire [1:0]        w_port__video_timing_generator_v01_0__s_axi_rresp ;
    wire [1:0]        w_port__AXI_Matrix_0__ds1_rresp ;
    wire [1:0]        w_net__video_timing_generator_v01_0__s_axi_rresp ; 

    wire              w_port__video_timing_generator_v01_0__s_axi_rvalid ;
    wire              w_port__AXI_Matrix_0__ds1_rvalid ;
    wire              w_net__video_timing_generator_v01_0__s_axi_rvalid ; 

    wire              w_port__video_timing_generator_v01_0__s_axi_wready ;
    wire              w_port__AXI_Matrix_0__ds1_wready ;
    wire              w_net__video_timing_generator_v01_0__s_axi_wready ; 

    wire              w_port__video_timing_generator_v01_0__vtg_active_video ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__vtg_active_video ;
    wire              w_net__video_timing_generator_v01_0__vtg_active_video ; 

    wire              w_port__video_timing_generator_v01_0__vtg_hblank ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__vtg_hblank ;
    wire              w_net__video_timing_generator_v01_0__vtg_hblank ; 

    wire              w_port__video_timing_generator_v01_0__vtg_hsync ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__vtg_hsync ;
    wire              w_net__video_timing_generator_v01_0__vtg_hsync ; 

    wire              w_port__video_timing_generator_v01_0__vtg_pclk ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__vid_io_out_clk ;
    wire              w_port__PLL_3__refclk ;
    wire              w_port__uihdmi_tx_0__I_pixel_clk ;
    wire              w_net__video_timing_generator_v01_0__vtg_pclk ; 

    wire              w_port__video_timing_generator_v01_0__vtg_pclk_locked ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__vid_io_out_ce ;
    wire [0:0]        w_port__Utility_Vector_Logic_0__vector_a ;
    wire              w_port__pwm_0_0__rst_n ;
    wire              w_net__video_timing_generator_v01_0__vtg_pclk_locked ; 

    wire              w_port__video_timing_generator_v01_0__vtg_vblank ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__vtg_vblank ;
    wire              w_net__video_timing_generator_v01_0__vtg_vblank ; 

    wire              w_port__video_timing_generator_v01_0__vtg_vsync ;
    wire              w_port__AXI4_Stream_to_Video_Out_0__vtg_vsync ;
    wire              w_net__video_timing_generator_v01_0__vtg_vsync ; 















    assign w_net__ARM_Processor_System_0__master_gp0_axi_araddr = w_port__ARM_Processor_System_0__master_gp0_axi_araddr ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_araddr = w_net__ARM_Processor_System_0__master_gp0_axi_araddr ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_arburst = w_port__ARM_Processor_System_0__master_gp0_axi_arburst ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_arburst = w_net__ARM_Processor_System_0__master_gp0_axi_arburst ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_arcache = w_port__ARM_Processor_System_0__master_gp0_axi_arcache ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_arcache = w_net__ARM_Processor_System_0__master_gp0_axi_arcache ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_arid = w_port__ARM_Processor_System_0__master_gp0_axi_arid ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_arid = w_net__ARM_Processor_System_0__master_gp0_axi_arid ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_arlen = w_port__ARM_Processor_System_0__master_gp0_axi_arlen ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_arlen = {4'b0,w_net__ARM_Processor_System_0__master_gp0_axi_arlen} ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_arlock = w_port__ARM_Processor_System_0__master_gp0_axi_arlock ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_arlock = w_net__ARM_Processor_System_0__master_gp0_axi_arlock ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_arprot = w_port__ARM_Processor_System_0__master_gp0_axi_arprot ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_arprot = w_net__ARM_Processor_System_0__master_gp0_axi_arprot ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_arsize = w_port__ARM_Processor_System_0__master_gp0_axi_arsize ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_arsize = {1'b0,w_net__ARM_Processor_System_0__master_gp0_axi_arsize} ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_arvalid = w_port__ARM_Processor_System_0__master_gp0_axi_arvalid ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_arvalid = w_net__ARM_Processor_System_0__master_gp0_axi_arvalid ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awaddr = w_port__ARM_Processor_System_0__master_gp0_axi_awaddr ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awaddr = w_net__ARM_Processor_System_0__master_gp0_axi_awaddr ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awburst = w_port__ARM_Processor_System_0__master_gp0_axi_awburst ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awburst = w_net__ARM_Processor_System_0__master_gp0_axi_awburst ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awcache = w_port__ARM_Processor_System_0__master_gp0_axi_awcache ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awcache = w_net__ARM_Processor_System_0__master_gp0_axi_awcache ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awid = w_port__ARM_Processor_System_0__master_gp0_axi_awid ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awid = w_net__ARM_Processor_System_0__master_gp0_axi_awid ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awlen = w_port__ARM_Processor_System_0__master_gp0_axi_awlen ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awlen = {4'b0,w_net__ARM_Processor_System_0__master_gp0_axi_awlen} ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awlock = w_port__ARM_Processor_System_0__master_gp0_axi_awlock ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awlock = w_net__ARM_Processor_System_0__master_gp0_axi_awlock ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awprot = w_port__ARM_Processor_System_0__master_gp0_axi_awprot ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awprot = w_net__ARM_Processor_System_0__master_gp0_axi_awprot ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awsize = w_port__ARM_Processor_System_0__master_gp0_axi_awsize ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awsize = {1'b0,w_net__ARM_Processor_System_0__master_gp0_axi_awsize} ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_awvalid = w_port__ARM_Processor_System_0__master_gp0_axi_awvalid ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_awvalid = w_net__ARM_Processor_System_0__master_gp0_axi_awvalid ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_bready = w_port__ARM_Processor_System_0__master_gp0_axi_bready ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_bready = w_net__ARM_Processor_System_0__master_gp0_axi_bready ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_rready = w_port__ARM_Processor_System_0__master_gp0_axi_rready ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_rready = w_net__ARM_Processor_System_0__master_gp0_axi_rready ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_wdata = w_port__ARM_Processor_System_0__master_gp0_axi_wdata ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_wdata = w_net__ARM_Processor_System_0__master_gp0_axi_wdata ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_wlast = w_port__ARM_Processor_System_0__master_gp0_axi_wlast ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_wlast = w_net__ARM_Processor_System_0__master_gp0_axi_wlast ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_wstrb = w_port__ARM_Processor_System_0__master_gp0_axi_wstrb ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_wstrb = w_net__ARM_Processor_System_0__master_gp0_axi_wstrb ;

    assign w_net__ARM_Processor_System_0__master_gp0_axi_wvalid = w_port__ARM_Processor_System_0__master_gp0_axi_wvalid ;
    assign w_port__AXI_Protocol_Converter_0__us_axi_wvalid = w_net__ARM_Processor_System_0__master_gp0_axi_wvalid ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_araddr = w_port__ARM_Processor_System_0__master_gp1_axi_araddr ;
    assign w_port__AXI_Matrix_1__us0_araddr = w_net__ARM_Processor_System_0__master_gp1_axi_araddr ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_arburst = w_port__ARM_Processor_System_0__master_gp1_axi_arburst ;
    assign w_port__AXI_Matrix_1__us0_arburst = w_net__ARM_Processor_System_0__master_gp1_axi_arburst ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_arcache = w_port__ARM_Processor_System_0__master_gp1_axi_arcache ;
    assign w_port__AXI_Matrix_1__us0_arcache = w_net__ARM_Processor_System_0__master_gp1_axi_arcache ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_arid = w_port__ARM_Processor_System_0__master_gp1_axi_arid ;
    assign w_port__AXI_Matrix_1__us0_arid = w_net__ARM_Processor_System_0__master_gp1_axi_arid ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_arlen = w_port__ARM_Processor_System_0__master_gp1_axi_arlen ;
    assign w_port__AXI_Matrix_1__us0_arlen = {4'b0,w_net__ARM_Processor_System_0__master_gp1_axi_arlen} ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_arlock = w_port__ARM_Processor_System_0__master_gp1_axi_arlock ;
    assign w_port__AXI_Matrix_1__us0_arlock = w_net__ARM_Processor_System_0__master_gp1_axi_arlock ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_arprot = w_port__ARM_Processor_System_0__master_gp1_axi_arprot ;
    assign w_port__AXI_Matrix_1__us0_arprot = w_net__ARM_Processor_System_0__master_gp1_axi_arprot ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_arsize = w_port__ARM_Processor_System_0__master_gp1_axi_arsize ;
    assign w_port__AXI_Matrix_1__us0_arsize = {1'b0,w_net__ARM_Processor_System_0__master_gp1_axi_arsize} ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_arvalid = w_port__ARM_Processor_System_0__master_gp1_axi_arvalid ;
    assign w_port__AXI_Matrix_1__us0_arvalid = w_net__ARM_Processor_System_0__master_gp1_axi_arvalid ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awaddr = w_port__ARM_Processor_System_0__master_gp1_axi_awaddr ;
    assign w_port__AXI_Matrix_1__us0_awaddr = w_net__ARM_Processor_System_0__master_gp1_axi_awaddr ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awburst = w_port__ARM_Processor_System_0__master_gp1_axi_awburst ;
    assign w_port__AXI_Matrix_1__us0_awburst = w_net__ARM_Processor_System_0__master_gp1_axi_awburst ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awcache = w_port__ARM_Processor_System_0__master_gp1_axi_awcache ;
    assign w_port__AXI_Matrix_1__us0_awcache = w_net__ARM_Processor_System_0__master_gp1_axi_awcache ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awid = w_port__ARM_Processor_System_0__master_gp1_axi_awid ;
    assign w_port__AXI_Matrix_1__us0_awid = w_net__ARM_Processor_System_0__master_gp1_axi_awid ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awlen = w_port__ARM_Processor_System_0__master_gp1_axi_awlen ;
    assign w_port__AXI_Matrix_1__us0_awlen = {4'b0,w_net__ARM_Processor_System_0__master_gp1_axi_awlen} ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awlock = w_port__ARM_Processor_System_0__master_gp1_axi_awlock ;
    assign w_port__AXI_Matrix_1__us0_awlock = w_net__ARM_Processor_System_0__master_gp1_axi_awlock ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awprot = w_port__ARM_Processor_System_0__master_gp1_axi_awprot ;
    assign w_port__AXI_Matrix_1__us0_awprot = w_net__ARM_Processor_System_0__master_gp1_axi_awprot ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awsize = w_port__ARM_Processor_System_0__master_gp1_axi_awsize ;
    assign w_port__AXI_Matrix_1__us0_awsize = {1'b0,w_net__ARM_Processor_System_0__master_gp1_axi_awsize} ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_awvalid = w_port__ARM_Processor_System_0__master_gp1_axi_awvalid ;
    assign w_port__AXI_Matrix_1__us0_awvalid = w_net__ARM_Processor_System_0__master_gp1_axi_awvalid ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_bready = w_port__ARM_Processor_System_0__master_gp1_axi_bready ;
    assign w_port__AXI_Matrix_1__us0_bready = w_net__ARM_Processor_System_0__master_gp1_axi_bready ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_rready = w_port__ARM_Processor_System_0__master_gp1_axi_rready ;
    assign w_port__AXI_Matrix_1__us0_rready = w_net__ARM_Processor_System_0__master_gp1_axi_rready ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_wdata = w_port__ARM_Processor_System_0__master_gp1_axi_wdata ;
    assign w_port__AXI_Matrix_1__us0_wdata = w_net__ARM_Processor_System_0__master_gp1_axi_wdata ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_wlast = w_port__ARM_Processor_System_0__master_gp1_axi_wlast ;
    assign w_port__AXI_Matrix_1__us0_wlast = w_net__ARM_Processor_System_0__master_gp1_axi_wlast ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_wstrb = w_port__ARM_Processor_System_0__master_gp1_axi_wstrb ;
    assign w_port__AXI_Matrix_1__us0_wstrb = w_net__ARM_Processor_System_0__master_gp1_axi_wstrb ;

    assign w_net__ARM_Processor_System_0__master_gp1_axi_wvalid = w_port__ARM_Processor_System_0__master_gp1_axi_wvalid ;
    assign w_port__AXI_Matrix_1__us0_wvalid = w_net__ARM_Processor_System_0__master_gp1_axi_wvalid ;

    assign w_net__ARM_Processor_System_0__p2f_clk0 = w_port__ARM_Processor_System_0__p2f_clk0 ;
    assign w_port__pll_75m__refclk = w_net__ARM_Processor_System_0__p2f_clk0 ;
    assign w_port__PLL_npu__refclk = w_net__ARM_Processor_System_0__p2f_clk0 ;
    assign w_port__pll_150m__refclk = w_net__ARM_Processor_System_0__p2f_clk0 ;
    assign w_port__video_timing_generator_v01_0__ref_clk = w_net__pll_75m__clk0_out ;
    assign p2f_clk0_50m = w_net__ARM_Processor_System_0__p2f_clk0 ;

    assign w_net__ARM_Processor_System_0__p2f_rst0_n = w_port__ARM_Processor_System_0__p2f_rst0_n ;
    assign w_port__rst_n_75m__aux_rst = w_net__ARM_Processor_System_0__p2f_rst0_n ;
    assign w_port__rstn_150m__aux_rst = w_net__ARM_Processor_System_0__p2f_rst0_n ;
    assign w_port__rstn_npu__aux_rst = w_net__ARM_Processor_System_0__p2f_rst0_n ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_arready = w_port__ARM_Processor_System_0__slave_hp0_axi_arready ;
    assign w_port__Video_NPU_0__m_axi_arready_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_arready ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_awready = w_port__ARM_Processor_System_0__slave_hp0_axi_awready ;
    assign w_port__Video_NPU_0__m_axi_awready_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_awready ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_bid = w_port__ARM_Processor_System_0__slave_hp0_axi_bid ;
    assign w_port__Video_NPU_0__m_axi_bid_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_bid ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_bresp = w_port__ARM_Processor_System_0__slave_hp0_axi_bresp ;
    assign w_port__Video_NPU_0__m_axi_bresp_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_bresp ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_bvalid = w_port__ARM_Processor_System_0__slave_hp0_axi_bvalid ;
    assign w_port__Video_NPU_0__m_axi_bvalid_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_bvalid ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_rdata = w_port__ARM_Processor_System_0__slave_hp0_axi_rdata ;
    assign w_port__Video_NPU_0__m_axi_rdata_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_rdata ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_rid = w_port__ARM_Processor_System_0__slave_hp0_axi_rid ;
    assign w_port__Video_NPU_0__m_axi_rid_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_rid ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_rlast = w_port__ARM_Processor_System_0__slave_hp0_axi_rlast ;
    assign w_port__Video_NPU_0__m_axi_rlast_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_rlast ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_rresp = w_port__ARM_Processor_System_0__slave_hp0_axi_rresp ;
    assign w_port__Video_NPU_0__m_axi_rresp_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_rresp ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_rvalid = w_port__ARM_Processor_System_0__slave_hp0_axi_rvalid ;
    assign w_port__Video_NPU_0__m_axi_rvalid_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_rvalid ;

    assign w_net__ARM_Processor_System_0__slave_hp0_axi_wready = w_port__ARM_Processor_System_0__slave_hp0_axi_wready ;
    assign w_port__Video_NPU_0__m_axi_wready_soft_i = w_net__ARM_Processor_System_0__slave_hp0_axi_wready ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_arready = w_port__ARM_Processor_System_0__slave_hp1_axi_arready ;
    assign w_port__AXI_Matrix_2__ds0_arready = w_net__ARM_Processor_System_0__slave_hp1_axi_arready ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_awready = w_port__ARM_Processor_System_0__slave_hp1_axi_awready ;
    assign w_port__AXI_Matrix_2__ds0_awready = w_net__ARM_Processor_System_0__slave_hp1_axi_awready ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_bid = w_port__ARM_Processor_System_0__slave_hp1_axi_bid ;
    assign w_port__AXI_Matrix_2__ds0_bid = w_net__ARM_Processor_System_0__slave_hp1_axi_bid ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_bresp = w_port__ARM_Processor_System_0__slave_hp1_axi_bresp ;
    assign w_port__AXI_Matrix_2__ds0_bresp = w_net__ARM_Processor_System_0__slave_hp1_axi_bresp ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_bvalid = w_port__ARM_Processor_System_0__slave_hp1_axi_bvalid ;
    assign w_port__AXI_Matrix_2__ds0_bvalid = w_net__ARM_Processor_System_0__slave_hp1_axi_bvalid ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_rdata = w_port__ARM_Processor_System_0__slave_hp1_axi_rdata ;
    assign w_port__AXI_Matrix_2__ds0_rdata = w_net__ARM_Processor_System_0__slave_hp1_axi_rdata ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_rid = w_port__ARM_Processor_System_0__slave_hp1_axi_rid ;
    assign w_port__AXI_Matrix_2__ds0_rid = w_net__ARM_Processor_System_0__slave_hp1_axi_rid ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_rlast = w_port__ARM_Processor_System_0__slave_hp1_axi_rlast ;
    assign w_port__AXI_Matrix_2__ds0_rlast = w_net__ARM_Processor_System_0__slave_hp1_axi_rlast ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_rresp = w_port__ARM_Processor_System_0__slave_hp1_axi_rresp ;
    assign w_port__AXI_Matrix_2__ds0_rresp = w_net__ARM_Processor_System_0__slave_hp1_axi_rresp ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_rvalid = w_port__ARM_Processor_System_0__slave_hp1_axi_rvalid ;
    assign w_port__AXI_Matrix_2__ds0_rvalid = w_net__ARM_Processor_System_0__slave_hp1_axi_rvalid ;

    assign w_net__ARM_Processor_System_0__slave_hp1_axi_wready = w_port__ARM_Processor_System_0__slave_hp1_axi_wready ;
    assign w_port__AXI_Matrix_2__ds0_wready = w_net__ARM_Processor_System_0__slave_hp1_axi_wready ;

    assign w_net__AXI4_Stream_to_Video_Out_0__locked = w_port__AXI4_Stream_to_Video_Out_0__locked ;
    assign w_port__pwm_0_1__rst_n = w_net__AXI4_Stream_to_Video_Out_0__locked ;

    assign w_net__AXI4_Stream_to_Video_Out_0__s_axis_video_tready = w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tready ;
    assign w_port__VDMA_0__m_axis_mm2s_tready = w_net__AXI4_Stream_to_Video_Out_0__s_axis_video_tready ;

    assign w_net__AXI4_Stream_to_Video_Out_0__vid_active_video = w_port__AXI4_Stream_to_Video_Out_0__vid_active_video ;
    assign w_port__uihdmi_tx_0__I_video_in_de = w_net__AXI4_Stream_to_Video_Out_0__vid_active_video ;

    assign w_net__AXI4_Stream_to_Video_Out_0__vid_data = w_port__AXI4_Stream_to_Video_Out_0__vid_data ;
    assign w_port__uihdmi_tx_0__I_video_in_data = w_net__AXI4_Stream_to_Video_Out_0__vid_data ;

    assign w_net__AXI4_Stream_to_Video_Out_0__vid_hsync = w_port__AXI4_Stream_to_Video_Out_0__vid_hsync ;
    assign w_port__uihdmi_tx_0__I_video_in_hs = w_net__AXI4_Stream_to_Video_Out_0__vid_hsync ;

    assign w_net__AXI4_Stream_to_Video_Out_0__vid_vsync = w_port__AXI4_Stream_to_Video_Out_0__vid_vsync ;
    assign w_port__uihdmi_tx_0__I_video_in_vs = w_net__AXI4_Stream_to_Video_Out_0__vid_vsync ;

    assign w_net__AXI4_Stream_to_Video_Out_0__vtg_ce = w_port__AXI4_Stream_to_Video_Out_0__vtg_ce ;
    assign w_port__video_timing_generator_v01_0__vtg_ce = w_net__AXI4_Stream_to_Video_Out_0__vtg_ce ;

    assign w_net__AXI_Matrix_0__ds0_araddr = w_port__AXI_Matrix_0__ds0_araddr ;
    assign w_port__VDMA_0__axi_lite_araddr = w_net__AXI_Matrix_0__ds0_araddr ;

    assign w_net__AXI_Matrix_0__ds0_arvalid = w_port__AXI_Matrix_0__ds0_arvalid ;
    assign w_port__VDMA_0__axi_lite_arvalid = w_net__AXI_Matrix_0__ds0_arvalid ;

    assign w_net__AXI_Matrix_0__ds0_awaddr = w_port__AXI_Matrix_0__ds0_awaddr ;
    assign w_port__VDMA_0__axi_lite_awaddr = w_net__AXI_Matrix_0__ds0_awaddr ;

    assign w_net__AXI_Matrix_0__ds0_awvalid = w_port__AXI_Matrix_0__ds0_awvalid ;
    assign w_port__VDMA_0__axi_lite_awvalid = w_net__AXI_Matrix_0__ds0_awvalid ;

    assign w_net__AXI_Matrix_0__ds0_bready = w_port__AXI_Matrix_0__ds0_bready ;
    assign w_port__VDMA_0__axi_lite_bready = w_net__AXI_Matrix_0__ds0_bready ;

    assign w_net__AXI_Matrix_0__ds0_rready = w_port__AXI_Matrix_0__ds0_rready ;
    assign w_port__VDMA_0__axi_lite_rready = w_net__AXI_Matrix_0__ds0_rready ;

    assign w_net__AXI_Matrix_0__ds0_wdata = w_port__AXI_Matrix_0__ds0_wdata ;
    assign w_port__VDMA_0__axi_lite_wdata = w_net__AXI_Matrix_0__ds0_wdata ;

    assign w_net__AXI_Matrix_0__ds0_wvalid = w_port__AXI_Matrix_0__ds0_wvalid ;
    assign w_port__VDMA_0__axi_lite_wvalid = w_net__AXI_Matrix_0__ds0_wvalid ;

    assign w_net__AXI_Matrix_0__ds1_araddr = w_port__AXI_Matrix_0__ds1_araddr ;
    assign w_port__video_timing_generator_v01_0__s_axi_araddr = w_net__AXI_Matrix_0__ds1_araddr ;

    assign w_net__AXI_Matrix_0__ds1_arvalid = w_port__AXI_Matrix_0__ds1_arvalid ;
    assign w_port__video_timing_generator_v01_0__s_axi_arvalid = w_net__AXI_Matrix_0__ds1_arvalid ;

    assign w_net__AXI_Matrix_0__ds1_awaddr = w_port__AXI_Matrix_0__ds1_awaddr ;
    assign w_port__video_timing_generator_v01_0__s_axi_awaddr = w_net__AXI_Matrix_0__ds1_awaddr ;

    assign w_net__AXI_Matrix_0__ds1_awvalid = w_port__AXI_Matrix_0__ds1_awvalid ;
    assign w_port__video_timing_generator_v01_0__s_axi_awvalid = w_net__AXI_Matrix_0__ds1_awvalid ;

    assign w_net__AXI_Matrix_0__ds1_bready = w_port__AXI_Matrix_0__ds1_bready ;
    assign w_port__video_timing_generator_v01_0__s_axi_bready = w_net__AXI_Matrix_0__ds1_bready ;

    assign w_net__AXI_Matrix_0__ds1_rready = w_port__AXI_Matrix_0__ds1_rready ;
    assign w_port__video_timing_generator_v01_0__s_axi_rready = w_net__AXI_Matrix_0__ds1_rready ;

    assign w_net__AXI_Matrix_0__ds1_wdata = w_port__AXI_Matrix_0__ds1_wdata ;
    assign w_port__video_timing_generator_v01_0__s_axi_wdata = w_net__AXI_Matrix_0__ds1_wdata ;

    assign w_net__AXI_Matrix_0__ds1_wstrb = w_port__AXI_Matrix_0__ds1_wstrb ;
    assign w_port__video_timing_generator_v01_0__s_axi_wstrb = w_net__AXI_Matrix_0__ds1_wstrb ;

    assign w_net__AXI_Matrix_0__ds1_wvalid = w_port__AXI_Matrix_0__ds1_wvalid ;
    assign w_port__video_timing_generator_v01_0__s_axi_wvalid = w_net__AXI_Matrix_0__ds1_wvalid ;

    assign w_net__AXI_Matrix_0__ds2_araddr = w_port__AXI_Matrix_0__ds2_araddr ;
    assign w_port__fvdma_ctrl_0__s_axi_araddr = w_net__AXI_Matrix_0__ds2_araddr ;

    assign w_net__AXI_Matrix_0__ds2_arprot = w_port__AXI_Matrix_0__ds2_arprot ;
    assign w_port__fvdma_ctrl_0__s_axi_arprot = w_net__AXI_Matrix_0__ds2_arprot ;

    assign w_net__AXI_Matrix_0__ds2_arvalid = w_port__AXI_Matrix_0__ds2_arvalid ;
    assign w_port__fvdma_ctrl_0__s_axi_arvalid = w_net__AXI_Matrix_0__ds2_arvalid ;

    assign w_net__AXI_Matrix_0__ds2_awaddr = w_port__AXI_Matrix_0__ds2_awaddr ;
    assign w_port__fvdma_ctrl_0__s_axi_awaddr = w_net__AXI_Matrix_0__ds2_awaddr ;

    assign w_net__AXI_Matrix_0__ds2_awprot = w_port__AXI_Matrix_0__ds2_awprot ;
    assign w_port__fvdma_ctrl_0__s_axi_awprot = w_net__AXI_Matrix_0__ds2_awprot ;

    assign w_net__AXI_Matrix_0__ds2_awvalid = w_port__AXI_Matrix_0__ds2_awvalid ;
    assign w_port__fvdma_ctrl_0__s_axi_awvalid = w_net__AXI_Matrix_0__ds2_awvalid ;

    assign w_net__AXI_Matrix_0__ds2_bready = w_port__AXI_Matrix_0__ds2_bready ;
    assign w_port__fvdma_ctrl_0__s_axi_bready = w_net__AXI_Matrix_0__ds2_bready ;

    assign w_net__AXI_Matrix_0__ds2_rready = w_port__AXI_Matrix_0__ds2_rready ;
    assign w_port__fvdma_ctrl_0__s_axi_rready = w_net__AXI_Matrix_0__ds2_rready ;

    assign w_net__AXI_Matrix_0__ds2_wdata = w_port__AXI_Matrix_0__ds2_wdata ;
    assign w_port__fvdma_ctrl_0__s_axi_wdata = w_net__AXI_Matrix_0__ds2_wdata ;

    assign w_net__AXI_Matrix_0__ds2_wstrb = w_port__AXI_Matrix_0__ds2_wstrb ;
    assign w_port__fvdma_ctrl_0__s_axi_wstrb = w_net__AXI_Matrix_0__ds2_wstrb ;

    assign w_net__AXI_Matrix_0__ds2_wvalid = w_port__AXI_Matrix_0__ds2_wvalid ;
    assign w_port__fvdma_ctrl_0__s_axi_wvalid = w_net__AXI_Matrix_0__ds2_wvalid ;

    assign w_net__AXI_Matrix_0__us0_arready = w_port__AXI_Matrix_0__us0_arready ;
    assign w_port__AXI_Protocol_Converter_0__ds_axi_arready = w_net__AXI_Matrix_0__us0_arready ;

    assign w_net__AXI_Matrix_0__us0_awready = w_port__AXI_Matrix_0__us0_awready ;
    assign w_port__AXI_Protocol_Converter_0__ds_axi_awready = w_net__AXI_Matrix_0__us0_awready ;

    assign w_net__AXI_Matrix_0__us0_bresp = w_port__AXI_Matrix_0__us0_bresp ;
    assign w_port__AXI_Protocol_Converter_0__ds_axi_bresp = w_net__AXI_Matrix_0__us0_bresp ;

    assign w_net__AXI_Matrix_0__us0_bvalid = w_port__AXI_Matrix_0__us0_bvalid ;
    assign w_port__AXI_Protocol_Converter_0__ds_axi_bvalid = w_net__AXI_Matrix_0__us0_bvalid ;

    assign w_net__AXI_Matrix_0__us0_rdata = w_port__AXI_Matrix_0__us0_rdata ;
    assign w_port__AXI_Protocol_Converter_0__ds_axi_rdata = w_net__AXI_Matrix_0__us0_rdata ;

    assign w_net__AXI_Matrix_0__us0_rresp = w_port__AXI_Matrix_0__us0_rresp ;
    assign w_port__AXI_Protocol_Converter_0__ds_axi_rresp = w_net__AXI_Matrix_0__us0_rresp ;

    assign w_net__AXI_Matrix_0__us0_rvalid = w_port__AXI_Matrix_0__us0_rvalid ;
    assign w_port__AXI_Protocol_Converter_0__ds_axi_rvalid = w_net__AXI_Matrix_0__us0_rvalid ;

    assign w_net__AXI_Matrix_0__us0_wready = w_port__AXI_Matrix_0__us0_wready ;
    assign w_port__AXI_Protocol_Converter_0__ds_axi_wready = w_net__AXI_Matrix_0__us0_wready ;

    assign w_net__AXI_Matrix_1__ds0_araddr = w_port__AXI_Matrix_1__ds0_araddr ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_araddr = w_net__AXI_Matrix_1__ds0_araddr ;

    assign w_net__AXI_Matrix_1__ds0_arburst = w_port__AXI_Matrix_1__ds0_arburst ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arburst = w_net__AXI_Matrix_1__ds0_arburst ;

    assign w_net__AXI_Matrix_1__ds0_arcache = w_port__AXI_Matrix_1__ds0_arcache ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arcache = w_net__AXI_Matrix_1__ds0_arcache ;

    assign w_net__AXI_Matrix_1__ds0_arid = w_port__AXI_Matrix_1__ds0_arid ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arid = w_net__AXI_Matrix_1__ds0_arid ;

    assign w_net__AXI_Matrix_1__ds0_arlen = w_port__AXI_Matrix_1__ds0_arlen ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arlen = w_net__AXI_Matrix_1__ds0_arlen ;

    assign w_net__AXI_Matrix_1__ds0_arlock = w_port__AXI_Matrix_1__ds0_arlock ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arlock = w_net__AXI_Matrix_1__ds0_arlock ;

    assign w_net__AXI_Matrix_1__ds0_arprot = w_port__AXI_Matrix_1__ds0_arprot ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arprot = w_net__AXI_Matrix_1__ds0_arprot ;

    assign w_net__AXI_Matrix_1__ds0_arqos = w_port__AXI_Matrix_1__ds0_arqos ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arqos = w_net__AXI_Matrix_1__ds0_arqos ;

    assign w_net__AXI_Matrix_1__ds0_arsize = w_port__AXI_Matrix_1__ds0_arsize ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arsize = w_net__AXI_Matrix_1__ds0_arsize ;

    assign w_net__AXI_Matrix_1__ds0_arvalid = w_port__AXI_Matrix_1__ds0_arvalid ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_arvalid = w_net__AXI_Matrix_1__ds0_arvalid ;

    assign w_net__AXI_Matrix_1__ds0_awaddr = w_port__AXI_Matrix_1__ds0_awaddr ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awaddr = w_net__AXI_Matrix_1__ds0_awaddr ;

    assign w_net__AXI_Matrix_1__ds0_awburst = w_port__AXI_Matrix_1__ds0_awburst ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awburst = w_net__AXI_Matrix_1__ds0_awburst ;

    assign w_net__AXI_Matrix_1__ds0_awcache = w_port__AXI_Matrix_1__ds0_awcache ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awcache = w_net__AXI_Matrix_1__ds0_awcache ;

    assign w_net__AXI_Matrix_1__ds0_awid = w_port__AXI_Matrix_1__ds0_awid ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awid = w_net__AXI_Matrix_1__ds0_awid ;

    assign w_net__AXI_Matrix_1__ds0_awlen = w_port__AXI_Matrix_1__ds0_awlen ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awlen = w_net__AXI_Matrix_1__ds0_awlen ;

    assign w_net__AXI_Matrix_1__ds0_awlock = w_port__AXI_Matrix_1__ds0_awlock ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awlock = w_net__AXI_Matrix_1__ds0_awlock ;

    assign w_net__AXI_Matrix_1__ds0_awprot = w_port__AXI_Matrix_1__ds0_awprot ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awprot = w_net__AXI_Matrix_1__ds0_awprot ;

    assign w_net__AXI_Matrix_1__ds0_awqos = w_port__AXI_Matrix_1__ds0_awqos ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awqos = w_net__AXI_Matrix_1__ds0_awqos ;

    assign w_net__AXI_Matrix_1__ds0_awsize = w_port__AXI_Matrix_1__ds0_awsize ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awsize = w_net__AXI_Matrix_1__ds0_awsize ;

    assign w_net__AXI_Matrix_1__ds0_awvalid = w_port__AXI_Matrix_1__ds0_awvalid ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_awvalid = w_net__AXI_Matrix_1__ds0_awvalid ;

    assign w_net__AXI_Matrix_1__ds0_bready = w_port__AXI_Matrix_1__ds0_bready ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_bready = w_net__AXI_Matrix_1__ds0_bready ;

    assign w_net__AXI_Matrix_1__ds0_rready = w_port__AXI_Matrix_1__ds0_rready ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_rready = w_net__AXI_Matrix_1__ds0_rready ;

    assign w_net__AXI_Matrix_1__ds0_wdata = w_port__AXI_Matrix_1__ds0_wdata ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_wdata = w_net__AXI_Matrix_1__ds0_wdata ;

    assign w_net__AXI_Matrix_1__ds0_wlast = w_port__AXI_Matrix_1__ds0_wlast ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_wlast = w_net__AXI_Matrix_1__ds0_wlast ;

    assign w_net__AXI_Matrix_1__ds0_wstrb = w_port__AXI_Matrix_1__ds0_wstrb ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_wstrb = w_net__AXI_Matrix_1__ds0_wstrb ;

    assign w_net__AXI_Matrix_1__ds0_wvalid = w_port__AXI_Matrix_1__ds0_wvalid ;
    assign w_port__AXI_Protocol_Converter_1__us_axi_wvalid = w_net__AXI_Matrix_1__ds0_wvalid ;

    assign w_net__AXI_Matrix_1__us0_arready = w_port__AXI_Matrix_1__us0_arready ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_arready = w_net__AXI_Matrix_1__us0_arready ;

    assign w_net__AXI_Matrix_1__us0_awready = w_port__AXI_Matrix_1__us0_awready ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_awready = w_net__AXI_Matrix_1__us0_awready ;

    assign w_net__AXI_Matrix_1__us0_bid = w_port__AXI_Matrix_1__us0_bid ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_bid = w_net__AXI_Matrix_1__us0_bid ;

    assign w_net__AXI_Matrix_1__us0_bresp = w_port__AXI_Matrix_1__us0_bresp ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_bresp = w_net__AXI_Matrix_1__us0_bresp ;

    assign w_net__AXI_Matrix_1__us0_bvalid = w_port__AXI_Matrix_1__us0_bvalid ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_bvalid = w_net__AXI_Matrix_1__us0_bvalid ;

    assign w_net__AXI_Matrix_1__us0_rdata = w_port__AXI_Matrix_1__us0_rdata ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_rdata = w_net__AXI_Matrix_1__us0_rdata ;

    assign w_net__AXI_Matrix_1__us0_rid = w_port__AXI_Matrix_1__us0_rid ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_rid = w_net__AXI_Matrix_1__us0_rid ;

    assign w_net__AXI_Matrix_1__us0_rlast = w_port__AXI_Matrix_1__us0_rlast ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_rlast = w_net__AXI_Matrix_1__us0_rlast ;

    assign w_net__AXI_Matrix_1__us0_rresp = w_port__AXI_Matrix_1__us0_rresp ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_rresp = w_net__AXI_Matrix_1__us0_rresp ;

    assign w_net__AXI_Matrix_1__us0_rvalid = w_port__AXI_Matrix_1__us0_rvalid ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_rvalid = w_net__AXI_Matrix_1__us0_rvalid ;

    assign w_net__AXI_Matrix_1__us0_wready = w_port__AXI_Matrix_1__us0_wready ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_wready = w_net__AXI_Matrix_1__us0_wready ;

    assign w_net__AXI_Matrix_2__ds0_araddr = w_port__AXI_Matrix_2__ds0_araddr ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_araddr = {1'b0,w_net__AXI_Matrix_2__ds0_araddr} ;

    assign w_net__AXI_Matrix_2__ds0_arburst = w_port__AXI_Matrix_2__ds0_arburst ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arburst = w_net__AXI_Matrix_2__ds0_arburst ;

    assign w_net__AXI_Matrix_2__ds0_arcache = w_port__AXI_Matrix_2__ds0_arcache ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arcache = w_net__AXI_Matrix_2__ds0_arcache ;

    assign w_net__AXI_Matrix_2__ds0_arid = w_port__AXI_Matrix_2__ds0_arid ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arid = w_net__AXI_Matrix_2__ds0_arid ;

    assign w_net__AXI_Matrix_2__ds0_arlen = w_port__AXI_Matrix_2__ds0_arlen ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arlen = w_net__AXI_Matrix_2__ds0_arlen ;

    assign w_net__AXI_Matrix_2__ds0_arlock = w_port__AXI_Matrix_2__ds0_arlock ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arlock = w_net__AXI_Matrix_2__ds0_arlock ;

    assign w_net__AXI_Matrix_2__ds0_arprot = w_port__AXI_Matrix_2__ds0_arprot ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arprot = w_net__AXI_Matrix_2__ds0_arprot ;

    assign w_net__AXI_Matrix_2__ds0_arqos = w_port__AXI_Matrix_2__ds0_arqos ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arqos = w_net__AXI_Matrix_2__ds0_arqos ;

    assign w_net__AXI_Matrix_2__ds0_arsize = w_port__AXI_Matrix_2__ds0_arsize ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arsize = w_net__AXI_Matrix_2__ds0_arsize ;

    assign w_net__AXI_Matrix_2__ds0_arvalid = w_port__AXI_Matrix_2__ds0_arvalid ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_arvalid = w_net__AXI_Matrix_2__ds0_arvalid ;

    assign w_net__AXI_Matrix_2__ds0_awaddr = w_port__AXI_Matrix_2__ds0_awaddr ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awaddr = {1'b0,w_net__AXI_Matrix_2__ds0_awaddr} ;

    assign w_net__AXI_Matrix_2__ds0_awburst = w_port__AXI_Matrix_2__ds0_awburst ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awburst = w_net__AXI_Matrix_2__ds0_awburst ;

    assign w_net__AXI_Matrix_2__ds0_awcache = w_port__AXI_Matrix_2__ds0_awcache ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awcache = w_net__AXI_Matrix_2__ds0_awcache ;

    assign w_net__AXI_Matrix_2__ds0_awid = w_port__AXI_Matrix_2__ds0_awid ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awid = w_net__AXI_Matrix_2__ds0_awid ;

    assign w_net__AXI_Matrix_2__ds0_awlen = w_port__AXI_Matrix_2__ds0_awlen ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awlen = w_net__AXI_Matrix_2__ds0_awlen ;

    assign w_net__AXI_Matrix_2__ds0_awlock = w_port__AXI_Matrix_2__ds0_awlock ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awlock = w_net__AXI_Matrix_2__ds0_awlock ;

    assign w_net__AXI_Matrix_2__ds0_awprot = w_port__AXI_Matrix_2__ds0_awprot ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awprot = w_net__AXI_Matrix_2__ds0_awprot ;

    assign w_net__AXI_Matrix_2__ds0_awqos = w_port__AXI_Matrix_2__ds0_awqos ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awqos = w_net__AXI_Matrix_2__ds0_awqos ;

    assign w_net__AXI_Matrix_2__ds0_awsize = w_port__AXI_Matrix_2__ds0_awsize ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awsize = w_net__AXI_Matrix_2__ds0_awsize ;

    assign w_net__AXI_Matrix_2__ds0_awvalid = w_port__AXI_Matrix_2__ds0_awvalid ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_awvalid = w_net__AXI_Matrix_2__ds0_awvalid ;

    assign w_net__AXI_Matrix_2__ds0_bready = w_port__AXI_Matrix_2__ds0_bready ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_bready = w_net__AXI_Matrix_2__ds0_bready ;

    assign w_net__AXI_Matrix_2__ds0_rready = w_port__AXI_Matrix_2__ds0_rready ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_rready = w_net__AXI_Matrix_2__ds0_rready ;

    assign w_net__AXI_Matrix_2__ds0_wdata = w_port__AXI_Matrix_2__ds0_wdata ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_wdata = w_net__AXI_Matrix_2__ds0_wdata ;

    assign w_net__AXI_Matrix_2__ds0_wlast = w_port__AXI_Matrix_2__ds0_wlast ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_wlast = w_net__AXI_Matrix_2__ds0_wlast ;

    assign w_net__AXI_Matrix_2__ds0_wstrb = w_port__AXI_Matrix_2__ds0_wstrb ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_wstrb = w_net__AXI_Matrix_2__ds0_wstrb ;

    assign w_net__AXI_Matrix_2__ds0_wvalid = w_port__AXI_Matrix_2__ds0_wvalid ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_wvalid = w_net__AXI_Matrix_2__ds0_wvalid ;

    assign w_net__AXI_Matrix_2__us0_arready = w_port__AXI_Matrix_2__us0_arready ;
    assign w_port__VDMA_0__m_axi_mm2s_arready = w_net__AXI_Matrix_2__us0_arready ;

    assign w_net__AXI_Matrix_2__us0_rdata = w_port__AXI_Matrix_2__us0_rdata ;
    assign w_port__VDMA_0__m_axi_mm2s_rdata = w_net__AXI_Matrix_2__us0_rdata ;

    assign w_net__AXI_Matrix_2__us0_rlast = w_port__AXI_Matrix_2__us0_rlast ;
    assign w_port__VDMA_0__m_axi_mm2s_rlast = w_net__AXI_Matrix_2__us0_rlast ;

    assign w_net__AXI_Matrix_2__us0_rresp = w_port__AXI_Matrix_2__us0_rresp ;
    assign w_port__VDMA_0__m_axi_mm2s_rresp = w_net__AXI_Matrix_2__us0_rresp ;

    assign w_net__AXI_Matrix_2__us0_rvalid = w_port__AXI_Matrix_2__us0_rvalid ;
    assign w_port__VDMA_0__m_axi_mm2s_rvalid = w_net__AXI_Matrix_2__us0_rvalid ;

    assign w_net__AXI_Matrix_2__us1_arready = w_port__AXI_Matrix_2__us1_arready ;
    assign hp1_w_us1_arready = w_net__AXI_Matrix_2__us1_arready ;

    assign w_net__AXI_Matrix_2__us1_awready = w_port__AXI_Matrix_2__us1_awready ;
    assign hp1_w_us1_awready = w_net__AXI_Matrix_2__us1_awready ;

    assign w_net__AXI_Matrix_2__us1_bid = w_port__AXI_Matrix_2__us1_bid ;
    assign hp1_w_us1_bid = w_net__AXI_Matrix_2__us1_bid ;

    assign w_net__AXI_Matrix_2__us1_bresp = w_port__AXI_Matrix_2__us1_bresp ;
    assign hp1_w_us1_bresp = w_net__AXI_Matrix_2__us1_bresp ;

    assign w_net__AXI_Matrix_2__us1_bvalid = w_port__AXI_Matrix_2__us1_bvalid ;
    assign hp1_w_us1_bvalid = w_net__AXI_Matrix_2__us1_bvalid ;

    assign w_net__AXI_Matrix_2__us1_rdata = w_port__AXI_Matrix_2__us1_rdata ;
    assign hp1_w_us1_rdata = w_net__AXI_Matrix_2__us1_rdata ;

    assign w_net__AXI_Matrix_2__us1_rid = w_port__AXI_Matrix_2__us1_rid ;
    assign hp1_w_us1_rid = w_net__AXI_Matrix_2__us1_rid ;

    assign w_net__AXI_Matrix_2__us1_rlast = w_port__AXI_Matrix_2__us1_rlast ;
    assign hp1_w_us1_rlast = w_net__AXI_Matrix_2__us1_rlast ;

    assign w_net__AXI_Matrix_2__us1_rresp = w_port__AXI_Matrix_2__us1_rresp ;
    assign hp1_w_us1_rresp = w_net__AXI_Matrix_2__us1_rresp ;

    assign w_net__AXI_Matrix_2__us1_rvalid = w_port__AXI_Matrix_2__us1_rvalid ;
    assign hp1_w_us1_rvalid = w_net__AXI_Matrix_2__us1_rvalid ;

    assign w_net__AXI_Matrix_2__us1_wready = w_port__AXI_Matrix_2__us1_wready ;
    assign hp1_w_us1_wready = w_net__AXI_Matrix_2__us1_wready ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_araddr = w_port__AXI_Protocol_Converter_0__ds_axi_araddr ;
    assign w_port__AXI_Matrix_0__us0_araddr = w_net__AXI_Protocol_Converter_0__ds_axi_araddr ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_arprot = w_port__AXI_Protocol_Converter_0__ds_axi_arprot ;
    assign w_port__AXI_Matrix_0__us0_arprot = w_net__AXI_Protocol_Converter_0__ds_axi_arprot ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_arvalid = w_port__AXI_Protocol_Converter_0__ds_axi_arvalid ;
    assign w_port__AXI_Matrix_0__us0_arvalid = w_net__AXI_Protocol_Converter_0__ds_axi_arvalid ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_awaddr = w_port__AXI_Protocol_Converter_0__ds_axi_awaddr ;
    assign w_port__AXI_Matrix_0__us0_awaddr = w_net__AXI_Protocol_Converter_0__ds_axi_awaddr ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_awprot = w_port__AXI_Protocol_Converter_0__ds_axi_awprot ;
    assign w_port__AXI_Matrix_0__us0_awprot = w_net__AXI_Protocol_Converter_0__ds_axi_awprot ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_awvalid = w_port__AXI_Protocol_Converter_0__ds_axi_awvalid ;
    assign w_port__AXI_Matrix_0__us0_awvalid = w_net__AXI_Protocol_Converter_0__ds_axi_awvalid ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_bready = w_port__AXI_Protocol_Converter_0__ds_axi_bready ;
    assign w_port__AXI_Matrix_0__us0_bready = w_net__AXI_Protocol_Converter_0__ds_axi_bready ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_rready = w_port__AXI_Protocol_Converter_0__ds_axi_rready ;
    assign w_port__AXI_Matrix_0__us0_rready = w_net__AXI_Protocol_Converter_0__ds_axi_rready ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_wdata = w_port__AXI_Protocol_Converter_0__ds_axi_wdata ;
    assign w_port__AXI_Matrix_0__us0_wdata = w_net__AXI_Protocol_Converter_0__ds_axi_wdata ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_wstrb = w_port__AXI_Protocol_Converter_0__ds_axi_wstrb ;
    assign w_port__AXI_Matrix_0__us0_wstrb = w_net__AXI_Protocol_Converter_0__ds_axi_wstrb ;

    assign w_net__AXI_Protocol_Converter_0__ds_axi_wvalid = w_port__AXI_Protocol_Converter_0__ds_axi_wvalid ;
    assign w_port__AXI_Matrix_0__us0_wvalid = w_net__AXI_Protocol_Converter_0__ds_axi_wvalid ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_arready = w_port__AXI_Protocol_Converter_0__us_axi_arready ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_arready = w_net__AXI_Protocol_Converter_0__us_axi_arready ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_awready = w_port__AXI_Protocol_Converter_0__us_axi_awready ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_awready = w_net__AXI_Protocol_Converter_0__us_axi_awready ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_bid = w_port__AXI_Protocol_Converter_0__us_axi_bid ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_bid = w_net__AXI_Protocol_Converter_0__us_axi_bid ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_bresp = w_port__AXI_Protocol_Converter_0__us_axi_bresp ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_bresp = w_net__AXI_Protocol_Converter_0__us_axi_bresp ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_bvalid = w_port__AXI_Protocol_Converter_0__us_axi_bvalid ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_bvalid = w_net__AXI_Protocol_Converter_0__us_axi_bvalid ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_rdata = w_port__AXI_Protocol_Converter_0__us_axi_rdata ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_rdata = w_net__AXI_Protocol_Converter_0__us_axi_rdata ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_rid = w_port__AXI_Protocol_Converter_0__us_axi_rid ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_rid = w_net__AXI_Protocol_Converter_0__us_axi_rid ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_rlast = w_port__AXI_Protocol_Converter_0__us_axi_rlast ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_rlast = w_net__AXI_Protocol_Converter_0__us_axi_rlast ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_rresp = w_port__AXI_Protocol_Converter_0__us_axi_rresp ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_rresp = w_net__AXI_Protocol_Converter_0__us_axi_rresp ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_rvalid = w_port__AXI_Protocol_Converter_0__us_axi_rvalid ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_rvalid = w_net__AXI_Protocol_Converter_0__us_axi_rvalid ;

    assign w_net__AXI_Protocol_Converter_0__us_axi_wready = w_port__AXI_Protocol_Converter_0__us_axi_wready ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_wready = w_net__AXI_Protocol_Converter_0__us_axi_wready ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_araddr = w_port__AXI_Protocol_Converter_1__ds_axi_araddr ;
    assign w_port__Video_NPU_0__s_axilite_araddr_i = w_net__AXI_Protocol_Converter_1__ds_axi_araddr ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_arprot = w_port__AXI_Protocol_Converter_1__ds_axi_arprot ;
    assign w_port__Video_NPU_0__s_axilite_arprot_i = w_net__AXI_Protocol_Converter_1__ds_axi_arprot ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_arvalid = w_port__AXI_Protocol_Converter_1__ds_axi_arvalid ;
    assign w_port__Video_NPU_0__s_axilite_arvalid_i = w_net__AXI_Protocol_Converter_1__ds_axi_arvalid ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_awaddr = w_port__AXI_Protocol_Converter_1__ds_axi_awaddr ;
    assign w_port__Video_NPU_0__s_axilite_awaddr_i = w_net__AXI_Protocol_Converter_1__ds_axi_awaddr ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_awprot = w_port__AXI_Protocol_Converter_1__ds_axi_awprot ;
    assign w_port__Video_NPU_0__s_axilite_awprot_i = w_net__AXI_Protocol_Converter_1__ds_axi_awprot ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_awvalid = w_port__AXI_Protocol_Converter_1__ds_axi_awvalid ;
    assign w_port__Video_NPU_0__s_axilite_awvalid_i = w_net__AXI_Protocol_Converter_1__ds_axi_awvalid ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_bready = w_port__AXI_Protocol_Converter_1__ds_axi_bready ;
    assign w_port__Video_NPU_0__s_axilite_bready_i = w_net__AXI_Protocol_Converter_1__ds_axi_bready ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_rready = w_port__AXI_Protocol_Converter_1__ds_axi_rready ;
    assign w_port__Video_NPU_0__s_axilite_rready_i = w_net__AXI_Protocol_Converter_1__ds_axi_rready ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_wdata = w_port__AXI_Protocol_Converter_1__ds_axi_wdata ;
    assign w_port__Video_NPU_0__s_axilite_wdata_i = w_net__AXI_Protocol_Converter_1__ds_axi_wdata ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_wstrb = w_port__AXI_Protocol_Converter_1__ds_axi_wstrb ;
    assign w_port__Video_NPU_0__s_axilite_wstrb_i = w_net__AXI_Protocol_Converter_1__ds_axi_wstrb ;

    assign w_net__AXI_Protocol_Converter_1__ds_axi_wvalid = w_port__AXI_Protocol_Converter_1__ds_axi_wvalid ;
    assign w_port__Video_NPU_0__s_axilite_wvalid_i = w_net__AXI_Protocol_Converter_1__ds_axi_wvalid ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_arready = w_port__AXI_Protocol_Converter_1__us_axi_arready ;
    assign w_port__AXI_Matrix_1__ds0_arready = w_net__AXI_Protocol_Converter_1__us_axi_arready ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_awready = w_port__AXI_Protocol_Converter_1__us_axi_awready ;
    assign w_port__AXI_Matrix_1__ds0_awready = w_net__AXI_Protocol_Converter_1__us_axi_awready ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_bid = w_port__AXI_Protocol_Converter_1__us_axi_bid ;
    assign w_port__AXI_Matrix_1__ds0_bid = w_net__AXI_Protocol_Converter_1__us_axi_bid ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_bresp = w_port__AXI_Protocol_Converter_1__us_axi_bresp ;
    assign w_port__AXI_Matrix_1__ds0_bresp = w_net__AXI_Protocol_Converter_1__us_axi_bresp ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_bvalid = w_port__AXI_Protocol_Converter_1__us_axi_bvalid ;
    assign w_port__AXI_Matrix_1__ds0_bvalid = w_net__AXI_Protocol_Converter_1__us_axi_bvalid ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_rdata = w_port__AXI_Protocol_Converter_1__us_axi_rdata ;
    assign w_port__AXI_Matrix_1__ds0_rdata = w_net__AXI_Protocol_Converter_1__us_axi_rdata ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_rid = w_port__AXI_Protocol_Converter_1__us_axi_rid ;
    assign w_port__AXI_Matrix_1__ds0_rid = w_net__AXI_Protocol_Converter_1__us_axi_rid ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_rlast = w_port__AXI_Protocol_Converter_1__us_axi_rlast ;
    assign w_port__AXI_Matrix_1__ds0_rlast = w_net__AXI_Protocol_Converter_1__us_axi_rlast ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_rresp = w_port__AXI_Protocol_Converter_1__us_axi_rresp ;
    assign w_port__AXI_Matrix_1__ds0_rresp = w_net__AXI_Protocol_Converter_1__us_axi_rresp ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_rvalid = w_port__AXI_Protocol_Converter_1__us_axi_rvalid ;
    assign w_port__AXI_Matrix_1__ds0_rvalid = w_net__AXI_Protocol_Converter_1__us_axi_rvalid ;

    assign w_net__AXI_Protocol_Converter_1__us_axi_wready = w_port__AXI_Protocol_Converter_1__us_axi_wready ;
    assign w_port__AXI_Matrix_1__ds0_wready = w_net__AXI_Protocol_Converter_1__us_axi_wready ;

    assign w_net__Concat_0__Dout = w_port__Concat_0__Dout ;
    assign w_port__ARM_Processor_System_0__f2p_irq = w_net__Concat_0__Dout ;

    assign w_net__PLL_3__clk0_out = w_port__PLL_3__clk0_out ;
    assign w_port__uihdmi_tx_0__I_serial_clk = w_net__PLL_3__clk0_out ;

    assign w_net__PLL_3__lock = w_port__PLL_3__lock ;
    assign w_port__Utility_Vector_Logic_1__vector_a = w_net__PLL_3__lock ;

    assign w_net__PLL_npu__clk0_out = w_port__PLL_npu__clk0_out ;
    assign w_port__ARM_Processor_System_0__master_gp1_axi_aclk = w_net__PLL_npu__clk0_out ;
    assign w_port__pwm_0__clk = w_net__PLL_npu__clk0_out ;
    assign w_port__rstn_npu__clk = w_net__PLL_npu__clk0_out ;
    assign w_port__AXI_Protocol_Converter_1__aclk = w_net__PLL_npu__clk0_out ;
    assign w_port__AXI_Matrix_1__aclk = w_net__PLL_npu__clk0_out ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_aclk = w_net__PLL_npu__clk0_out ;
    assign w_port__Video_NPU_0__S_AXILite_ACLK = w_net__PLL_npu__clk0_out ;
    assign w_port__Video_NPU_0__M_AXI_ACLK = w_net__PLL_npu__clk0_out ;
    assign w_port__pwm_0_0__clk = w_net__PLL_npu__clk0_out ;
    assign w_port__pwm_0_1__clk = w_net__PLL_npu__clk0_out ;

    assign w_net__PLL_npu__lock = w_port__PLL_npu__lock ;
    assign w_port__rstn_npu__pll_locked = w_net__PLL_npu__lock ;

    assign w_net__Utility_Vector_Logic_0__result_vector = w_port__Utility_Vector_Logic_0__result_vector ;
    assign w_port__PLL_3__reset = w_net__Utility_Vector_Logic_0__result_vector ;

    assign w_net__Utility_Vector_Logic_1__result_vector = w_port__Utility_Vector_Logic_1__result_vector ;
    assign w_port__uihdmi_tx_0__I_rst = w_net__Utility_Vector_Logic_1__result_vector ;

    assign w_net__VDMA_0__axi_lite_arready = w_port__VDMA_0__axi_lite_arready ;
    assign w_port__AXI_Matrix_0__ds0_arready = w_net__VDMA_0__axi_lite_arready ;

    assign w_net__VDMA_0__axi_lite_awready = w_port__VDMA_0__axi_lite_awready ;
    assign w_port__AXI_Matrix_0__ds0_awready = w_net__VDMA_0__axi_lite_awready ;

    assign w_net__VDMA_0__axi_lite_bresp = w_port__VDMA_0__axi_lite_bresp ;
    assign w_port__AXI_Matrix_0__ds0_bresp = w_net__VDMA_0__axi_lite_bresp ;

    assign w_net__VDMA_0__axi_lite_bvalid = w_port__VDMA_0__axi_lite_bvalid ;
    assign w_port__AXI_Matrix_0__ds0_bvalid = w_net__VDMA_0__axi_lite_bvalid ;

    assign w_net__VDMA_0__axi_lite_rdata = w_port__VDMA_0__axi_lite_rdata ;
    assign w_port__AXI_Matrix_0__ds0_rdata = w_net__VDMA_0__axi_lite_rdata ;

    assign w_net__VDMA_0__axi_lite_rresp = w_port__VDMA_0__axi_lite_rresp ;
    assign w_port__AXI_Matrix_0__ds0_rresp = w_net__VDMA_0__axi_lite_rresp ;

    assign w_net__VDMA_0__axi_lite_rvalid = w_port__VDMA_0__axi_lite_rvalid ;
    assign w_port__AXI_Matrix_0__ds0_rvalid = w_net__VDMA_0__axi_lite_rvalid ;

    assign w_net__VDMA_0__axi_lite_wready = w_port__VDMA_0__axi_lite_wready ;
    assign w_port__AXI_Matrix_0__ds0_wready = w_net__VDMA_0__axi_lite_wready ;

    assign w_net__VDMA_0__m_axi_mm2s_araddr = w_port__VDMA_0__m_axi_mm2s_araddr ;
    assign w_port__AXI_Matrix_2__us0_araddr = w_net__VDMA_0__m_axi_mm2s_araddr ;

    assign w_net__VDMA_0__m_axi_mm2s_arburst = w_port__VDMA_0__m_axi_mm2s_arburst ;
    assign w_port__AXI_Matrix_2__us0_arburst = w_net__VDMA_0__m_axi_mm2s_arburst ;

    assign w_net__VDMA_0__m_axi_mm2s_arcache = w_port__VDMA_0__m_axi_mm2s_arcache ;
    assign w_port__AXI_Matrix_2__us0_arcache = w_net__VDMA_0__m_axi_mm2s_arcache ;

    assign w_net__VDMA_0__m_axi_mm2s_arlen = w_port__VDMA_0__m_axi_mm2s_arlen ;
    assign w_port__AXI_Matrix_2__us0_arlen = w_net__VDMA_0__m_axi_mm2s_arlen ;

    assign w_net__VDMA_0__m_axi_mm2s_arprot = w_port__VDMA_0__m_axi_mm2s_arprot ;
    assign w_port__AXI_Matrix_2__us0_arprot = w_net__VDMA_0__m_axi_mm2s_arprot ;

    assign w_net__VDMA_0__m_axi_mm2s_arsize = w_port__VDMA_0__m_axi_mm2s_arsize ;
    assign w_port__AXI_Matrix_2__us0_arsize = w_net__VDMA_0__m_axi_mm2s_arsize ;

    assign w_net__VDMA_0__m_axi_mm2s_arvalid = w_port__VDMA_0__m_axi_mm2s_arvalid ;
    assign w_port__AXI_Matrix_2__us0_arvalid = w_net__VDMA_0__m_axi_mm2s_arvalid ;

    assign w_net__VDMA_0__m_axi_mm2s_rready = w_port__VDMA_0__m_axi_mm2s_rready ;
    assign w_port__AXI_Matrix_2__us0_rready = w_net__VDMA_0__m_axi_mm2s_rready ;

    assign w_net__VDMA_0__m_axis_mm2s_tdata = w_port__VDMA_0__m_axis_mm2s_tdata ;
    assign w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tdata = w_net__VDMA_0__m_axis_mm2s_tdata ;

    assign w_net__VDMA_0__m_axis_mm2s_tlast = w_port__VDMA_0__m_axis_mm2s_tlast ;
    assign w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tlast = w_net__VDMA_0__m_axis_mm2s_tlast ;

    assign w_net__VDMA_0__m_axis_mm2s_tuser = w_port__VDMA_0__m_axis_mm2s_tuser ;
    assign w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tuser = w_net__VDMA_0__m_axis_mm2s_tuser ;

    assign w_net__VDMA_0__m_axis_mm2s_tvalid = w_port__VDMA_0__m_axis_mm2s_tvalid ;
    assign w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tvalid = w_net__VDMA_0__m_axis_mm2s_tvalid ;

    assign w_net__VDMA_0__mm2s_introut = w_port__VDMA_0__mm2s_introut ;
    assign w_port__Concat_0__In2 = w_net__VDMA_0__mm2s_introut ;

    assign w_net__Video_NPU_0__m_axi_araddr_soft_o = w_port__Video_NPU_0__m_axi_araddr_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_araddr = w_net__Video_NPU_0__m_axi_araddr_soft_o ;

    assign w_net__Video_NPU_0__m_axi_arburst_soft_o = w_port__Video_NPU_0__m_axi_arburst_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_arburst = w_net__Video_NPU_0__m_axi_arburst_soft_o ;

    assign w_net__Video_NPU_0__m_axi_arcache_soft_o = w_port__Video_NPU_0__m_axi_arcache_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_arcache = w_net__Video_NPU_0__m_axi_arcache_soft_o ;

    assign w_net__Video_NPU_0__m_axi_arid_soft_o = w_port__Video_NPU_0__m_axi_arid_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_arid = w_net__Video_NPU_0__m_axi_arid_soft_o ;

    assign w_net__Video_NPU_0__m_axi_arlen_soft_o = w_port__Video_NPU_0__m_axi_arlen_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_arlen = w_net__Video_NPU_0__m_axi_arlen_soft_o ;

    assign w_net__Video_NPU_0__m_axi_arlock_soft_o = w_port__Video_NPU_0__m_axi_arlock_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_arlock = w_net__Video_NPU_0__m_axi_arlock_soft_o ;

    assign w_net__Video_NPU_0__m_axi_arprot_soft_o = w_port__Video_NPU_0__m_axi_arprot_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_arprot = w_net__Video_NPU_0__m_axi_arprot_soft_o ;

    assign w_net__Video_NPU_0__m_axi_arsize_soft_o = w_port__Video_NPU_0__m_axi_arsize_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_arsize = w_net__Video_NPU_0__m_axi_arsize_soft_o ;

    assign w_net__Video_NPU_0__m_axi_arvalid_soft_o = w_port__Video_NPU_0__m_axi_arvalid_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_arvalid = w_net__Video_NPU_0__m_axi_arvalid_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awaddr_soft_o = w_port__Video_NPU_0__m_axi_awaddr_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awaddr = w_net__Video_NPU_0__m_axi_awaddr_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awburst_soft_o = w_port__Video_NPU_0__m_axi_awburst_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awburst = w_net__Video_NPU_0__m_axi_awburst_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awcache_soft_o = w_port__Video_NPU_0__m_axi_awcache_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awcache = w_net__Video_NPU_0__m_axi_awcache_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awid_soft_o = w_port__Video_NPU_0__m_axi_awid_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awid = w_net__Video_NPU_0__m_axi_awid_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awlen_soft_o = w_port__Video_NPU_0__m_axi_awlen_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awlen = w_net__Video_NPU_0__m_axi_awlen_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awlock_soft_o = w_port__Video_NPU_0__m_axi_awlock_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awlock = w_net__Video_NPU_0__m_axi_awlock_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awprot_soft_o = w_port__Video_NPU_0__m_axi_awprot_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awprot = w_net__Video_NPU_0__m_axi_awprot_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awsize_soft_o = w_port__Video_NPU_0__m_axi_awsize_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awsize = w_net__Video_NPU_0__m_axi_awsize_soft_o ;

    assign w_net__Video_NPU_0__m_axi_awvalid_soft_o = w_port__Video_NPU_0__m_axi_awvalid_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_awvalid = w_net__Video_NPU_0__m_axi_awvalid_soft_o ;

    assign w_net__Video_NPU_0__m_axi_bready_soft_o = w_port__Video_NPU_0__m_axi_bready_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_bready = w_net__Video_NPU_0__m_axi_bready_soft_o ;

    assign w_net__Video_NPU_0__m_axi_rready_soft_o = w_port__Video_NPU_0__m_axi_rready_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_rready = w_net__Video_NPU_0__m_axi_rready_soft_o ;

    assign w_net__Video_NPU_0__m_axi_wdata_soft_o = w_port__Video_NPU_0__m_axi_wdata_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_wdata = w_net__Video_NPU_0__m_axi_wdata_soft_o ;

    assign w_net__Video_NPU_0__m_axi_wlast_soft_o = w_port__Video_NPU_0__m_axi_wlast_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_wlast = w_net__Video_NPU_0__m_axi_wlast_soft_o ;

    assign w_net__Video_NPU_0__m_axi_wstrb_soft_o = w_port__Video_NPU_0__m_axi_wstrb_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_wstrb = w_net__Video_NPU_0__m_axi_wstrb_soft_o ;

    assign w_net__Video_NPU_0__m_axi_wvalid_soft_o = w_port__Video_NPU_0__m_axi_wvalid_soft_o ;
    assign w_port__ARM_Processor_System_0__slave_hp0_axi_wvalid = w_net__Video_NPU_0__m_axi_wvalid_soft_o ;

    assign w_net__Video_NPU_0__npu_soft_intr = w_port__Video_NPU_0__npu_soft_intr ;
    assign w_port__Concat_0__In15 = w_net__Video_NPU_0__npu_soft_intr ;

    assign w_net__Video_NPU_0__s_axilite_arready_o = w_port__Video_NPU_0__s_axilite_arready_o ;
    assign w_port__AXI_Protocol_Converter_1__ds_axi_arready = w_net__Video_NPU_0__s_axilite_arready_o ;

    assign w_net__Video_NPU_0__s_axilite_awready_o = w_port__Video_NPU_0__s_axilite_awready_o ;
    assign w_port__AXI_Protocol_Converter_1__ds_axi_awready = w_net__Video_NPU_0__s_axilite_awready_o ;

    assign w_net__Video_NPU_0__s_axilite_bresp_o = w_port__Video_NPU_0__s_axilite_bresp_o ;
    assign w_port__AXI_Protocol_Converter_1__ds_axi_bresp = w_net__Video_NPU_0__s_axilite_bresp_o ;

    assign w_net__Video_NPU_0__s_axilite_bvalid_o = w_port__Video_NPU_0__s_axilite_bvalid_o ;
    assign w_port__AXI_Protocol_Converter_1__ds_axi_bvalid = w_net__Video_NPU_0__s_axilite_bvalid_o ;

    assign w_net__Video_NPU_0__s_axilite_rdata_o = w_port__Video_NPU_0__s_axilite_rdata_o ;
    assign w_port__AXI_Protocol_Converter_1__ds_axi_rdata = w_net__Video_NPU_0__s_axilite_rdata_o ;

    assign w_net__Video_NPU_0__s_axilite_rresp_o = w_port__Video_NPU_0__s_axilite_rresp_o ;
    assign w_port__AXI_Protocol_Converter_1__ds_axi_rresp = w_net__Video_NPU_0__s_axilite_rresp_o ;

    assign w_net__Video_NPU_0__s_axilite_rvalid_o = w_port__Video_NPU_0__s_axilite_rvalid_o ;
    assign w_port__AXI_Protocol_Converter_1__ds_axi_rvalid = w_net__Video_NPU_0__s_axilite_rvalid_o ;

    assign w_net__Video_NPU_0__s_axilite_wready_o = w_port__Video_NPU_0__s_axilite_wready_o ;
    assign w_port__AXI_Protocol_Converter_1__ds_axi_wready = w_net__Video_NPU_0__s_axilite_wready_o ;

    assign w_net__f2p_irq = f2p_irq ;
    assign w_port__Concat_0__In0 = w_net__f2p_irq ;

    assign w_net__fvdma_ctrl_0__camera_base_addr = w_port__fvdma_ctrl_0__camera_base_addr ;
    assign camera_base_addr = w_net__fvdma_ctrl_0__camera_base_addr ;

    assign w_net__fvdma_ctrl_0__camera_clear = w_port__fvdma_ctrl_0__camera_clear ;
    assign camera_clear = w_net__fvdma_ctrl_0__camera_clear ;

    assign w_net__fvdma_ctrl_0__camera_start = w_port__fvdma_ctrl_0__camera_start ;
    assign camera_start = w_net__fvdma_ctrl_0__camera_start ;

    assign w_net__fvdma_ctrl_0__s_axi_arready = w_port__fvdma_ctrl_0__s_axi_arready ;
    assign w_port__AXI_Matrix_0__ds2_arready = w_net__fvdma_ctrl_0__s_axi_arready ;

    assign w_net__fvdma_ctrl_0__s_axi_awready = w_port__fvdma_ctrl_0__s_axi_awready ;
    assign w_port__AXI_Matrix_0__ds2_awready = w_net__fvdma_ctrl_0__s_axi_awready ;

    assign w_net__fvdma_ctrl_0__s_axi_bresp = w_port__fvdma_ctrl_0__s_axi_bresp ;
    assign w_port__AXI_Matrix_0__ds2_bresp = w_net__fvdma_ctrl_0__s_axi_bresp ;

    assign w_net__fvdma_ctrl_0__s_axi_bvalid = w_port__fvdma_ctrl_0__s_axi_bvalid ;
    assign w_port__AXI_Matrix_0__ds2_bvalid = w_net__fvdma_ctrl_0__s_axi_bvalid ;

    assign w_net__fvdma_ctrl_0__s_axi_rdata = w_port__fvdma_ctrl_0__s_axi_rdata ;
    assign w_port__AXI_Matrix_0__ds2_rdata = w_net__fvdma_ctrl_0__s_axi_rdata ;

    assign w_net__fvdma_ctrl_0__s_axi_rresp = w_port__fvdma_ctrl_0__s_axi_rresp ;
    assign w_port__AXI_Matrix_0__ds2_rresp = w_net__fvdma_ctrl_0__s_axi_rresp ;

    assign w_net__fvdma_ctrl_0__s_axi_rvalid = w_port__fvdma_ctrl_0__s_axi_rvalid ;
    assign w_port__AXI_Matrix_0__ds2_rvalid = w_net__fvdma_ctrl_0__s_axi_rvalid ;

    assign w_net__fvdma_ctrl_0__s_axi_wready = w_port__fvdma_ctrl_0__s_axi_wready ;
    assign w_port__AXI_Matrix_0__ds2_wready = w_net__fvdma_ctrl_0__s_axi_wready ;

    assign w_net__hp1_w_us1_araddr = hp1_w_us1_araddr ;
    assign w_port__AXI_Matrix_2__us1_araddr = w_net__hp1_w_us1_araddr ;

    assign w_net__hp1_w_us1_arburst = hp1_w_us1_arburst ;
    assign w_port__AXI_Matrix_2__us1_arburst = w_net__hp1_w_us1_arburst ;

    assign w_net__hp1_w_us1_arcache = hp1_w_us1_arcache ;
    assign w_port__AXI_Matrix_2__us1_arcache = w_net__hp1_w_us1_arcache ;

    assign w_net__hp1_w_us1_arid = hp1_w_us1_arid ;
    assign w_port__AXI_Matrix_2__us1_arid = w_net__hp1_w_us1_arid ;

    assign w_net__hp1_w_us1_arlen = hp1_w_us1_arlen ;
    assign w_port__AXI_Matrix_2__us1_arlen = w_net__hp1_w_us1_arlen ;

    assign w_net__hp1_w_us1_arlock = hp1_w_us1_arlock ;
    assign w_port__AXI_Matrix_2__us1_arlock = w_net__hp1_w_us1_arlock ;

    assign w_net__hp1_w_us1_arprot = hp1_w_us1_arprot ;
    assign w_port__AXI_Matrix_2__us1_arprot = w_net__hp1_w_us1_arprot ;

    assign w_net__hp1_w_us1_arqos = hp1_w_us1_arqos ;
    assign w_port__AXI_Matrix_2__us1_arqos = w_net__hp1_w_us1_arqos ;

    assign w_net__hp1_w_us1_arsize = hp1_w_us1_arsize ;
    assign w_port__AXI_Matrix_2__us1_arsize = w_net__hp1_w_us1_arsize ;

    assign w_net__hp1_w_us1_arvalid = hp1_w_us1_arvalid ;
    assign w_port__AXI_Matrix_2__us1_arvalid = w_net__hp1_w_us1_arvalid ;

    assign w_net__hp1_w_us1_awaddr = hp1_w_us1_awaddr ;
    assign w_port__AXI_Matrix_2__us1_awaddr = w_net__hp1_w_us1_awaddr ;

    assign w_net__hp1_w_us1_awburst = hp1_w_us1_awburst ;
    assign w_port__AXI_Matrix_2__us1_awburst = w_net__hp1_w_us1_awburst ;

    assign w_net__hp1_w_us1_awcache = hp1_w_us1_awcache ;
    assign w_port__AXI_Matrix_2__us1_awcache = w_net__hp1_w_us1_awcache ;

    assign w_net__hp1_w_us1_awid = hp1_w_us1_awid ;
    assign w_port__AXI_Matrix_2__us1_awid = w_net__hp1_w_us1_awid ;

    assign w_net__hp1_w_us1_awlen = hp1_w_us1_awlen ;
    assign w_port__AXI_Matrix_2__us1_awlen = w_net__hp1_w_us1_awlen ;

    assign w_net__hp1_w_us1_awlock = hp1_w_us1_awlock ;
    assign w_port__AXI_Matrix_2__us1_awlock = w_net__hp1_w_us1_awlock ;

    assign w_net__hp1_w_us1_awprot = hp1_w_us1_awprot ;
    assign w_port__AXI_Matrix_2__us1_awprot = w_net__hp1_w_us1_awprot ;

    assign w_net__hp1_w_us1_awqos = hp1_w_us1_awqos ;
    assign w_port__AXI_Matrix_2__us1_awqos = w_net__hp1_w_us1_awqos ;

    assign w_net__hp1_w_us1_awsize = hp1_w_us1_awsize ;
    assign w_port__AXI_Matrix_2__us1_awsize = w_net__hp1_w_us1_awsize ;

    assign w_net__hp1_w_us1_awvalid = hp1_w_us1_awvalid ;
    assign w_port__AXI_Matrix_2__us1_awvalid = w_net__hp1_w_us1_awvalid ;

    assign w_net__hp1_w_us1_bready = hp1_w_us1_bready ;
    assign w_port__AXI_Matrix_2__us1_bready = w_net__hp1_w_us1_bready ;

    assign w_net__hp1_w_us1_rready = hp1_w_us1_rready ;
    assign w_port__AXI_Matrix_2__us1_rready = w_net__hp1_w_us1_rready ;

    assign w_net__hp1_w_us1_wdata = hp1_w_us1_wdata ;
    assign w_port__AXI_Matrix_2__us1_wdata = w_net__hp1_w_us1_wdata ;

    assign w_net__hp1_w_us1_wlast = hp1_w_us1_wlast ;
    assign w_port__AXI_Matrix_2__us1_wlast = w_net__hp1_w_us1_wlast ;

    assign w_net__hp1_w_us1_wstrb = hp1_w_us1_wstrb ;
    assign w_port__AXI_Matrix_2__us1_wstrb = w_net__hp1_w_us1_wstrb ;

    assign w_net__hp1_w_us1_wvalid = hp1_w_us1_wvalid ;
    assign w_port__AXI_Matrix_2__us1_wvalid = w_net__hp1_w_us1_wvalid ;

    assign w_net__pll_150m__clk0_out = w_port__pll_150m__clk0_out ;
    assign w_port__ARM_Processor_System_0__slave_hp1_axi_aclk = w_net__pll_150m__clk0_out ;
    assign clk_150m = w_net__pll_150m__clk0_out ;
    assign w_port__rstn_150m__clk = w_net__pll_150m__clk0_out ;
    assign w_port__VDMA_0__m_axi_mm2s_aclk = w_net__pll_150m__clk0_out ;
    assign w_port__VDMA_0__m_axis_mm2s_aclk = w_net__pll_150m__clk0_out ;
    assign w_port__AXI4_Stream_to_Video_Out_0__aclk = w_net__pll_150m__clk0_out ;
    assign w_port__AXI_Matrix_2__aclk = w_net__pll_150m__clk0_out ;

    assign w_net__pll_150m__lock = w_port__pll_150m__lock ;
    assign w_port__rstn_150m__pll_locked = w_net__pll_150m__lock ;
    assign w_port__AXI4_Stream_to_Video_Out_0__aclken = w_net__pll_150m__lock ;

    assign w_net__pll_75m__clk0_out = w_port__pll_75m__clk0_out ;
    assign w_port__AXI_Protocol_Converter_0__aclk = w_net__pll_75m__clk0_out ;
    assign w_port__ARM_Processor_System_0__master_gp0_axi_aclk = w_net__pll_75m__clk0_out ;
    assign w_port__AXI_Matrix_0__aclk = w_net__pll_75m__clk0_out ;
    assign w_port__rst_n_75m__clk = w_net__pll_75m__clk0_out ;
    assign w_port__fvdma_ctrl_0__s_axi_aclk = w_net__pll_75m__clk0_out ;
    assign w_port__VDMA_0__s_axi_lite_aclk = w_net__pll_75m__clk0_out ;
    assign w_port__video_timing_generator_v01_0__aclk = w_net__pll_75m__clk0_out ;

    assign w_net__pll_75m__lock = w_port__pll_75m__lock ;
    assign w_port__rst_n_75m__pll_locked = w_net__pll_75m__lock ;

    assign w_net__pwm_0_0__pwm_out = w_port__pwm_0_0__pwm_out ;
    assign vtg_lock = w_net__pwm_0_0__pwm_out ;

    assign w_net__pwm_0_1__pwm_out = w_port__pwm_0_1__pwm_out ;
    assign axis_to_video_lock = w_net__pwm_0_1__pwm_out ;

    assign w_net__pwm_0__pwm_out = w_port__pwm_0__pwm_out ;
    assign pwm_out = w_net__pwm_0__pwm_out ;

    assign w_net__rst_n_75m__interconnect_aresetn = w_port__rst_n_75m__interconnect_aresetn ;
    assign w_port__AXI_Protocol_Converter_0__aresetn = w_net__rst_n_75m__interconnect_aresetn ;
    assign w_port__AXI_Matrix_0__aresetn = w_net__rst_n_75m__interconnect_aresetn ;
    assign w_port__fvdma_ctrl_0__s_axi_aresetn = w_net__rst_n_75m__interconnect_aresetn ;
    assign w_port__VDMA_0__resetn = w_net__rst_n_75m__interconnect_aresetn ;
    assign w_port__video_timing_generator_v01_0__arst_n = w_net__rst_n_75m__interconnect_aresetn ;

    assign w_net__rstn_150m__peripheral_aresetn = w_port__rstn_150m__peripheral_aresetn ;
    assign rstn_150m = w_net__rstn_150m__peripheral_aresetn ;
    assign w_port__AXI4_Stream_to_Video_Out_0__aresetn = w_net__rstn_150m__peripheral_aresetn ;
    assign w_port__AXI_Matrix_2__aresetn = w_net__rstn_150m__peripheral_aresetn ;

    assign w_net__rstn_npu__interconnect_aresetn = w_port__rstn_npu__interconnect_aresetn ;
    assign w_port__pwm_0__rst_n = w_net__rstn_npu__interconnect_aresetn ;

    assign w_net__rstn_npu__peripheral_aresetn = w_port__rstn_npu__peripheral_aresetn ;
    assign w_port__Video_NPU_0__S_AXILite_AResetn = w_net__rstn_npu__peripheral_aresetn ;
    assign w_port__Video_NPU_0__M_AXI_AResetn = w_net__rstn_npu__peripheral_aresetn ;
    assign w_port__AXI_Protocol_Converter_1__aresetn = w_net__rstn_npu__peripheral_aresetn ;
    assign w_port__AXI_Matrix_1__aresetn = w_net__rstn_npu__peripheral_aresetn ;

    assign w_net__uihdmi_tx_0__O_hdmi_clk_p = w_port__uihdmi_tx_0__O_hdmi_clk_p ;
    assign O_hdmi_clk_p = w_net__uihdmi_tx_0__O_hdmi_clk_p ;

    assign w_net__uihdmi_tx_0__O_hdmi_tx_p = w_port__uihdmi_tx_0__O_hdmi_tx_p ;
    assign O_hdmi_tx_p = w_net__uihdmi_tx_0__O_hdmi_tx_p ;

    assign w_net__video_timing_generator_v01_0__s_axi_arready = w_port__video_timing_generator_v01_0__s_axi_arready ;
    assign w_port__AXI_Matrix_0__ds1_arready = w_net__video_timing_generator_v01_0__s_axi_arready ;

    assign w_net__video_timing_generator_v01_0__s_axi_awready = w_port__video_timing_generator_v01_0__s_axi_awready ;
    assign w_port__AXI_Matrix_0__ds1_awready = w_net__video_timing_generator_v01_0__s_axi_awready ;

    assign w_net__video_timing_generator_v01_0__s_axi_bresp = w_port__video_timing_generator_v01_0__s_axi_bresp ;
    assign w_port__AXI_Matrix_0__ds1_bresp = w_net__video_timing_generator_v01_0__s_axi_bresp ;

    assign w_net__video_timing_generator_v01_0__s_axi_bvalid = w_port__video_timing_generator_v01_0__s_axi_bvalid ;
    assign w_port__AXI_Matrix_0__ds1_bvalid = w_net__video_timing_generator_v01_0__s_axi_bvalid ;

    assign w_net__video_timing_generator_v01_0__s_axi_rdata = w_port__video_timing_generator_v01_0__s_axi_rdata ;
    assign w_port__AXI_Matrix_0__ds1_rdata = w_net__video_timing_generator_v01_0__s_axi_rdata ;

    assign w_net__video_timing_generator_v01_0__s_axi_rresp = w_port__video_timing_generator_v01_0__s_axi_rresp ;
    assign w_port__AXI_Matrix_0__ds1_rresp = w_net__video_timing_generator_v01_0__s_axi_rresp ;

    assign w_net__video_timing_generator_v01_0__s_axi_rvalid = w_port__video_timing_generator_v01_0__s_axi_rvalid ;
    assign w_port__AXI_Matrix_0__ds1_rvalid = w_net__video_timing_generator_v01_0__s_axi_rvalid ;

    assign w_net__video_timing_generator_v01_0__s_axi_wready = w_port__video_timing_generator_v01_0__s_axi_wready ;
    assign w_port__AXI_Matrix_0__ds1_wready = w_net__video_timing_generator_v01_0__s_axi_wready ;

    assign w_net__video_timing_generator_v01_0__vtg_active_video = w_port__video_timing_generator_v01_0__vtg_active_video ;
    assign w_port__AXI4_Stream_to_Video_Out_0__vtg_active_video = w_net__video_timing_generator_v01_0__vtg_active_video ;

    assign w_net__video_timing_generator_v01_0__vtg_hblank = w_port__video_timing_generator_v01_0__vtg_hblank ;
    assign w_port__AXI4_Stream_to_Video_Out_0__vtg_hblank = w_net__video_timing_generator_v01_0__vtg_hblank ;

    assign w_net__video_timing_generator_v01_0__vtg_hsync = w_port__video_timing_generator_v01_0__vtg_hsync ;
    assign w_port__AXI4_Stream_to_Video_Out_0__vtg_hsync = w_net__video_timing_generator_v01_0__vtg_hsync ;

    assign w_net__video_timing_generator_v01_0__vtg_pclk = w_port__video_timing_generator_v01_0__vtg_pclk ;
    assign w_port__AXI4_Stream_to_Video_Out_0__vid_io_out_clk = w_net__video_timing_generator_v01_0__vtg_pclk ;
    assign w_port__PLL_3__refclk = w_net__video_timing_generator_v01_0__vtg_pclk ;
    assign w_port__uihdmi_tx_0__I_pixel_clk = w_net__video_timing_generator_v01_0__vtg_pclk ;

    assign w_net__video_timing_generator_v01_0__vtg_pclk_locked = w_port__video_timing_generator_v01_0__vtg_pclk_locked ;
    assign w_port__AXI4_Stream_to_Video_Out_0__vid_io_out_ce = w_net__video_timing_generator_v01_0__vtg_pclk_locked ;
    assign w_port__Utility_Vector_Logic_0__vector_a = w_net__video_timing_generator_v01_0__vtg_pclk_locked ;
    assign w_port__pwm_0_0__rst_n = w_net__video_timing_generator_v01_0__vtg_pclk_locked ;

    assign w_net__video_timing_generator_v01_0__vtg_vblank = w_port__video_timing_generator_v01_0__vtg_vblank ;
    assign w_port__AXI4_Stream_to_Video_Out_0__vtg_vblank = w_net__video_timing_generator_v01_0__vtg_vblank ;

    assign w_net__video_timing_generator_v01_0__vtg_vsync = w_port__video_timing_generator_v01_0__vtg_vsync ;
    assign w_port__AXI4_Stream_to_Video_Out_0__vtg_vsync = w_net__video_timing_generator_v01_0__vtg_vsync ;















    DR1_LOGIC_IOTRIBUF mipi_iic_i2c0_scl_DR1_LOGIC_IOTRIBUF_0 (  .o(w_port__ARM_Processor_System_0__i2c0_scl_in)
                                                               , .i(1'b0)
                                                               , .t(~w_port__ARM_Processor_System_0__i2c0_scl_oe)
                                                               , .io(mipi_iic_i2c0_scl_io) );

    DR1_LOGIC_IOTRIBUF mipi_iic_i2c0_sda_DR1_LOGIC_IOTRIBUF_0 (  .o(w_port__ARM_Processor_System_0__i2c0_sda_in)
                                                               , .i(1'b0)
                                                               , .t(~w_port__ARM_Processor_System_0__i2c0_sda_oe)
                                                               , .io(mipi_iic_i2c0_sda_io) );

    AXI_Protocol_Converter_0 design_0_AXI_Protocol_Converter_0_Inst ( 
                                                                       .us_axi_awid(w_port__AXI_Protocol_Converter_0__us_axi_awid)
                                                                     , .us_axi_awaddr(w_port__AXI_Protocol_Converter_0__us_axi_awaddr)
                                                                     , .us_axi_awlen(w_port__AXI_Protocol_Converter_0__us_axi_awlen)
                                                                     , .us_axi_awsize(w_port__AXI_Protocol_Converter_0__us_axi_awsize)
                                                                     , .us_axi_awburst(w_port__AXI_Protocol_Converter_0__us_axi_awburst)
                                                                     , .us_axi_awlock(w_port__AXI_Protocol_Converter_0__us_axi_awlock)
                                                                     , .us_axi_awcache(w_port__AXI_Protocol_Converter_0__us_axi_awcache)
                                                                     , .us_axi_awprot(w_port__AXI_Protocol_Converter_0__us_axi_awprot)
                                                                     , .us_axi_awvalid(w_port__AXI_Protocol_Converter_0__us_axi_awvalid)
                                                                     , .us_axi_awready(w_port__AXI_Protocol_Converter_0__us_axi_awready)
                                                                     , .us_axi_wdata(w_port__AXI_Protocol_Converter_0__us_axi_wdata)
                                                                     , .us_axi_wstrb(w_port__AXI_Protocol_Converter_0__us_axi_wstrb)
                                                                     , .us_axi_wlast(w_port__AXI_Protocol_Converter_0__us_axi_wlast)
                                                                     , .us_axi_wvalid(w_port__AXI_Protocol_Converter_0__us_axi_wvalid)
                                                                     , .us_axi_wready(w_port__AXI_Protocol_Converter_0__us_axi_wready)
                                                                     , .us_axi_bid(w_port__AXI_Protocol_Converter_0__us_axi_bid)
                                                                     , .us_axi_bresp(w_port__AXI_Protocol_Converter_0__us_axi_bresp)
                                                                     , .us_axi_bvalid(w_port__AXI_Protocol_Converter_0__us_axi_bvalid)
                                                                     , .us_axi_bready(w_port__AXI_Protocol_Converter_0__us_axi_bready)
                                                                     , .us_axi_arid(w_port__AXI_Protocol_Converter_0__us_axi_arid)
                                                                     , .us_axi_araddr(w_port__AXI_Protocol_Converter_0__us_axi_araddr)
                                                                     , .us_axi_arlen(w_port__AXI_Protocol_Converter_0__us_axi_arlen)
                                                                     , .us_axi_arsize(w_port__AXI_Protocol_Converter_0__us_axi_arsize)
                                                                     , .us_axi_arburst(w_port__AXI_Protocol_Converter_0__us_axi_arburst)
                                                                     , .us_axi_arlock(w_port__AXI_Protocol_Converter_0__us_axi_arlock)
                                                                     , .us_axi_arcache(w_port__AXI_Protocol_Converter_0__us_axi_arcache)
                                                                     , .us_axi_arprot(w_port__AXI_Protocol_Converter_0__us_axi_arprot)
                                                                     , .us_axi_arvalid(w_port__AXI_Protocol_Converter_0__us_axi_arvalid)
                                                                     , .us_axi_arready(w_port__AXI_Protocol_Converter_0__us_axi_arready)
                                                                     , .us_axi_rid(w_port__AXI_Protocol_Converter_0__us_axi_rid)
                                                                     , .us_axi_rdata(w_port__AXI_Protocol_Converter_0__us_axi_rdata)
                                                                     , .us_axi_rresp(w_port__AXI_Protocol_Converter_0__us_axi_rresp)
                                                                     , .us_axi_rlast(w_port__AXI_Protocol_Converter_0__us_axi_rlast)
                                                                     , .us_axi_rvalid(w_port__AXI_Protocol_Converter_0__us_axi_rvalid)
                                                                     , .us_axi_rready(w_port__AXI_Protocol_Converter_0__us_axi_rready)
                                                                     , .us_axi_awuser(1'b0)
                                                                     , .us_axi_awqos(4'b0)
                                                                     , .us_axi_wuser(1'b0)
                                                                     , .us_axi_buser()
                                                                     , .us_axi_aruser(1'b0)
                                                                     , .us_axi_arqos(4'b0)
                                                                     , .us_axi_ruser()
                                                                     , .aclk(w_port__AXI_Protocol_Converter_0__aclk)
                                                                     , .aresetn(w_port__AXI_Protocol_Converter_0__aresetn)
                                                                     , .ds_axi_awaddr(edge_gp0_awaddr)
                                                                     , .ds_axi_awprot(edge_gp0_awprot)
                                                                     , .ds_axi_awvalid(edge_gp0_awvalid)
                                                                     , .ds_axi_awready(edge_gp0_awready)
                                                                     , .ds_axi_wdata(edge_gp0_wdata)
                                                                     , .ds_axi_wstrb(edge_gp0_wstrb)
                                                                     , .ds_axi_wvalid(edge_gp0_wvalid)
                                                                     , .ds_axi_wready(edge_gp0_wready)
                                                                     , .ds_axi_bresp(edge_gp0_bresp)
                                                                     , .ds_axi_bvalid(edge_gp0_bvalid)
                                                                     , .ds_axi_bready(edge_gp0_bready)
                                                                     , .ds_axi_araddr(edge_gp0_araddr)
                                                                     , .ds_axi_arprot(edge_gp0_arprot)
                                                                     , .ds_axi_arvalid(edge_gp0_arvalid)
                                                                     , .ds_axi_arready(edge_gp0_arready)
                                                                     , .ds_axi_rdata(edge_gp0_rdata)
                                                                     , .ds_axi_rresp(edge_gp0_rresp)
                                                                     , .ds_axi_rvalid(edge_gp0_rvalid)
                                                                     , .ds_axi_rready(edge_gp0_rready) );
// EDGE_LINK_GP0_BEGIN
assign edge_clk=w_port__AXI_Protocol_Converter_0__aclk;
assign edge_rst_n=w_port__AXI_Protocol_Converter_0__aresetn;
edge_axil_router u_edge_gp0(.clk(edge_clk),.rst_n(edge_rst_n),
.s_awaddr(edge_gp0_awaddr),
.p_awaddr(w_port__AXI_Protocol_Converter_0__ds_axi_awaddr),
.s_awprot(edge_gp0_awprot),
.p_awprot(w_port__AXI_Protocol_Converter_0__ds_axi_awprot),
.s_awvalid(edge_gp0_awvalid),
.p_awvalid(w_port__AXI_Protocol_Converter_0__ds_axi_awvalid),
.s_awready(edge_gp0_awready),
.p_awready(w_port__AXI_Protocol_Converter_0__ds_axi_awready),
.s_wdata(edge_gp0_wdata),
.p_wdata(w_port__AXI_Protocol_Converter_0__ds_axi_wdata),
.s_wstrb(edge_gp0_wstrb),
.p_wstrb(w_port__AXI_Protocol_Converter_0__ds_axi_wstrb),
.s_wvalid(edge_gp0_wvalid),
.p_wvalid(w_port__AXI_Protocol_Converter_0__ds_axi_wvalid),
.s_wready(edge_gp0_wready),
.p_wready(w_port__AXI_Protocol_Converter_0__ds_axi_wready),
.s_bresp(edge_gp0_bresp),
.p_bresp(w_port__AXI_Protocol_Converter_0__ds_axi_bresp),
.s_bvalid(edge_gp0_bvalid),
.p_bvalid(w_port__AXI_Protocol_Converter_0__ds_axi_bvalid),
.s_bready(edge_gp0_bready),
.p_bready(w_port__AXI_Protocol_Converter_0__ds_axi_bready),
.s_araddr(edge_gp0_araddr),
.p_araddr(w_port__AXI_Protocol_Converter_0__ds_axi_araddr),
.s_arprot(edge_gp0_arprot),
.p_arprot(w_port__AXI_Protocol_Converter_0__ds_axi_arprot),
.s_arvalid(edge_gp0_arvalid),
.p_arvalid(w_port__AXI_Protocol_Converter_0__ds_axi_arvalid),
.s_arready(edge_gp0_arready),
.p_arready(w_port__AXI_Protocol_Converter_0__ds_axi_arready),
.s_rdata(edge_gp0_rdata),
.p_rdata(w_port__AXI_Protocol_Converter_0__ds_axi_rdata),
.s_rresp(edge_gp0_rresp),
.p_rresp(w_port__AXI_Protocol_Converter_0__ds_axi_rresp),
.s_rvalid(edge_gp0_rvalid),
.p_rvalid(w_port__AXI_Protocol_Converter_0__ds_axi_rvalid),
.s_rready(edge_gp0_rready),
.p_rready(w_port__AXI_Protocol_Converter_0__ds_axi_rready),
.e_awaddr(edge_awaddr),
.e_awvalid(edge_awvalid),
.e_awready(edge_awready),
.e_wdata(edge_wdata),
.e_wstrb(edge_wstrb),
.e_wvalid(edge_wvalid),
.e_wready(edge_wready),
.e_bresp(edge_bresp),
.e_bvalid(edge_bvalid),
.e_bready(edge_bready),
.e_araddr(edge_araddr),
.e_arvalid(edge_arvalid),
.e_arready(edge_arready),
.e_rdata(edge_rdata),
.e_rresp(edge_rresp),
.e_rvalid(edge_rvalid),
.e_rready(edge_rready));
// EDGE_LINK_GP0_END


    design_0_ARM_Processor_System_0 design_0_ARM_Processor_System_0_Inst ( 
                                                                            .slave_hp0_axi_araddr(w_port__ARM_Processor_System_0__slave_hp0_axi_araddr)
                                                                          , .slave_hp0_axi_arburst(w_port__ARM_Processor_System_0__slave_hp0_axi_arburst)
                                                                          , .slave_hp0_axi_arcache(w_port__ARM_Processor_System_0__slave_hp0_axi_arcache)
                                                                          , .slave_hp0_axi_arid(w_port__ARM_Processor_System_0__slave_hp0_axi_arid)
                                                                          , .slave_hp0_axi_arlen(w_port__ARM_Processor_System_0__slave_hp0_axi_arlen)
                                                                          , .slave_hp0_axi_arlock(w_port__ARM_Processor_System_0__slave_hp0_axi_arlock)
                                                                          , .slave_hp0_axi_arprot(w_port__ARM_Processor_System_0__slave_hp0_axi_arprot)
                                                                          , .slave_hp0_axi_arqos(4'b0)
                                                                          , .slave_hp0_axi_arready(w_port__ARM_Processor_System_0__slave_hp0_axi_arready)
                                                                          , .slave_hp0_axi_arsize(w_port__ARM_Processor_System_0__slave_hp0_axi_arsize)
                                                                          , .slave_hp0_axi_arvalid(w_port__ARM_Processor_System_0__slave_hp0_axi_arvalid)
                                                                          , .slave_hp0_axi_awaddr(w_port__ARM_Processor_System_0__slave_hp0_axi_awaddr)
                                                                          , .slave_hp0_axi_awburst(w_port__ARM_Processor_System_0__slave_hp0_axi_awburst)
                                                                          , .slave_hp0_axi_awcache(w_port__ARM_Processor_System_0__slave_hp0_axi_awcache)
                                                                          , .slave_hp0_axi_awid(w_port__ARM_Processor_System_0__slave_hp0_axi_awid)
                                                                          , .slave_hp0_axi_awlen(w_port__ARM_Processor_System_0__slave_hp0_axi_awlen)
                                                                          , .slave_hp0_axi_awlock(w_port__ARM_Processor_System_0__slave_hp0_axi_awlock)
                                                                          , .slave_hp0_axi_awprot(w_port__ARM_Processor_System_0__slave_hp0_axi_awprot)
                                                                          , .slave_hp0_axi_awqos(4'b0)
                                                                          , .slave_hp0_axi_awready(w_port__ARM_Processor_System_0__slave_hp0_axi_awready)
                                                                          , .slave_hp0_axi_awsize(w_port__ARM_Processor_System_0__slave_hp0_axi_awsize)
                                                                          , .slave_hp0_axi_awvalid(w_port__ARM_Processor_System_0__slave_hp0_axi_awvalid)
                                                                          , .slave_hp0_axi_bid(w_port__ARM_Processor_System_0__slave_hp0_axi_bid)
                                                                          , .slave_hp0_axi_bready(w_port__ARM_Processor_System_0__slave_hp0_axi_bready)
                                                                          , .slave_hp0_axi_bresp(w_port__ARM_Processor_System_0__slave_hp0_axi_bresp)
                                                                          , .slave_hp0_axi_bvalid(w_port__ARM_Processor_System_0__slave_hp0_axi_bvalid)
                                                                          , .slave_hp0_axi_rdata(w_port__ARM_Processor_System_0__slave_hp0_axi_rdata)
                                                                          , .slave_hp0_axi_rid(w_port__ARM_Processor_System_0__slave_hp0_axi_rid)
                                                                          , .slave_hp0_axi_rlast(w_port__ARM_Processor_System_0__slave_hp0_axi_rlast)
                                                                          , .slave_hp0_axi_rready(w_port__ARM_Processor_System_0__slave_hp0_axi_rready)
                                                                          , .slave_hp0_axi_rresp(w_port__ARM_Processor_System_0__slave_hp0_axi_rresp)
                                                                          , .slave_hp0_axi_rvalid(w_port__ARM_Processor_System_0__slave_hp0_axi_rvalid)
                                                                          , .slave_hp0_axi_wdata(w_port__ARM_Processor_System_0__slave_hp0_axi_wdata)
                                                                          , .slave_hp0_axi_wlast(w_port__ARM_Processor_System_0__slave_hp0_axi_wlast)
                                                                          , .slave_hp0_axi_wready(w_port__ARM_Processor_System_0__slave_hp0_axi_wready)
                                                                          , .slave_hp0_axi_wstrb(w_port__ARM_Processor_System_0__slave_hp0_axi_wstrb)
                                                                          , .slave_hp0_axi_wvalid(w_port__ARM_Processor_System_0__slave_hp0_axi_wvalid)
                                                                          , .slave_hp1_axi_araddr(w_port__ARM_Processor_System_0__slave_hp1_axi_araddr)
                                                                          , .slave_hp1_axi_arburst(w_port__ARM_Processor_System_0__slave_hp1_axi_arburst)
                                                                          , .slave_hp1_axi_arcache(w_port__ARM_Processor_System_0__slave_hp1_axi_arcache)
                                                                          , .slave_hp1_axi_arid(w_port__ARM_Processor_System_0__slave_hp1_axi_arid)
                                                                          , .slave_hp1_axi_arlen(w_port__ARM_Processor_System_0__slave_hp1_axi_arlen)
                                                                          , .slave_hp1_axi_arlock(w_port__ARM_Processor_System_0__slave_hp1_axi_arlock)
                                                                          , .slave_hp1_axi_arprot(w_port__ARM_Processor_System_0__slave_hp1_axi_arprot)
                                                                          , .slave_hp1_axi_arqos(w_port__ARM_Processor_System_0__slave_hp1_axi_arqos)
                                                                          , .slave_hp1_axi_arready(w_port__ARM_Processor_System_0__slave_hp1_axi_arready)
                                                                          , .slave_hp1_axi_arsize(w_port__ARM_Processor_System_0__slave_hp1_axi_arsize)
                                                                          , .slave_hp1_axi_arvalid(w_port__ARM_Processor_System_0__slave_hp1_axi_arvalid)
                                                                          , .slave_hp1_axi_awaddr(w_port__ARM_Processor_System_0__slave_hp1_axi_awaddr)
                                                                          , .slave_hp1_axi_awburst(w_port__ARM_Processor_System_0__slave_hp1_axi_awburst)
                                                                          , .slave_hp1_axi_awcache(w_port__ARM_Processor_System_0__slave_hp1_axi_awcache)
                                                                          , .slave_hp1_axi_awid(w_port__ARM_Processor_System_0__slave_hp1_axi_awid)
                                                                          , .slave_hp1_axi_awlen(w_port__ARM_Processor_System_0__slave_hp1_axi_awlen)
                                                                          , .slave_hp1_axi_awlock(w_port__ARM_Processor_System_0__slave_hp1_axi_awlock)
                                                                          , .slave_hp1_axi_awprot(w_port__ARM_Processor_System_0__slave_hp1_axi_awprot)
                                                                          , .slave_hp1_axi_awqos(w_port__ARM_Processor_System_0__slave_hp1_axi_awqos)
                                                                          , .slave_hp1_axi_awready(w_port__ARM_Processor_System_0__slave_hp1_axi_awready)
                                                                          , .slave_hp1_axi_awsize(w_port__ARM_Processor_System_0__slave_hp1_axi_awsize)
                                                                          , .slave_hp1_axi_awvalid(w_port__ARM_Processor_System_0__slave_hp1_axi_awvalid)
                                                                          , .slave_hp1_axi_bid(w_port__ARM_Processor_System_0__slave_hp1_axi_bid)
                                                                          , .slave_hp1_axi_bready(w_port__ARM_Processor_System_0__slave_hp1_axi_bready)
                                                                          , .slave_hp1_axi_bresp(w_port__ARM_Processor_System_0__slave_hp1_axi_bresp)
                                                                          , .slave_hp1_axi_bvalid(w_port__ARM_Processor_System_0__slave_hp1_axi_bvalid)
                                                                          , .slave_hp1_axi_rdata(w_port__ARM_Processor_System_0__slave_hp1_axi_rdata)
                                                                          , .slave_hp1_axi_rid(w_port__ARM_Processor_System_0__slave_hp1_axi_rid)
                                                                          , .slave_hp1_axi_rlast(w_port__ARM_Processor_System_0__slave_hp1_axi_rlast)
                                                                          , .slave_hp1_axi_rready(w_port__ARM_Processor_System_0__slave_hp1_axi_rready)
                                                                          , .slave_hp1_axi_rresp(w_port__ARM_Processor_System_0__slave_hp1_axi_rresp)
                                                                          , .slave_hp1_axi_rvalid(w_port__ARM_Processor_System_0__slave_hp1_axi_rvalid)
                                                                          , .slave_hp1_axi_wdata(w_port__ARM_Processor_System_0__slave_hp1_axi_wdata)
                                                                          , .slave_hp1_axi_wlast(w_port__ARM_Processor_System_0__slave_hp1_axi_wlast)
                                                                          , .slave_hp1_axi_wready(w_port__ARM_Processor_System_0__slave_hp1_axi_wready)
                                                                          , .slave_hp1_axi_wstrb(w_port__ARM_Processor_System_0__slave_hp1_axi_wstrb)
                                                                          , .slave_hp1_axi_wvalid(w_port__ARM_Processor_System_0__slave_hp1_axi_wvalid)
                                                                          , .slave_hp0_axi_aclk(w_port__ARM_Processor_System_0__slave_hp0_axi_aclk)
                                                                          , .slave_hp1_axi_aclk(w_port__ARM_Processor_System_0__slave_hp1_axi_aclk)
                                                                          , .master_gp0_axi_aclk(w_port__ARM_Processor_System_0__master_gp0_axi_aclk)
                                                                          , .master_gp1_axi_aclk(w_port__ARM_Processor_System_0__master_gp1_axi_aclk)
                                                                          , .f2p_irq(w_port__ARM_Processor_System_0__f2p_irq)
                                                                          , .master_gp0_axi_araddr(w_port__ARM_Processor_System_0__master_gp0_axi_araddr)
                                                                          , .master_gp0_axi_arburst(w_port__ARM_Processor_System_0__master_gp0_axi_arburst)
                                                                          , .master_gp0_axi_arcache(w_port__ARM_Processor_System_0__master_gp0_axi_arcache)
                                                                          , .master_gp0_axi_arid(w_port__ARM_Processor_System_0__master_gp0_axi_arid)
                                                                          , .master_gp0_axi_arlen(w_port__ARM_Processor_System_0__master_gp0_axi_arlen)
                                                                          , .master_gp0_axi_arlock(w_port__ARM_Processor_System_0__master_gp0_axi_arlock)
                                                                          , .master_gp0_axi_arprot(w_port__ARM_Processor_System_0__master_gp0_axi_arprot)
                                                                          , .master_gp0_axi_arready(w_port__ARM_Processor_System_0__master_gp0_axi_arready)
                                                                          , .master_gp0_axi_arsize(w_port__ARM_Processor_System_0__master_gp0_axi_arsize)
                                                                          , .master_gp0_axi_arvalid(w_port__ARM_Processor_System_0__master_gp0_axi_arvalid)
                                                                          , .master_gp0_axi_awaddr(w_port__ARM_Processor_System_0__master_gp0_axi_awaddr)
                                                                          , .master_gp0_axi_awburst(w_port__ARM_Processor_System_0__master_gp0_axi_awburst)
                                                                          , .master_gp0_axi_awcache(w_port__ARM_Processor_System_0__master_gp0_axi_awcache)
                                                                          , .master_gp0_axi_awid(w_port__ARM_Processor_System_0__master_gp0_axi_awid)
                                                                          , .master_gp0_axi_awlen(w_port__ARM_Processor_System_0__master_gp0_axi_awlen)
                                                                          , .master_gp0_axi_awlock(w_port__ARM_Processor_System_0__master_gp0_axi_awlock)
                                                                          , .master_gp0_axi_awprot(w_port__ARM_Processor_System_0__master_gp0_axi_awprot)
                                                                          , .master_gp0_axi_awready(w_port__ARM_Processor_System_0__master_gp0_axi_awready)
                                                                          , .master_gp0_axi_awsize(w_port__ARM_Processor_System_0__master_gp0_axi_awsize)
                                                                          , .master_gp0_axi_awvalid(w_port__ARM_Processor_System_0__master_gp0_axi_awvalid)
                                                                          , .master_gp0_axi_bid(w_port__ARM_Processor_System_0__master_gp0_axi_bid)
                                                                          , .master_gp0_axi_bready(w_port__ARM_Processor_System_0__master_gp0_axi_bready)
                                                                          , .master_gp0_axi_bresp(w_port__ARM_Processor_System_0__master_gp0_axi_bresp)
                                                                          , .master_gp0_axi_bvalid(w_port__ARM_Processor_System_0__master_gp0_axi_bvalid)
                                                                          , .master_gp0_axi_rdata(w_port__ARM_Processor_System_0__master_gp0_axi_rdata)
                                                                          , .master_gp0_axi_rid(w_port__ARM_Processor_System_0__master_gp0_axi_rid)
                                                                          , .master_gp0_axi_rlast(w_port__ARM_Processor_System_0__master_gp0_axi_rlast)
                                                                          , .master_gp0_axi_rready(w_port__ARM_Processor_System_0__master_gp0_axi_rready)
                                                                          , .master_gp0_axi_rresp(w_port__ARM_Processor_System_0__master_gp0_axi_rresp)
                                                                          , .master_gp0_axi_rvalid(w_port__ARM_Processor_System_0__master_gp0_axi_rvalid)
                                                                          , .master_gp0_axi_wdata(w_port__ARM_Processor_System_0__master_gp0_axi_wdata)
                                                                          , .master_gp0_axi_wlast(w_port__ARM_Processor_System_0__master_gp0_axi_wlast)
                                                                          , .master_gp0_axi_wready(w_port__ARM_Processor_System_0__master_gp0_axi_wready)
                                                                          , .master_gp0_axi_wstrb(w_port__ARM_Processor_System_0__master_gp0_axi_wstrb)
                                                                          , .master_gp0_axi_wvalid(w_port__ARM_Processor_System_0__master_gp0_axi_wvalid)
                                                                          , .master_gp1_axi_araddr(w_port__ARM_Processor_System_0__master_gp1_axi_araddr)
                                                                          , .master_gp1_axi_arburst(w_port__ARM_Processor_System_0__master_gp1_axi_arburst)
                                                                          , .master_gp1_axi_arcache(w_port__ARM_Processor_System_0__master_gp1_axi_arcache)
                                                                          , .master_gp1_axi_arid(w_port__ARM_Processor_System_0__master_gp1_axi_arid)
                                                                          , .master_gp1_axi_arlen(w_port__ARM_Processor_System_0__master_gp1_axi_arlen)
                                                                          , .master_gp1_axi_arlock(w_port__ARM_Processor_System_0__master_gp1_axi_arlock)
                                                                          , .master_gp1_axi_arprot(w_port__ARM_Processor_System_0__master_gp1_axi_arprot)
                                                                          , .master_gp1_axi_arready(w_port__ARM_Processor_System_0__master_gp1_axi_arready)
                                                                          , .master_gp1_axi_arsize(w_port__ARM_Processor_System_0__master_gp1_axi_arsize)
                                                                          , .master_gp1_axi_arvalid(w_port__ARM_Processor_System_0__master_gp1_axi_arvalid)
                                                                          , .master_gp1_axi_awaddr(w_port__ARM_Processor_System_0__master_gp1_axi_awaddr)
                                                                          , .master_gp1_axi_awburst(w_port__ARM_Processor_System_0__master_gp1_axi_awburst)
                                                                          , .master_gp1_axi_awcache(w_port__ARM_Processor_System_0__master_gp1_axi_awcache)
                                                                          , .master_gp1_axi_awid(w_port__ARM_Processor_System_0__master_gp1_axi_awid)
                                                                          , .master_gp1_axi_awlen(w_port__ARM_Processor_System_0__master_gp1_axi_awlen)
                                                                          , .master_gp1_axi_awlock(w_port__ARM_Processor_System_0__master_gp1_axi_awlock)
                                                                          , .master_gp1_axi_awprot(w_port__ARM_Processor_System_0__master_gp1_axi_awprot)
                                                                          , .master_gp1_axi_awready(w_port__ARM_Processor_System_0__master_gp1_axi_awready)
                                                                          , .master_gp1_axi_awsize(w_port__ARM_Processor_System_0__master_gp1_axi_awsize)
                                                                          , .master_gp1_axi_awvalid(w_port__ARM_Processor_System_0__master_gp1_axi_awvalid)
                                                                          , .master_gp1_axi_bid(w_port__ARM_Processor_System_0__master_gp1_axi_bid)
                                                                          , .master_gp1_axi_bready(w_port__ARM_Processor_System_0__master_gp1_axi_bready)
                                                                          , .master_gp1_axi_bresp(w_port__ARM_Processor_System_0__master_gp1_axi_bresp)
                                                                          , .master_gp1_axi_bvalid(w_port__ARM_Processor_System_0__master_gp1_axi_bvalid)
                                                                          , .master_gp1_axi_rdata(w_port__ARM_Processor_System_0__master_gp1_axi_rdata)
                                                                          , .master_gp1_axi_rid(w_port__ARM_Processor_System_0__master_gp1_axi_rid)
                                                                          , .master_gp1_axi_rlast(w_port__ARM_Processor_System_0__master_gp1_axi_rlast)
                                                                          , .master_gp1_axi_rready(w_port__ARM_Processor_System_0__master_gp1_axi_rready)
                                                                          , .master_gp1_axi_rresp(w_port__ARM_Processor_System_0__master_gp1_axi_rresp)
                                                                          , .master_gp1_axi_rvalid(w_port__ARM_Processor_System_0__master_gp1_axi_rvalid)
                                                                          , .master_gp1_axi_wdata(w_port__ARM_Processor_System_0__master_gp1_axi_wdata)
                                                                          , .master_gp1_axi_wlast(w_port__ARM_Processor_System_0__master_gp1_axi_wlast)
                                                                          , .master_gp1_axi_wready(w_port__ARM_Processor_System_0__master_gp1_axi_wready)
                                                                          , .master_gp1_axi_wstrb(w_port__ARM_Processor_System_0__master_gp1_axi_wstrb)
                                                                          , .master_gp1_axi_wvalid(w_port__ARM_Processor_System_0__master_gp1_axi_wvalid)
                                                                          , .i2c0_scl_in(w_port__ARM_Processor_System_0__i2c0_scl_in)
                                                                          , .i2c0_scl_oe(w_port__ARM_Processor_System_0__i2c0_scl_oe)
                                                                          , .i2c0_sda_in(w_port__ARM_Processor_System_0__i2c0_sda_in)
                                                                          , .i2c0_sda_oe(w_port__ARM_Processor_System_0__i2c0_sda_oe)
                                                                          , .i2c1_scl_in(1'b0)
                                                                          , .i2c1_scl_oe()
                                                                          , .i2c1_sda_in(1'b0)
                                                                          , .i2c1_sda_oe()
                                                                          , .tc0_clk0_in(1'b0)
                                                                          , .tc0_clk1_in(1'b0)
                                                                          , .tc0_clk2_in(1'b0)
                                                                          , .tc0_wave0_out()
                                                                          , .tc0_wave1_out()
                                                                          , .tc0_wave2_out()
                                                                          , .p2f_rst0_n(w_port__ARM_Processor_System_0__p2f_rst0_n)
                                                                          , .p2f_clk0(w_port__ARM_Processor_System_0__p2f_clk0) );

    design_0_Concat_0 design_0_Concat_0_Inst ( 
                                                .In0(w_port__Concat_0__In0)
                                              , .In1(1'b0)
                                              , .In2(w_port__Concat_0__In2)
                                              , .In3(1'b0)
                                              , .In4(1'b0)
                                              , .In5(1'b0)
                                              , .In6(1'b0)
                                              , .In7(1'b0)
                                              , .In8(1'b0)
                                              , .In9(1'b0)
                                              , .In10(1'b0)
                                              , .In11(1'b0)
                                              , .In12(1'b0)
                                              , .In13(1'b0)
                                              , .In14(1'b0)
                                              , .In15(w_port__Concat_0__In15)
                                              , .Dout(w_port__Concat_0__Dout) );

    design_0_AXI_Matrix_0 design_0_AXI_Matrix_0_Inst ( 
                                                        .us0_araddr(w_port__AXI_Matrix_0__us0_araddr)
                                                      , .us0_arprot(w_port__AXI_Matrix_0__us0_arprot)
                                                      , .us0_arready(w_port__AXI_Matrix_0__us0_arready)
                                                      , .us0_arvalid(w_port__AXI_Matrix_0__us0_arvalid)
                                                      , .us0_awaddr(w_port__AXI_Matrix_0__us0_awaddr)
                                                      , .us0_awprot(w_port__AXI_Matrix_0__us0_awprot)
                                                      , .us0_awready(w_port__AXI_Matrix_0__us0_awready)
                                                      , .us0_awvalid(w_port__AXI_Matrix_0__us0_awvalid)
                                                      , .us0_bready(w_port__AXI_Matrix_0__us0_bready)
                                                      , .us0_bresp(w_port__AXI_Matrix_0__us0_bresp)
                                                      , .us0_bvalid(w_port__AXI_Matrix_0__us0_bvalid)
                                                      , .us0_rdata(w_port__AXI_Matrix_0__us0_rdata)
                                                      , .us0_rready(w_port__AXI_Matrix_0__us0_rready)
                                                      , .us0_rresp(w_port__AXI_Matrix_0__us0_rresp)
                                                      , .us0_rvalid(w_port__AXI_Matrix_0__us0_rvalid)
                                                      , .us0_wdata(w_port__AXI_Matrix_0__us0_wdata)
                                                      , .us0_wready(w_port__AXI_Matrix_0__us0_wready)
                                                      , .us0_wstrb(w_port__AXI_Matrix_0__us0_wstrb)
                                                      , .us0_wvalid(w_port__AXI_Matrix_0__us0_wvalid)
                                                      , .aclk(w_port__AXI_Matrix_0__aclk)
                                                      , .aresetn(w_port__AXI_Matrix_0__aresetn)
                                                      , .ds0_araddr(w_port__AXI_Matrix_0__ds0_araddr)
                                                      , .ds0_arprot()
                                                      , .ds0_arready(w_port__AXI_Matrix_0__ds0_arready)
                                                      , .ds0_arvalid(w_port__AXI_Matrix_0__ds0_arvalid)
                                                      , .ds0_awaddr(w_port__AXI_Matrix_0__ds0_awaddr)
                                                      , .ds0_awprot()
                                                      , .ds0_awready(w_port__AXI_Matrix_0__ds0_awready)
                                                      , .ds0_awvalid(w_port__AXI_Matrix_0__ds0_awvalid)
                                                      , .ds0_bready(w_port__AXI_Matrix_0__ds0_bready)
                                                      , .ds0_bresp(w_port__AXI_Matrix_0__ds0_bresp)
                                                      , .ds0_bvalid(w_port__AXI_Matrix_0__ds0_bvalid)
                                                      , .ds0_rdata(w_port__AXI_Matrix_0__ds0_rdata)
                                                      , .ds0_rready(w_port__AXI_Matrix_0__ds0_rready)
                                                      , .ds0_rresp(w_port__AXI_Matrix_0__ds0_rresp)
                                                      , .ds0_rvalid(w_port__AXI_Matrix_0__ds0_rvalid)
                                                      , .ds0_wdata(w_port__AXI_Matrix_0__ds0_wdata)
                                                      , .ds0_wready(w_port__AXI_Matrix_0__ds0_wready)
                                                      , .ds0_wstrb()
                                                      , .ds0_wvalid(w_port__AXI_Matrix_0__ds0_wvalid)
                                                      , .ds1_araddr(w_port__AXI_Matrix_0__ds1_araddr)
                                                      , .ds1_arprot()
                                                      , .ds1_arready(w_port__AXI_Matrix_0__ds1_arready)
                                                      , .ds1_arvalid(w_port__AXI_Matrix_0__ds1_arvalid)
                                                      , .ds1_awaddr(w_port__AXI_Matrix_0__ds1_awaddr)
                                                      , .ds1_awprot()
                                                      , .ds1_awready(w_port__AXI_Matrix_0__ds1_awready)
                                                      , .ds1_awvalid(w_port__AXI_Matrix_0__ds1_awvalid)
                                                      , .ds1_bready(w_port__AXI_Matrix_0__ds1_bready)
                                                      , .ds1_bresp(w_port__AXI_Matrix_0__ds1_bresp)
                                                      , .ds1_bvalid(w_port__AXI_Matrix_0__ds1_bvalid)
                                                      , .ds1_rdata(w_port__AXI_Matrix_0__ds1_rdata)
                                                      , .ds1_rready(w_port__AXI_Matrix_0__ds1_rready)
                                                      , .ds1_rresp(w_port__AXI_Matrix_0__ds1_rresp)
                                                      , .ds1_rvalid(w_port__AXI_Matrix_0__ds1_rvalid)
                                                      , .ds1_wdata(w_port__AXI_Matrix_0__ds1_wdata)
                                                      , .ds1_wready(w_port__AXI_Matrix_0__ds1_wready)
                                                      , .ds1_wstrb(w_port__AXI_Matrix_0__ds1_wstrb)
                                                      , .ds1_wvalid(w_port__AXI_Matrix_0__ds1_wvalid)
                                                      , .ds2_araddr(w_port__AXI_Matrix_0__ds2_araddr)
                                                      , .ds2_arprot(w_port__AXI_Matrix_0__ds2_arprot)
                                                      , .ds2_arready(w_port__AXI_Matrix_0__ds2_arready)
                                                      , .ds2_arvalid(w_port__AXI_Matrix_0__ds2_arvalid)
                                                      , .ds2_awaddr(w_port__AXI_Matrix_0__ds2_awaddr)
                                                      , .ds2_awprot(w_port__AXI_Matrix_0__ds2_awprot)
                                                      , .ds2_awready(w_port__AXI_Matrix_0__ds2_awready)
                                                      , .ds2_awvalid(w_port__AXI_Matrix_0__ds2_awvalid)
                                                      , .ds2_bready(w_port__AXI_Matrix_0__ds2_bready)
                                                      , .ds2_bresp(w_port__AXI_Matrix_0__ds2_bresp)
                                                      , .ds2_bvalid(w_port__AXI_Matrix_0__ds2_bvalid)
                                                      , .ds2_rdata(w_port__AXI_Matrix_0__ds2_rdata)
                                                      , .ds2_rready(w_port__AXI_Matrix_0__ds2_rready)
                                                      , .ds2_rresp(w_port__AXI_Matrix_0__ds2_rresp)
                                                      , .ds2_rvalid(w_port__AXI_Matrix_0__ds2_rvalid)
                                                      , .ds2_wdata(w_port__AXI_Matrix_0__ds2_wdata)
                                                      , .ds2_wready(w_port__AXI_Matrix_0__ds2_wready)
                                                      , .ds2_wstrb(w_port__AXI_Matrix_0__ds2_wstrb)
                                                      , .ds2_wvalid(w_port__AXI_Matrix_0__ds2_wvalid) );

    design_0_PLL_0 design_0_pll_75m_Inst ( 
                                            .refclk(w_port__pll_75m__refclk)
                                          , .clk0_out(w_port__pll_75m__clk0_out)
                                          , .clk1_out(w_shared_fabric_clk150)
                                          , .lock(w_port__pll_75m__lock) );

    design_0_Processor_System_Reset_0 design_0_rst_n_75m_Inst ( 
                                                                 .clk(w_port__rst_n_75m__clk)
                                                               , .external_reset(1'b0)
                                                               , .aux_rst(w_port__rst_n_75m__aux_rst)
                                                               , .system_rst(1'b0)
                                                               , .pll_locked(w_port__rst_n_75m__pll_locked)
                                                               , .soc_reset()
                                                               , .bus_reset()
                                                               , .peripheral_reset()
                                                               , .interconnect_aresetn(w_port__rst_n_75m__interconnect_aresetn)
                                                               , .peripheral_aresetn() );



    design_0_Processor_System_Reset_1 design_0_rstn_150m_Inst ( 
                                                                 .clk(w_port__rstn_150m__clk)
                                                               , .external_reset(1'b0)
                                                               , .aux_rst(w_port__rstn_150m__aux_rst)
                                                               , .system_rst(1'b0)
                                                               , .pll_locked(w_port__rstn_150m__pll_locked)
                                                               , .soc_reset()
                                                               , .bus_reset()
                                                               , .peripheral_reset()
                                                               , .interconnect_aresetn()
                                                               , .peripheral_aresetn(w_port__rstn_150m__peripheral_aresetn) );

    design_0_pwm_0 design_0_pwm_0_Inst ( 
                                          .clk(w_port__pwm_0__clk)
                                        , .rst_n(w_port__pwm_0__rst_n)
                                        , .pwm_out(w_port__pwm_0__pwm_out) );



    design_0_Processor_System_Reset_2 design_0_rstn_npu_Inst ( 
                                                                .clk(w_port__rstn_npu__clk)
                                                              , .external_reset(1'b0)
                                                              , .aux_rst(w_port__rstn_npu__aux_rst)
                                                              , .system_rst(1'b0)
                                                              , .pll_locked(w_port__rstn_npu__pll_locked)
                                                              , .soc_reset()
                                                              , .bus_reset()
                                                              , .peripheral_reset()
                                                              , .interconnect_aresetn(w_port__rstn_npu__interconnect_aresetn)
                                                              , .peripheral_aresetn(w_port__rstn_npu__peripheral_aresetn) );

    design_0_AXI_Matrix_1 design_0_AXI_Matrix_1_Inst ( 
                                                        .us0_awid(w_port__AXI_Matrix_1__us0_awid)
                                                      , .us0_awaddr(w_port__AXI_Matrix_1__us0_awaddr)
                                                      , .us0_awlen(w_port__AXI_Matrix_1__us0_awlen)
                                                      , .us0_awsize(w_port__AXI_Matrix_1__us0_awsize)
                                                      , .us0_awburst(w_port__AXI_Matrix_1__us0_awburst)
                                                      , .us0_awlock(w_port__AXI_Matrix_1__us0_awlock)
                                                      , .us0_awcache(w_port__AXI_Matrix_1__us0_awcache)
                                                      , .us0_awprot(w_port__AXI_Matrix_1__us0_awprot)
                                                      , .us0_awvalid(w_port__AXI_Matrix_1__us0_awvalid)
                                                      , .us0_awready(w_port__AXI_Matrix_1__us0_awready)
                                                      , .us0_wdata(w_port__AXI_Matrix_1__us0_wdata)
                                                      , .us0_wstrb(w_port__AXI_Matrix_1__us0_wstrb)
                                                      , .us0_wlast(w_port__AXI_Matrix_1__us0_wlast)
                                                      , .us0_wvalid(w_port__AXI_Matrix_1__us0_wvalid)
                                                      , .us0_wready(w_port__AXI_Matrix_1__us0_wready)
                                                      , .us0_bid(w_port__AXI_Matrix_1__us0_bid)
                                                      , .us0_bresp(w_port__AXI_Matrix_1__us0_bresp)
                                                      , .us0_bvalid(w_port__AXI_Matrix_1__us0_bvalid)
                                                      , .us0_bready(w_port__AXI_Matrix_1__us0_bready)
                                                      , .us0_arid(w_port__AXI_Matrix_1__us0_arid)
                                                      , .us0_araddr(w_port__AXI_Matrix_1__us0_araddr)
                                                      , .us0_arlen(w_port__AXI_Matrix_1__us0_arlen)
                                                      , .us0_arsize(w_port__AXI_Matrix_1__us0_arsize)
                                                      , .us0_arburst(w_port__AXI_Matrix_1__us0_arburst)
                                                      , .us0_arlock(w_port__AXI_Matrix_1__us0_arlock)
                                                      , .us0_arcache(w_port__AXI_Matrix_1__us0_arcache)
                                                      , .us0_arprot(w_port__AXI_Matrix_1__us0_arprot)
                                                      , .us0_arvalid(w_port__AXI_Matrix_1__us0_arvalid)
                                                      , .us0_arready(w_port__AXI_Matrix_1__us0_arready)
                                                      , .us0_rid(w_port__AXI_Matrix_1__us0_rid)
                                                      , .us0_rdata(w_port__AXI_Matrix_1__us0_rdata)
                                                      , .us0_rresp(w_port__AXI_Matrix_1__us0_rresp)
                                                      , .us0_rlast(w_port__AXI_Matrix_1__us0_rlast)
                                                      , .us0_rvalid(w_port__AXI_Matrix_1__us0_rvalid)
                                                      , .us0_rready(w_port__AXI_Matrix_1__us0_rready)
                                                      , .us0_awqos(4'b0)
                                                      , .us0_arqos(4'b0)
                                                      , .aclk(w_port__AXI_Matrix_1__aclk)
                                                      , .aresetn(w_port__AXI_Matrix_1__aresetn)
                                                      , .ds0_awid(w_port__AXI_Matrix_1__ds0_awid)
                                                      , .ds0_awaddr(w_port__AXI_Matrix_1__ds0_awaddr)
                                                      , .ds0_awlen(w_port__AXI_Matrix_1__ds0_awlen)
                                                      , .ds0_awsize(w_port__AXI_Matrix_1__ds0_awsize)
                                                      , .ds0_awburst(w_port__AXI_Matrix_1__ds0_awburst)
                                                      , .ds0_awlock(w_port__AXI_Matrix_1__ds0_awlock)
                                                      , .ds0_awcache(w_port__AXI_Matrix_1__ds0_awcache)
                                                      , .ds0_awprot(w_port__AXI_Matrix_1__ds0_awprot)
                                                      , .ds0_awvalid(w_port__AXI_Matrix_1__ds0_awvalid)
                                                      , .ds0_awready(w_port__AXI_Matrix_1__ds0_awready)
                                                      , .ds0_wdata(w_port__AXI_Matrix_1__ds0_wdata)
                                                      , .ds0_wstrb(w_port__AXI_Matrix_1__ds0_wstrb)
                                                      , .ds0_wlast(w_port__AXI_Matrix_1__ds0_wlast)
                                                      , .ds0_wvalid(w_port__AXI_Matrix_1__ds0_wvalid)
                                                      , .ds0_wready(w_port__AXI_Matrix_1__ds0_wready)
                                                      , .ds0_bid(w_port__AXI_Matrix_1__ds0_bid)
                                                      , .ds0_bresp(w_port__AXI_Matrix_1__ds0_bresp)
                                                      , .ds0_bvalid(w_port__AXI_Matrix_1__ds0_bvalid)
                                                      , .ds0_bready(w_port__AXI_Matrix_1__ds0_bready)
                                                      , .ds0_arid(w_port__AXI_Matrix_1__ds0_arid)
                                                      , .ds0_araddr(w_port__AXI_Matrix_1__ds0_araddr)
                                                      , .ds0_arlen(w_port__AXI_Matrix_1__ds0_arlen)
                                                      , .ds0_arsize(w_port__AXI_Matrix_1__ds0_arsize)
                                                      , .ds0_arburst(w_port__AXI_Matrix_1__ds0_arburst)
                                                      , .ds0_arlock(w_port__AXI_Matrix_1__ds0_arlock)
                                                      , .ds0_arcache(w_port__AXI_Matrix_1__ds0_arcache)
                                                      , .ds0_arprot(w_port__AXI_Matrix_1__ds0_arprot)
                                                      , .ds0_arvalid(w_port__AXI_Matrix_1__ds0_arvalid)
                                                      , .ds0_arready(w_port__AXI_Matrix_1__ds0_arready)
                                                      , .ds0_rid(w_port__AXI_Matrix_1__ds0_rid)
                                                      , .ds0_rdata(w_port__AXI_Matrix_1__ds0_rdata)
                                                      , .ds0_rresp(w_port__AXI_Matrix_1__ds0_rresp)
                                                      , .ds0_rlast(w_port__AXI_Matrix_1__ds0_rlast)
                                                      , .ds0_rvalid(w_port__AXI_Matrix_1__ds0_rvalid)
                                                      , .ds0_rready(w_port__AXI_Matrix_1__ds0_rready)
                                                      , .ds0_awqos(w_port__AXI_Matrix_1__ds0_awqos)
                                                      , .ds0_awregion()
                                                      , .ds0_arqos(w_port__AXI_Matrix_1__ds0_arqos)
                                                      , .ds0_arregion()
                                                      , .ds1_awid()
                                                      , .ds1_awaddr()
                                                      , .ds1_awlen()
                                                      , .ds1_awsize()
                                                      , .ds1_awburst()
                                                      , .ds1_awlock()
                                                      , .ds1_awcache()
                                                      , .ds1_awprot()
                                                      , .ds1_awvalid()
                                                      , .ds1_awready(1'b0)
                                                      , .ds1_wdata()
                                                      , .ds1_wstrb()
                                                      , .ds1_wlast()
                                                      , .ds1_wvalid()
                                                      , .ds1_wready(1'b0)
                                                      , .ds1_bid(13'b0)
                                                      , .ds1_bresp(2'b0)
                                                      , .ds1_bvalid(1'b0)
                                                      , .ds1_bready()
                                                      , .ds1_arid()
                                                      , .ds1_araddr()
                                                      , .ds1_arlen()
                                                      , .ds1_arsize()
                                                      , .ds1_arburst()
                                                      , .ds1_arlock()
                                                      , .ds1_arcache()
                                                      , .ds1_arprot()
                                                      , .ds1_arvalid()
                                                      , .ds1_arready(1'b0)
                                                      , .ds1_rid(13'b0)
                                                      , .ds1_rdata(32'b0)
                                                      , .ds1_rresp(2'b0)
                                                      , .ds1_rlast(1'b0)
                                                      , .ds1_rvalid(1'b0)
                                                      , .ds1_rready()
                                                      , .ds1_awqos()
                                                      , .ds1_awregion()
                                                      , .ds1_arqos()
                                                      , .ds1_arregion() );

    design_0_AXI_Protocol_Converter_1 design_0_AXI_Protocol_Converter_1_Inst ( 
                                                                                .us_axi_awid(w_port__AXI_Protocol_Converter_1__us_axi_awid)
                                                                              , .us_axi_awaddr(w_port__AXI_Protocol_Converter_1__us_axi_awaddr)
                                                                              , .us_axi_awlen(w_port__AXI_Protocol_Converter_1__us_axi_awlen)
                                                                              , .us_axi_awsize(w_port__AXI_Protocol_Converter_1__us_axi_awsize)
                                                                              , .us_axi_awburst(w_port__AXI_Protocol_Converter_1__us_axi_awburst)
                                                                              , .us_axi_awlock(w_port__AXI_Protocol_Converter_1__us_axi_awlock)
                                                                              , .us_axi_awcache(w_port__AXI_Protocol_Converter_1__us_axi_awcache)
                                                                              , .us_axi_awprot(w_port__AXI_Protocol_Converter_1__us_axi_awprot)
                                                                              , .us_axi_awvalid(w_port__AXI_Protocol_Converter_1__us_axi_awvalid)
                                                                              , .us_axi_awready(w_port__AXI_Protocol_Converter_1__us_axi_awready)
                                                                              , .us_axi_wdata(w_port__AXI_Protocol_Converter_1__us_axi_wdata)
                                                                              , .us_axi_wstrb(w_port__AXI_Protocol_Converter_1__us_axi_wstrb)
                                                                              , .us_axi_wlast(w_port__AXI_Protocol_Converter_1__us_axi_wlast)
                                                                              , .us_axi_wvalid(w_port__AXI_Protocol_Converter_1__us_axi_wvalid)
                                                                              , .us_axi_wready(w_port__AXI_Protocol_Converter_1__us_axi_wready)
                                                                              , .us_axi_bid(w_port__AXI_Protocol_Converter_1__us_axi_bid)
                                                                              , .us_axi_bresp(w_port__AXI_Protocol_Converter_1__us_axi_bresp)
                                                                              , .us_axi_bvalid(w_port__AXI_Protocol_Converter_1__us_axi_bvalid)
                                                                              , .us_axi_bready(w_port__AXI_Protocol_Converter_1__us_axi_bready)
                                                                              , .us_axi_arid(w_port__AXI_Protocol_Converter_1__us_axi_arid)
                                                                              , .us_axi_araddr(w_port__AXI_Protocol_Converter_1__us_axi_araddr)
                                                                              , .us_axi_arlen(w_port__AXI_Protocol_Converter_1__us_axi_arlen)
                                                                              , .us_axi_arsize(w_port__AXI_Protocol_Converter_1__us_axi_arsize)
                                                                              , .us_axi_arburst(w_port__AXI_Protocol_Converter_1__us_axi_arburst)
                                                                              , .us_axi_arlock(w_port__AXI_Protocol_Converter_1__us_axi_arlock)
                                                                              , .us_axi_arcache(w_port__AXI_Protocol_Converter_1__us_axi_arcache)
                                                                              , .us_axi_arprot(w_port__AXI_Protocol_Converter_1__us_axi_arprot)
                                                                              , .us_axi_arvalid(w_port__AXI_Protocol_Converter_1__us_axi_arvalid)
                                                                              , .us_axi_arready(w_port__AXI_Protocol_Converter_1__us_axi_arready)
                                                                              , .us_axi_rid(w_port__AXI_Protocol_Converter_1__us_axi_rid)
                                                                              , .us_axi_rdata(w_port__AXI_Protocol_Converter_1__us_axi_rdata)
                                                                              , .us_axi_rresp(w_port__AXI_Protocol_Converter_1__us_axi_rresp)
                                                                              , .us_axi_rlast(w_port__AXI_Protocol_Converter_1__us_axi_rlast)
                                                                              , .us_axi_rvalid(w_port__AXI_Protocol_Converter_1__us_axi_rvalid)
                                                                              , .us_axi_rready(w_port__AXI_Protocol_Converter_1__us_axi_rready)
                                                                              , .us_axi_awuser(1'b0)
                                                                              , .us_axi_awqos(w_port__AXI_Protocol_Converter_1__us_axi_awqos)
                                                                              , .us_axi_wuser(1'b0)
                                                                              , .us_axi_buser()
                                                                              , .us_axi_aruser(1'b0)
                                                                              , .us_axi_arqos(w_port__AXI_Protocol_Converter_1__us_axi_arqos)
                                                                              , .us_axi_ruser()
                                                                              , .aclk(w_port__AXI_Protocol_Converter_1__aclk)
                                                                              , .aresetn(w_port__AXI_Protocol_Converter_1__aresetn)
                                                                              , .ds_axi_awaddr(w_port__AXI_Protocol_Converter_1__ds_axi_awaddr)
                                                                              , .ds_axi_awprot(w_port__AXI_Protocol_Converter_1__ds_axi_awprot)
                                                                              , .ds_axi_awvalid(w_port__AXI_Protocol_Converter_1__ds_axi_awvalid)
                                                                              , .ds_axi_awready(w_port__AXI_Protocol_Converter_1__ds_axi_awready)
                                                                              , .ds_axi_wdata(w_port__AXI_Protocol_Converter_1__ds_axi_wdata)
                                                                              , .ds_axi_wstrb(w_port__AXI_Protocol_Converter_1__ds_axi_wstrb)
                                                                              , .ds_axi_wvalid(w_port__AXI_Protocol_Converter_1__ds_axi_wvalid)
                                                                              , .ds_axi_wready(w_port__AXI_Protocol_Converter_1__ds_axi_wready)
                                                                              , .ds_axi_bresp(w_port__AXI_Protocol_Converter_1__ds_axi_bresp)
                                                                              , .ds_axi_bvalid(w_port__AXI_Protocol_Converter_1__ds_axi_bvalid)
                                                                              , .ds_axi_bready(w_port__AXI_Protocol_Converter_1__ds_axi_bready)
                                                                              , .ds_axi_araddr(w_port__AXI_Protocol_Converter_1__ds_axi_araddr)
                                                                              , .ds_axi_arprot(w_port__AXI_Protocol_Converter_1__ds_axi_arprot)
                                                                              , .ds_axi_arvalid(w_port__AXI_Protocol_Converter_1__ds_axi_arvalid)
                                                                              , .ds_axi_arready(w_port__AXI_Protocol_Converter_1__ds_axi_arready)
                                                                              , .ds_axi_rdata(w_port__AXI_Protocol_Converter_1__ds_axi_rdata)
                                                                              , .ds_axi_rresp(w_port__AXI_Protocol_Converter_1__ds_axi_rresp)
                                                                              , .ds_axi_rvalid(w_port__AXI_Protocol_Converter_1__ds_axi_rvalid)
                                                                              , .ds_axi_rready(w_port__AXI_Protocol_Converter_1__ds_axi_rready) );

    design_0_Video_NPU_0 design_0_Video_NPU_0_Inst ( 
                                                      .s_axilite_awaddr_i(w_port__Video_NPU_0__s_axilite_awaddr_i)
                                                    , .s_axilite_awprot_i(w_port__Video_NPU_0__s_axilite_awprot_i)
                                                    , .s_axilite_awvalid_i(w_port__Video_NPU_0__s_axilite_awvalid_i)
                                                    , .s_axilite_awready_o(w_port__Video_NPU_0__s_axilite_awready_o)
                                                    , .s_axilite_wdata_i(w_port__Video_NPU_0__s_axilite_wdata_i)
                                                    , .s_axilite_wstrb_i(w_port__Video_NPU_0__s_axilite_wstrb_i)
                                                    , .s_axilite_wvalid_i(w_port__Video_NPU_0__s_axilite_wvalid_i)
                                                    , .s_axilite_wready_o(w_port__Video_NPU_0__s_axilite_wready_o)
                                                    , .s_axilite_bresp_o(w_port__Video_NPU_0__s_axilite_bresp_o)
                                                    , .s_axilite_bvalid_o(w_port__Video_NPU_0__s_axilite_bvalid_o)
                                                    , .s_axilite_bready_i(w_port__Video_NPU_0__s_axilite_bready_i)
                                                    , .s_axilite_araddr_i(w_port__Video_NPU_0__s_axilite_araddr_i)
                                                    , .s_axilite_arprot_i(w_port__Video_NPU_0__s_axilite_arprot_i)
                                                    , .s_axilite_arvalid_i(w_port__Video_NPU_0__s_axilite_arvalid_i)
                                                    , .s_axilite_arready_o(w_port__Video_NPU_0__s_axilite_arready_o)
                                                    , .s_axilite_rdata_o(w_port__Video_NPU_0__s_axilite_rdata_o)
                                                    , .s_axilite_rresp_o(w_port__Video_NPU_0__s_axilite_rresp_o)
                                                    , .s_axilite_rvalid_o(w_port__Video_NPU_0__s_axilite_rvalid_o)
                                                    , .s_axilite_rready_i(w_port__Video_NPU_0__s_axilite_rready_i)
                                                    , .S_AXILite_ACLK(w_port__Video_NPU_0__S_AXILite_ACLK)
                                                    , .S_AXILite_AResetn(w_port__Video_NPU_0__S_AXILite_AResetn)
                                                    , .M_AXI_ACLK(w_port__Video_NPU_0__M_AXI_ACLK)
                                                    , .M_AXI_AResetn(w_port__Video_NPU_0__M_AXI_AResetn)
                                                    , .m_axi_awid_soft_o(w_port__Video_NPU_0__m_axi_awid_soft_o)
                                                    , .m_axi_awaddr_soft_o(w_port__Video_NPU_0__m_axi_awaddr_soft_o)
                                                    , .m_axi_awlen_soft_o(w_port__Video_NPU_0__m_axi_awlen_soft_o)
                                                    , .m_axi_awsize_soft_o(w_port__Video_NPU_0__m_axi_awsize_soft_o)
                                                    , .m_axi_awburst_soft_o(w_port__Video_NPU_0__m_axi_awburst_soft_o)
                                                    , .m_axi_awlock_soft_o(w_port__Video_NPU_0__m_axi_awlock_soft_o)
                                                    , .m_axi_awcache_soft_o(w_port__Video_NPU_0__m_axi_awcache_soft_o)
                                                    , .m_axi_awprot_soft_o(w_port__Video_NPU_0__m_axi_awprot_soft_o)
                                                    , .m_axi_awvalid_soft_o(w_port__Video_NPU_0__m_axi_awvalid_soft_o)
                                                    , .m_axi_awready_soft_i(w_port__Video_NPU_0__m_axi_awready_soft_i)
                                                    , .m_axi_wdata_soft_o(w_port__Video_NPU_0__m_axi_wdata_soft_o)
                                                    , .m_axi_wstrb_soft_o(w_port__Video_NPU_0__m_axi_wstrb_soft_o)
                                                    , .m_axi_wlast_soft_o(w_port__Video_NPU_0__m_axi_wlast_soft_o)
                                                    , .m_axi_wvalid_soft_o(w_port__Video_NPU_0__m_axi_wvalid_soft_o)
                                                    , .m_axi_wready_soft_i(w_port__Video_NPU_0__m_axi_wready_soft_i)
                                                    , .m_axi_bid_soft_i(w_port__Video_NPU_0__m_axi_bid_soft_i)
                                                    , .m_axi_bresp_soft_i(w_port__Video_NPU_0__m_axi_bresp_soft_i)
                                                    , .m_axi_bvalid_soft_i(w_port__Video_NPU_0__m_axi_bvalid_soft_i)
                                                    , .m_axi_bready_soft_o(w_port__Video_NPU_0__m_axi_bready_soft_o)
                                                    , .m_axi_arid_soft_o(w_port__Video_NPU_0__m_axi_arid_soft_o)
                                                    , .m_axi_araddr_soft_o(w_port__Video_NPU_0__m_axi_araddr_soft_o)
                                                    , .m_axi_arlen_soft_o(w_port__Video_NPU_0__m_axi_arlen_soft_o)
                                                    , .m_axi_arsize_soft_o(w_port__Video_NPU_0__m_axi_arsize_soft_o)
                                                    , .m_axi_arburst_soft_o(w_port__Video_NPU_0__m_axi_arburst_soft_o)
                                                    , .m_axi_arlock_soft_o(w_port__Video_NPU_0__m_axi_arlock_soft_o)
                                                    , .m_axi_arcache_soft_o(w_port__Video_NPU_0__m_axi_arcache_soft_o)
                                                    , .m_axi_arprot_soft_o(w_port__Video_NPU_0__m_axi_arprot_soft_o)
                                                    , .m_axi_arvalid_soft_o(w_port__Video_NPU_0__m_axi_arvalid_soft_o)
                                                    , .m_axi_arready_soft_i(w_port__Video_NPU_0__m_axi_arready_soft_i)
                                                    , .m_axi_rid_soft_i(w_port__Video_NPU_0__m_axi_rid_soft_i)
                                                    , .m_axi_rdata_soft_i(w_port__Video_NPU_0__m_axi_rdata_soft_i)
                                                    , .m_axi_rresp_soft_i(w_port__Video_NPU_0__m_axi_rresp_soft_i)
                                                    , .m_axi_rlast_soft_i(w_port__Video_NPU_0__m_axi_rlast_soft_i)
                                                    , .m_axi_rvalid_soft_i(w_port__Video_NPU_0__m_axi_rvalid_soft_i)
                                                    , .m_axi_rready_soft_o(w_port__Video_NPU_0__m_axi_rready_soft_o)
                                                    , .npu_soft_intr(w_port__Video_NPU_0__npu_soft_intr) );

    design_0_fvdma_ctrl_0 design_0_fvdma_ctrl_0_Inst ( 
                                                        .s_axi_awaddr(w_port__fvdma_ctrl_0__s_axi_awaddr)
                                                      , .s_axi_awprot(w_port__fvdma_ctrl_0__s_axi_awprot)
                                                      , .s_axi_awvalid(w_port__fvdma_ctrl_0__s_axi_awvalid)
                                                      , .s_axi_awready(w_port__fvdma_ctrl_0__s_axi_awready)
                                                      , .s_axi_wdata(w_port__fvdma_ctrl_0__s_axi_wdata)
                                                      , .s_axi_wstrb(w_port__fvdma_ctrl_0__s_axi_wstrb)
                                                      , .s_axi_wvalid(w_port__fvdma_ctrl_0__s_axi_wvalid)
                                                      , .s_axi_wready(w_port__fvdma_ctrl_0__s_axi_wready)
                                                      , .s_axi_bresp(w_port__fvdma_ctrl_0__s_axi_bresp)
                                                      , .s_axi_bvalid(w_port__fvdma_ctrl_0__s_axi_bvalid)
                                                      , .s_axi_bready(w_port__fvdma_ctrl_0__s_axi_bready)
                                                      , .s_axi_araddr(w_port__fvdma_ctrl_0__s_axi_araddr)
                                                      , .s_axi_arprot(w_port__fvdma_ctrl_0__s_axi_arprot)
                                                      , .s_axi_arvalid(w_port__fvdma_ctrl_0__s_axi_arvalid)
                                                      , .s_axi_arready(w_port__fvdma_ctrl_0__s_axi_arready)
                                                      , .s_axi_rdata(w_port__fvdma_ctrl_0__s_axi_rdata)
                                                      , .s_axi_rresp(w_port__fvdma_ctrl_0__s_axi_rresp)
                                                      , .s_axi_rvalid(w_port__fvdma_ctrl_0__s_axi_rvalid)
                                                      , .s_axi_aclk(w_port__fvdma_ctrl_0__s_axi_aclk)
                                                      , .s_axi_aresetn(w_port__fvdma_ctrl_0__s_axi_aresetn)
                                                      , .s_axi_rready(w_port__fvdma_ctrl_0__s_axi_rready)
                                                      , .camera_base_addr(w_port__fvdma_ctrl_0__camera_base_addr)
                                                      , .camera_start(w_port__fvdma_ctrl_0__camera_start)
                                                      , .camera_clear(w_port__fvdma_ctrl_0__camera_clear) );

    design_0_VDMA_0 design_0_VDMA_0_Inst ( 
                                            .axi_lite_awvalid(w_port__VDMA_0__axi_lite_awvalid)
                                          , .axi_lite_awready(w_port__VDMA_0__axi_lite_awready)
                                          , .axi_lite_awaddr(w_port__VDMA_0__axi_lite_awaddr)
                                          , .axi_lite_wvalid(w_port__VDMA_0__axi_lite_wvalid)
                                          , .axi_lite_wready(w_port__VDMA_0__axi_lite_wready)
                                          , .axi_lite_wdata(w_port__VDMA_0__axi_lite_wdata)
                                          , .axi_lite_bresp(w_port__VDMA_0__axi_lite_bresp)
                                          , .axi_lite_bvalid(w_port__VDMA_0__axi_lite_bvalid)
                                          , .axi_lite_bready(w_port__VDMA_0__axi_lite_bready)
                                          , .axi_lite_arvalid(w_port__VDMA_0__axi_lite_arvalid)
                                          , .axi_lite_arready(w_port__VDMA_0__axi_lite_arready)
                                          , .axi_lite_araddr(w_port__VDMA_0__axi_lite_araddr)
                                          , .axi_lite_rvalid(w_port__VDMA_0__axi_lite_rvalid)
                                          , .axi_lite_rready(w_port__VDMA_0__axi_lite_rready)
                                          , .axi_lite_rdata(w_port__VDMA_0__axi_lite_rdata)
                                          , .axi_lite_rresp(w_port__VDMA_0__axi_lite_rresp)
                                          , .s_axis_s2mm_tdata(32'b0)
                                          , .s_axis_s2mm_tkeep(4'b1111)
                                          , .s_axis_s2mm_tuser(1'b0)
                                          , .s_axis_s2mm_tvalid(1'b0)
                                          , .s_axis_s2mm_tready()
                                          , .s_axis_s2mm_tlast(1'b0)
                                          , .s_axi_lite_aclk(w_port__VDMA_0__s_axi_lite_aclk)
                                          , .m_axi_mm2s_aclk(w_port__VDMA_0__m_axi_mm2s_aclk)
                                          , .m_axis_mm2s_aclk(w_port__VDMA_0__m_axis_mm2s_aclk)
                                          , .m_axi_s2mm_aclk(1'b0)
                                          , .s_axis_s2mm_aclk(1'b0)
                                          , .resetn(w_port__VDMA_0__resetn)
                                          , .mm2s_fsync(1'b0)
                                          , .s2mm_fsync(1'b0)
                                          , .m_axi_mm2s_araddr(w_port__VDMA_0__m_axi_mm2s_araddr)
                                          , .m_axi_mm2s_arlen(w_port__VDMA_0__m_axi_mm2s_arlen)
                                          , .m_axi_mm2s_arsize(w_port__VDMA_0__m_axi_mm2s_arsize)
                                          , .m_axi_mm2s_arburst(w_port__VDMA_0__m_axi_mm2s_arburst)
                                          , .m_axi_mm2s_arprot(w_port__VDMA_0__m_axi_mm2s_arprot)
                                          , .m_axi_mm2s_arcache(w_port__VDMA_0__m_axi_mm2s_arcache)
                                          , .m_axi_mm2s_arvalid(w_port__VDMA_0__m_axi_mm2s_arvalid)
                                          , .m_axi_mm2s_arready(w_port__VDMA_0__m_axi_mm2s_arready)
                                          , .m_axi_mm2s_rdata(w_port__VDMA_0__m_axi_mm2s_rdata)
                                          , .m_axi_mm2s_rresp(w_port__VDMA_0__m_axi_mm2s_rresp)
                                          , .m_axi_mm2s_rlast(w_port__VDMA_0__m_axi_mm2s_rlast)
                                          , .m_axi_mm2s_rvalid(w_port__VDMA_0__m_axi_mm2s_rvalid)
                                          , .m_axi_mm2s_rready(w_port__VDMA_0__m_axi_mm2s_rready)
                                          , .m_axi_s2mm_awaddr()
                                          , .m_axi_s2mm_awlen()
                                          , .m_axi_s2mm_awsize()
                                          , .m_axi_s2mm_awburst()
                                          , .m_axi_s2mm_awprot()
                                          , .m_axi_s2mm_awcache()
                                          , .m_axi_s2mm_awvalid()
                                          , .m_axi_s2mm_awready(1'b0)
                                          , .m_axi_s2mm_wdata()
                                          , .m_axi_s2mm_wstrb()
                                          , .m_axi_s2mm_wlast()
                                          , .m_axi_s2mm_wvalid()
                                          , .m_axi_s2mm_wready(1'b0)
                                          , .m_axi_s2mm_bresp(2'b0)
                                          , .m_axi_s2mm_bvalid(1'b0)
                                          , .m_axi_s2mm_bready()
                                          , .m_axis_mm2s_tdata(w_port__VDMA_0__m_axis_mm2s_tdata)
                                          , .m_axis_mm2s_tkeep()
                                          , .m_axis_mm2s_tuser(w_port__VDMA_0__m_axis_mm2s_tuser)
                                          , .m_axis_mm2s_tvalid(w_port__VDMA_0__m_axis_mm2s_tvalid)
                                          , .m_axis_mm2s_tready(w_port__VDMA_0__m_axis_mm2s_tready)
                                          , .m_axis_mm2s_tlast(w_port__VDMA_0__m_axis_mm2s_tlast)
                                          , .mm2s_frame_ptr_out()
                                          , .s2mm_frame_ptr_out()
                                          , .mm2s_introut(w_port__VDMA_0__mm2s_introut)
                                          , .s2mm_introut() );

    design_0_video_timing_generator_v01_0 design_0_video_timing_generator_v01_0_Inst ( 
                                                                                        .s_axi_awaddr(w_port__video_timing_generator_v01_0__s_axi_awaddr)
                                                                                      , .s_axi_awvalid(w_port__video_timing_generator_v01_0__s_axi_awvalid)
                                                                                      , .s_axi_awready(w_port__video_timing_generator_v01_0__s_axi_awready)
                                                                                      , .s_axi_wdata(w_port__video_timing_generator_v01_0__s_axi_wdata)
                                                                                      , .s_axi_wstrb(w_port__video_timing_generator_v01_0__s_axi_wstrb)
                                                                                      , .s_axi_wvalid(w_port__video_timing_generator_v01_0__s_axi_wvalid)
                                                                                      , .s_axi_wready(w_port__video_timing_generator_v01_0__s_axi_wready)
                                                                                      , .s_axi_bresp(w_port__video_timing_generator_v01_0__s_axi_bresp)
                                                                                      , .s_axi_bvalid(w_port__video_timing_generator_v01_0__s_axi_bvalid)
                                                                                      , .s_axi_bready(w_port__video_timing_generator_v01_0__s_axi_bready)
                                                                                      , .s_axi_araddr(w_port__video_timing_generator_v01_0__s_axi_araddr)
                                                                                      , .s_axi_arvalid(w_port__video_timing_generator_v01_0__s_axi_arvalid)
                                                                                      , .s_axi_arready(w_port__video_timing_generator_v01_0__s_axi_arready)
                                                                                      , .s_axi_rdata(w_port__video_timing_generator_v01_0__s_axi_rdata)
                                                                                      , .s_axi_rresp(w_port__video_timing_generator_v01_0__s_axi_rresp)
                                                                                      , .s_axi_rvalid(w_port__video_timing_generator_v01_0__s_axi_rvalid)
                                                                                      , .s_axi_rready(w_port__video_timing_generator_v01_0__s_axi_rready)
                                                                                      , .aclk(w_port__video_timing_generator_v01_0__aclk)
                                                                                      , .arst_n(w_port__video_timing_generator_v01_0__arst_n)
                                                                                      , .ref_clk(w_port__video_timing_generator_v01_0__ref_clk)
                                                                                      , .vtg_ce(w_port__video_timing_generator_v01_0__vtg_ce)
                                                                                      , .vtg_pclk_locked(w_port__video_timing_generator_v01_0__vtg_pclk_locked)
                                                                                      , .vtg_pclk(w_port__video_timing_generator_v01_0__vtg_pclk)
                                                                                      , .vtg_hsync(w_port__video_timing_generator_v01_0__vtg_hsync)
                                                                                      , .vtg_vsync(w_port__video_timing_generator_v01_0__vtg_vsync)
                                                                                      , .vtg_hblank(w_port__video_timing_generator_v01_0__vtg_hblank)
                                                                                      , .vtg_vblank(w_port__video_timing_generator_v01_0__vtg_vblank)
                                                                                      , .vtg_active_video(w_port__video_timing_generator_v01_0__vtg_active_video) );

    design_0_AXI4_Stream_to_Video_Out_0 design_0_AXI4_Stream_to_Video_Out_0_Inst ( 
                                                                                    .s_axis_video_tdata(w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tdata)
                                                                                  , .s_axis_video_tvalid(w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tvalid)
                                                                                  , .s_axis_video_tready(w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tready)
                                                                                  , .s_axis_video_tuser(w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tuser)
                                                                                  , .s_axis_video_tlast(w_port__AXI4_Stream_to_Video_Out_0__s_axis_video_tlast)
                                                                                  , .aclk(w_port__AXI4_Stream_to_Video_Out_0__aclk)
                                                                                  , .aclken(w_port__AXI4_Stream_to_Video_Out_0__aclken)
                                                                                  , .aresetn(w_port__AXI4_Stream_to_Video_Out_0__aresetn)
                                                                                  , .fid(1'b0)
                                                                                  , .vid_io_out_clk(w_port__AXI4_Stream_to_Video_Out_0__vid_io_out_clk)
                                                                                  , .vid_io_out_reset(1'b0)
                                                                                  , .vid_io_out_ce(w_port__AXI4_Stream_to_Video_Out_0__vid_io_out_ce)
                                                                                  , .vtg_vsync(w_port__AXI4_Stream_to_Video_Out_0__vtg_vsync)
                                                                                  , .vtg_hsync(w_port__AXI4_Stream_to_Video_Out_0__vtg_hsync)
                                                                                  , .vtg_vblank(w_port__AXI4_Stream_to_Video_Out_0__vtg_vblank)
                                                                                  , .vtg_hblank(w_port__AXI4_Stream_to_Video_Out_0__vtg_hblank)
                                                                                  , .vtg_active_video(w_port__AXI4_Stream_to_Video_Out_0__vtg_active_video)
                                                                                  , .vtg_field_id(1'b0)
                                                                                  , .vid_active_video(w_port__AXI4_Stream_to_Video_Out_0__vid_active_video)
                                                                                  , .vid_vsync(w_port__AXI4_Stream_to_Video_Out_0__vid_vsync)
                                                                                  , .vid_hsync(w_port__AXI4_Stream_to_Video_Out_0__vid_hsync)
                                                                                  , .vid_vblank()
                                                                                  , .vid_hblank()
                                                                                  , .vid_field_id()
                                                                                  , .vid_data(w_port__AXI4_Stream_to_Video_Out_0__vid_data)
                                                                                  , .vtg_ce(w_port__AXI4_Stream_to_Video_Out_0__vtg_ce)
                                                                                  , .locked(w_port__AXI4_Stream_to_Video_Out_0__locked)
                                                                                  , .overflow()
                                                                                  , .underflow()
                                                                                  , .fifo_read_level()
                                                                                  , .status()
                                                                                  , .sof_state_out() );

    design_0_AXI_Matrix_2 design_0_AXI_Matrix_2_Inst ( 
                                                        .us0_araddr(w_port__AXI_Matrix_2__us0_araddr)
                                                      , .us0_arburst(w_port__AXI_Matrix_2__us0_arburst)
                                                      , .us0_arcache(w_port__AXI_Matrix_2__us0_arcache)
                                                      , .us0_arid(5'b0)
                                                      , .us0_arlen(w_port__AXI_Matrix_2__us0_arlen)
                                                      , .us0_arlock(1'b0)
                                                      , .us0_arprot(w_port__AXI_Matrix_2__us0_arprot)
                                                      , .us0_arqos(4'b0)
                                                      , .us0_arready(w_port__AXI_Matrix_2__us0_arready)
                                                      , .us0_arsize(w_port__AXI_Matrix_2__us0_arsize)
                                                      , .us0_arvalid(w_port__AXI_Matrix_2__us0_arvalid)
                                                      , .us0_awaddr(32'b0)
                                                      , .us0_awburst(2'b0)
                                                      , .us0_awcache(4'b0)
                                                      , .us0_awid(5'b0)
                                                      , .us0_awlen(8'b0)
                                                      , .us0_awlock(1'b0)
                                                      , .us0_awprot(3'b0)
                                                      , .us0_awqos(4'b0)
                                                      , .us0_awready()
                                                      , .us0_awsize(3'b0)
                                                      , .us0_awvalid(1'b0)
                                                      , .us0_bid()
                                                      , .us0_bready(1'b0)
                                                      , .us0_bresp()
                                                      , .us0_bvalid()
                                                      , .us0_rdata(w_port__AXI_Matrix_2__us0_rdata)
                                                      , .us0_rid()
                                                      , .us0_rlast(w_port__AXI_Matrix_2__us0_rlast)
                                                      , .us0_rready(w_port__AXI_Matrix_2__us0_rready)
                                                      , .us0_rresp(w_port__AXI_Matrix_2__us0_rresp)
                                                      , .us0_rvalid(w_port__AXI_Matrix_2__us0_rvalid)
                                                      , .us0_wdata(64'b0)
                                                      , .us0_wlast(1'b0)
                                                      , .us0_wready()
                                                      , .us0_wstrb(8'b0)
                                                      , .us0_wvalid(1'b0)
                                                      , .us1_araddr(w_port__AXI_Matrix_2__us1_araddr)
                                                      , .us1_arburst(w_port__AXI_Matrix_2__us1_arburst)
                                                      , .us1_arcache(w_port__AXI_Matrix_2__us1_arcache)
                                                      , .us1_arid(w_port__AXI_Matrix_2__us1_arid)
                                                      , .us1_arlen(w_port__AXI_Matrix_2__us1_arlen)
                                                      , .us1_arlock(w_port__AXI_Matrix_2__us1_arlock)
                                                      , .us1_arprot(w_port__AXI_Matrix_2__us1_arprot)
                                                      , .us1_arqos(w_port__AXI_Matrix_2__us1_arqos)
                                                      , .us1_arready(w_port__AXI_Matrix_2__us1_arready)
                                                      , .us1_arsize(w_port__AXI_Matrix_2__us1_arsize)
                                                      , .us1_arvalid(w_port__AXI_Matrix_2__us1_arvalid)
                                                      , .us1_awaddr(w_port__AXI_Matrix_2__us1_awaddr)
                                                      , .us1_awburst(w_port__AXI_Matrix_2__us1_awburst)
                                                      , .us1_awcache(w_port__AXI_Matrix_2__us1_awcache)
                                                      , .us1_awid(w_port__AXI_Matrix_2__us1_awid)
                                                      , .us1_awlen(w_port__AXI_Matrix_2__us1_awlen)
                                                      , .us1_awlock(w_port__AXI_Matrix_2__us1_awlock)
                                                      , .us1_awprot(w_port__AXI_Matrix_2__us1_awprot)
                                                      , .us1_awqos(w_port__AXI_Matrix_2__us1_awqos)
                                                      , .us1_awready(w_port__AXI_Matrix_2__us1_awready)
                                                      , .us1_awsize(w_port__AXI_Matrix_2__us1_awsize)
                                                      , .us1_awvalid(w_port__AXI_Matrix_2__us1_awvalid)
                                                      , .us1_bid(w_port__AXI_Matrix_2__us1_bid)
                                                      , .us1_bready(w_port__AXI_Matrix_2__us1_bready)
                                                      , .us1_bresp(w_port__AXI_Matrix_2__us1_bresp)
                                                      , .us1_bvalid(w_port__AXI_Matrix_2__us1_bvalid)
                                                      , .us1_rdata(w_port__AXI_Matrix_2__us1_rdata)
                                                      , .us1_rid(w_port__AXI_Matrix_2__us1_rid)
                                                      , .us1_rlast(w_port__AXI_Matrix_2__us1_rlast)
                                                      , .us1_rready(w_port__AXI_Matrix_2__us1_rready)
                                                      , .us1_rresp(w_port__AXI_Matrix_2__us1_rresp)
                                                      , .us1_rvalid(w_port__AXI_Matrix_2__us1_rvalid)
                                                      , .us1_wdata(w_port__AXI_Matrix_2__us1_wdata)
                                                      , .us1_wlast(w_port__AXI_Matrix_2__us1_wlast)
                                                      , .us1_wready(w_port__AXI_Matrix_2__us1_wready)
                                                      , .us1_wstrb(w_port__AXI_Matrix_2__us1_wstrb)
                                                      , .us1_wvalid(w_port__AXI_Matrix_2__us1_wvalid)
                                                      , .aclk(w_port__AXI_Matrix_2__aclk)
                                                      , .aresetn(w_port__AXI_Matrix_2__aresetn)
                                                      , .ds0_araddr(w_port__AXI_Matrix_2__ds0_araddr)
                                                      , .ds0_arburst(w_port__AXI_Matrix_2__ds0_arburst)
                                                      , .ds0_arcache(w_port__AXI_Matrix_2__ds0_arcache)
                                                      , .ds0_arid(w_port__AXI_Matrix_2__ds0_arid)
                                                      , .ds0_arlen(w_port__AXI_Matrix_2__ds0_arlen)
                                                      , .ds0_arlock(w_port__AXI_Matrix_2__ds0_arlock)
                                                      , .ds0_arprot(w_port__AXI_Matrix_2__ds0_arprot)
                                                      , .ds0_arqos(w_port__AXI_Matrix_2__ds0_arqos)
                                                      , .ds0_arregion()
                                                      , .ds0_arready(w_port__AXI_Matrix_2__ds0_arready)
                                                      , .ds0_arsize(w_port__AXI_Matrix_2__ds0_arsize)
                                                      , .ds0_arvalid(w_port__AXI_Matrix_2__ds0_arvalid)
                                                      , .ds0_awaddr(w_port__AXI_Matrix_2__ds0_awaddr)
                                                      , .ds0_awburst(w_port__AXI_Matrix_2__ds0_awburst)
                                                      , .ds0_awcache(w_port__AXI_Matrix_2__ds0_awcache)
                                                      , .ds0_awid(w_port__AXI_Matrix_2__ds0_awid)
                                                      , .ds0_awlen(w_port__AXI_Matrix_2__ds0_awlen)
                                                      , .ds0_awlock(w_port__AXI_Matrix_2__ds0_awlock)
                                                      , .ds0_awprot(w_port__AXI_Matrix_2__ds0_awprot)
                                                      , .ds0_awqos(w_port__AXI_Matrix_2__ds0_awqos)
                                                      , .ds0_awregion()
                                                      , .ds0_awready(w_port__AXI_Matrix_2__ds0_awready)
                                                      , .ds0_awsize(w_port__AXI_Matrix_2__ds0_awsize)
                                                      , .ds0_awvalid(w_port__AXI_Matrix_2__ds0_awvalid)
                                                      , .ds0_bid(w_port__AXI_Matrix_2__ds0_bid)
                                                      , .ds0_bready(w_port__AXI_Matrix_2__ds0_bready)
                                                      , .ds0_bresp(w_port__AXI_Matrix_2__ds0_bresp)
                                                      , .ds0_bvalid(w_port__AXI_Matrix_2__ds0_bvalid)
                                                      , .ds0_rdata(w_port__AXI_Matrix_2__ds0_rdata)
                                                      , .ds0_rid(w_port__AXI_Matrix_2__ds0_rid)
                                                      , .ds0_rlast(w_port__AXI_Matrix_2__ds0_rlast)
                                                      , .ds0_rready(w_port__AXI_Matrix_2__ds0_rready)
                                                      , .ds0_rresp(w_port__AXI_Matrix_2__ds0_rresp)
                                                      , .ds0_rvalid(w_port__AXI_Matrix_2__ds0_rvalid)
                                                      , .ds0_wdata(w_port__AXI_Matrix_2__ds0_wdata)
                                                      , .ds0_wlast(w_port__AXI_Matrix_2__ds0_wlast)
                                                      , .ds0_wready(w_port__AXI_Matrix_2__ds0_wready)
                                                      , .ds0_wstrb(w_port__AXI_Matrix_2__ds0_wstrb)
                                                      , .ds0_wvalid(w_port__AXI_Matrix_2__ds0_wvalid) );

    design_0_PLL_3 design_0_PLL_3_Inst ( 
                                          .refclk(w_port__PLL_3__refclk)
                                        , .reset(w_port__PLL_3__reset)
                                        , .clk0_out(w_port__PLL_3__clk0_out)
                                        , .lock(w_port__PLL_3__lock) );

    design_0_Utility_Vector_Logic_0 design_0_Utility_Vector_Logic_0_Inst ( 
                                                                            .vector_a(w_port__Utility_Vector_Logic_0__vector_a)
                                                                          , .result_vector(w_port__Utility_Vector_Logic_0__result_vector) );

    design_0_Utility_Vector_Logic_1 design_0_Utility_Vector_Logic_1_Inst ( 
                                                                            .vector_a(w_port__Utility_Vector_Logic_1__vector_a)
                                                                          , .result_vector(w_port__Utility_Vector_Logic_1__result_vector) );

    design_0_uihdmi_tx_0 design_0_uihdmi_tx_0_Inst ( 
                                                      .I_pixel_clk(w_port__uihdmi_tx_0__I_pixel_clk)
                                                    , .I_serial_clk(w_port__uihdmi_tx_0__I_serial_clk)
                                                    , .I_rst(w_port__uihdmi_tx_0__I_rst)
                                                    , .I_video_in_data(w_port__uihdmi_tx_0__I_video_in_data)
                                                    , .I_video_in_de(w_port__uihdmi_tx_0__I_video_in_de)
                                                    , .I_video_in_vs(w_port__uihdmi_tx_0__I_video_in_vs)
                                                    , .I_video_in_hs(w_port__uihdmi_tx_0__I_video_in_hs)
                                                    , .O_hdmi_clk_p(w_port__uihdmi_tx_0__O_hdmi_clk_p)
                                                    , .O_hdmi_tx_p(w_port__uihdmi_tx_0__O_hdmi_tx_p) );

    design_0_pwm_0_0 design_0_pwm_0_0_Inst ( 
                                              .clk(w_port__pwm_0_0__clk)
                                            , .rst_n(w_port__pwm_0_0__rst_n)
                                            , .pwm_out(w_port__pwm_0_0__pwm_out) );

    design_0_pwm_0_1 design_0_pwm_0_1_Inst ( 
                                              .clk(w_port__pwm_0_1__clk)
                                            , .rst_n(w_port__pwm_0_1__rst_n)
                                            , .pwm_out(w_port__pwm_0_1__pwm_out) );

// Clock aliases follow all explicit net declarations.
    assign w_port__PLL_npu__clk0_out = w_shared_fabric_clk150;
    assign w_port__pll_150m__clk0_out = w_shared_fabric_clk150;
    assign w_port__PLL_npu__lock = w_port__pll_75m__lock;
    assign w_port__pll_150m__lock = w_port__pll_75m__lock;
endmodule
