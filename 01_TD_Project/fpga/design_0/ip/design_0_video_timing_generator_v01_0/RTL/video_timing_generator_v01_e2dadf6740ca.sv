
// 使用axi lite接口配置显示时序参数，生成hs、vs等信号，一般用于对接vdma和axi stream to video out实现显示器显示
// 20250810 初始版本
// 20250910 增加axi lite接口，实现动态配置视频时序参数和像素时钟
// 20250912 修改pll 配置时的地址和数据，低八位为数据，高八位为地址，为了保证与apug1216兼容
// 20250919 支持通过参数设置视频时序、帧率，以支持非动态调整的模式
// 20250919 新增vtg_ce信号，以和axis to video out ip 配合使用
// 20250919 更改ip名称为video timing generator，暂不支持vtc的视频时序检测功能
// 20251010 增加pll reset和clk out控制寄存器, 已确保lock信号有足够的时间为外部提供复位
// 20251022 消除vtg内部的时序违例，并去掉加密部分

/* 寄存器分布
index addr    purpose
0     0x00    h_front      (reg0[15:0])
1     0x04    h_action     (reg1[15:0])
2     0x08    h_sync       (reg2[15:0])
3     0x0c    h_back       (reg3[15:0])
4     0x10    v_front      (reg4[15:0])
5     0x14    v_action     (reg5[15:0])
6     0x18    v_sync       (reg6[15:0])
7     0x1c    v_back       (reg7[15:0])
8     0x20    [0] : rstn   (reg8[15:0])

...

16    0x1000  pll drp [7:0] write data, [15:8] write addr
17    0x1004  pll drp [7:0] read  data, [15:8] read addr
18    0x1008  pll lock  [0] pll lock status
19    0x100c  pll reset and clk out control:
                        [0] clk out 0 enable
                        [8] pll reset
*/

`timescale 1 ns / 1 ps
module video_timing_generator_v01_e2dadf6740ca #(
    // 时钟参数
    parameter REF_CLK_FREQ = 50,      // ref clock时钟频率,用于计算pll的分频系数, 仅支持50和100两个频率，且输入必须为整数
    parameter integer FPS  = 60,      // 帧率(Frames Per Second)
    // 默认时序参数 - 1920x1080@60Hz
    parameter H_FRONT  = 16'd88,     // 水平前肩
    parameter H_ACTIVE = 16'd1920,   // 水平有效区
    parameter H_SYNC   = 16'd44,     // 水平同步
    parameter H_BACK   = 16'd148,    // 水平后肩
    parameter V_FRONT  = 16'd4,      // 垂直前肩
    parameter V_ACTIVE = 16'd1080,   // 垂直有效区
    parameter V_SYNC   = 16'd5,      // 垂直同步
    parameter V_BACK   = 16'd36      // 垂直后肩
   
)(
    input  wire                 aclk,            // 时钟信号
    input  wire                 arst_n,          // 异步复位，低有效

    // AXI Lite 接口信号
    input  wire [12:0]           s_axi_awaddr  ,  // 写地址
    input  wire                  s_axi_awvalid ,  // 写地址有效
    output wire                  s_axi_awready ,  // 写地址准备好  
    input  wire [31:0]           s_axi_wdata   ,  // 写数据
    input  wire [3:0]            s_axi_wstrb   ,  // 写字节使能
    input  wire                  s_axi_wvalid  ,  // 写数据有效
    output wire                  s_axi_wready  ,  // 写数据准备好 
    output wire [1:0]            s_axi_bresp   ,  // 写响应
    output wire                  s_axi_bvalid  ,  // 写响应有效
    input  wire                  s_axi_bready  ,  // 写响应准备好 
    input  wire [12:0]           s_axi_araddr  ,  // 读地址
    input  wire                  s_axi_arvalid ,  // 读地址有效
    output wire                  s_axi_arready ,  // 读地址准备好 
    output wire [31:0]           s_axi_rdata   ,  // 读数据
    output wire [1:0]            s_axi_rresp   ,  // 读响应
    output wire                  s_axi_rvalid  ,  // 读数据有效
    input  wire                  s_axi_rready  ,  // 读数据准备好 
    // 这里添加用户端口
    // ....
    input  wire                  ref_clk       ,  // 输入到PLL的参考时钟，需要与驱动中保持一致 
    input  wire                  vtg_ce        ,
     // 时序信号输出接口
    output wire                      vtg_pclk_locked,      // 像素时钟锁定状态
    output wire                      vtg_pclk,
    output wire                      vtg_hsync,            // 水平同步信号
    output wire                      vtg_vsync,            // 垂直同步信号
    output wire                      vtg_hblank,           // 水平消隐信号
    output wire                      vtg_vblank,           // 垂直消隐信号
    output wire                      vtg_active_video      // 数据使能信号
    
    // 用户端口添加结束
);
 
localparam REG_NUM    = 32;                   // 寄存器数量
localparam DATA_WIDTH = 32;                   // 数据宽度
localparam ADDR_WIDTH = 13;                   // 地址宽度

//==============================================================================
// PLL配置参数自动计算
//==============================================================================

localparam real REF_CLK_REAL = REF_CLK_FREQ;
localparam FIN = (REF_CLK_FREQ == 50)? "50":(REF_CLK_FREQ == 75)? "75":(REF_CLK_FREQ == 100)? "100":"50" ;

// 根据时序参数和FPS计算像素时钟 (MHz)
// Pixel Clock = (H_TOTAL * V_TOTAL * FPS) / 1_000_000
localparam integer H_TOTAL = H_FRONT + H_ACTIVE + H_SYNC + H_BACK;
localparam integer V_TOTAL = V_FRONT + V_ACTIVE + V_SYNC + V_BACK;
localparam integer TOTAL_PIXELS_PER_FRAME = H_TOTAL * V_TOTAL; // 可能较大, 对1080p约 2200*1125=2,475,000
localparam real PIXEL_CLK_REAL = (TOTAL_PIXELS_PER_FRAME * 1.0 * FPS) / 1_000_000.0; // MHz

// PLL VCO频率范围约束 (MHz)
localparam real VCO_MIN = 800.0;
localparam real VCO_MAX = 2000.0;

// 计算最优PLL参数的函数
`pragma protect begin
function automatic [20:0] calculate_pll_params;
    input real ref_freq;
    input real target_freq;
    
    real vco_freq;
    real error, min_error;
    integer best_m, best_n, best_c;
    integer m, n, c;
    real calc_freq;
    
    begin
        min_error = 1000.0;
        best_m = 78; best_n = 2; best_c = 13; // 默认值
        
        // 搜索最优参数组合
        for (n = 1; n <= 127; n = n + 1) begin
            for (c = 1; c <= 127; c = c + 1) begin
                // 计算所需的VCO频率
                vco_freq = target_freq * c;
                
                // 检查VCO频率是否在有效范围内
                if (vco_freq >= VCO_MIN && vco_freq <= VCO_MAX) begin
                    // 计算对应的m值
                    m = $rtoi((vco_freq * n / ref_freq) + 0.5);
                    
                    // 限制m值范围：3~126
                    if (m >= 3 && m <= 126) begin
                        // 计算实际输出频率
                        calc_freq = ref_freq * m / n / c;
                        
                        // 计算误差
                        error = (calc_freq > target_freq) ? 
                               (calc_freq - target_freq) : (target_freq - calc_freq);
                        
                        // 更新最优参数
                        if (error < min_error) begin
                            min_error = error;
                            best_m = m;
                            best_n = n;
                            best_c = c;
                        end
                    end
                end
            end
        end
        
        // 返回打包的参数 [31:20]=m, [19:10]=n, [9:0]=c
        calculate_pll_params = {best_m[6:0], best_n[6:0], best_c[6:0]};
    end
endfunction

`pragma protect end

// 计算PLL参数
localparam [20:0] PLL_PARAMS = calculate_pll_params(REF_CLK_REAL, PIXEL_CLK_REAL);
localparam  FBCLK_DIV  = int'(PLL_PARAMS[20:14]);    // m值 (3~126)
localparam  REFCLK_DIV = int'(PLL_PARAMS[13:7]);     // n值 (1~127)
localparam  CLKC0_DIV  = int'(PLL_PARAMS[6:0]);      // c值 (1~127)
localparam  CLKC0_DUTY_INT = (CLKC0_DIV > 1) ? ((CLKC0_DIV+1)/2) : 1; // 简单偶数/奇数占空比近似

// axi lite bus  start 
// 时钟和复位信号
wire clk   = aclk;
wire rst_n = arst_n;
// 写通道状态机
localparam [1:0] WRITE_IDLE = 2'b00,
                 WRITE_ADDR = 2'b01,
                 WRITE_DATA = 2'b10,
                 WRITE_RESP = 2'b11;

reg [1:0] write_state;

// 参数化的寄存器数组
reg [15:0] reg0;
reg [15:0] reg1;
reg [15:0] reg2;
reg [15:0] reg3;
reg [15:0] reg4;
reg [15:0] reg5;
reg [15:0] reg6;
reg [15:0] reg7;
reg [0:0] reg8;

reg [15:0] reg400;
reg [15:0] reg401;
reg [DATA_WIDTH-1:0] reg402;
reg [8:0] reg403;

// 写通道寄存器 , 确保数据缓存
reg [ADDR_WIDTH-1:0] write_addr;
reg [15:0] write_data;
reg [3:0]            write_strb;     // 缓存写字节使能
reg                  bvalid;

// 读通道状态寄存器
reg [DATA_WIDTH-1:0] rdata;
reg rvalid;

// 声明变量
integer j;

// 输出信号连接
assign s_axi_awready = (write_state == WRITE_IDLE) || (write_state == WRITE_ADDR);
assign s_axi_wready  = (write_state == WRITE_IDLE) || (write_state == WRITE_DATA);

assign s_axi_bvalid  = bvalid;
assign s_axi_bresp   = 2'b00;

// 优化的读通道信号连接 
assign s_axi_arready = (!rvalid || s_axi_rready);
assign s_axi_rdata   = rdata;
assign s_axi_rvalid  = rvalid;
assign s_axi_rresp   = 2'b00;

`pragma protect begin
// 执行写操作的函数 - 提取公共逻辑
task execute_write_operation;
    input [ADDR_WIDTH-1:0] addr;
    input [DATA_WIDTH-1:0] data;
    input [3:0] strb;
    begin
    case (addr[ADDR_WIDTH-1:2]) 
        11'h0  : reg0    <= data[15:0];
        11'h1  : reg1    <= data[15:0];
        11'h2  : reg2    <= data[15:0];
        11'h3  : reg3    <= data[15:0];
        11'h4  : reg4    <= data[15:0];
        11'h5  : reg5    <= data[15:0];
        11'h6  : reg6    <= data[15:0];
        11'h7  : reg7    <= data[15:0];
        11'h8  : reg8    <= data[0];
        
        11'h400: reg400  <= data[15:0];
        11'h401: reg401  <= data[15:0];
        11'h402: reg402  <= data;
        11'h403: reg403  <= data[8:0] & 9'h101;
    endcase
    end
endtask

`pragma protect end

// 写通道状态机
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        write_state <= WRITE_IDLE;
        write_addr  <= {ADDR_WIDTH{1'b0}};
        write_data  <= 16'd0;
        write_strb  <= 4'b0000;
        bvalid      <= 1'b0;
        // 初始化寄存器数组 - 使用默认时序参数
        reg0  <= H_FRONT;
        reg1  <= H_ACTIVE;
        reg2  <= H_SYNC;
        reg3  <= H_BACK;
        reg4  <= V_FRONT;
        reg5  <= V_ACTIVE;
        reg6  <= V_SYNC;
        reg7  <= V_BACK;
        reg8  <= 1'b1;
        
        reg400  <= 16'd0;
        reg401  <= 16'd0;
        reg402  <= {DATA_WIDTH{1'b0}};
        reg403  <= 9'd0;

    end else begin
        case (write_state)
            WRITE_IDLE: begin
                if (s_axi_awvalid && s_axi_wvalid) begin
                    // 地址和数据同时到达，直接执行写操作
                    execute_write_operation(s_axi_awaddr, s_axi_wdata, s_axi_wstrb);
                    write_state <= WRITE_RESP;
                    bvalid <= 1'b1;
                end else if (s_axi_awvalid) begin
                    // 只有地址到达，缓存地址
                    write_addr <= s_axi_awaddr;
                    write_state <= WRITE_DATA;
                end else if (s_axi_wvalid) begin
                    // 只有数据到达，缓存数据
                    write_data <= s_axi_wdata[15:0];
                    write_strb <= s_axi_wstrb;
                    write_state <= WRITE_ADDR;
                end
            end
            
            WRITE_ADDR: begin
                // 等待地址，数据已缓存
                if (s_axi_awvalid) begin
                    // 使用缓存的数据和当前地址执行写操作
                    execute_write_operation(s_axi_awaddr, write_data, write_strb);
                    write_state <= WRITE_RESP;
                    bvalid <= 1'b1;
                end
            end
            
            WRITE_DATA: begin
                // 等待数据，地址已缓存
                if (s_axi_wvalid) begin
                    // 使用缓存的地址和当前数据执行写操作
                    execute_write_operation(write_addr, s_axi_wdata, s_axi_wstrb);
                    write_state <= WRITE_RESP;
                    bvalid <= 1'b1;
                end
            end
            
            WRITE_RESP: begin
                // 等待响应被接收
                if (s_axi_bready) begin
                    bvalid <= 1'b0;
                    write_state <= WRITE_IDLE;
                end
                // 关键：在RESP状态下，bvalid必须保持为1直到被接收
            end
            
            default: begin
                write_state <= WRITE_IDLE;
                bvalid <= 1'b0;
            end
        endcase
    end
end

// 优化的读操作处理
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        rvalid <= 1'b0;
        rdata  <= {DATA_WIDTH{1'b0}};
    end else begin
        if (s_axi_arvalid && (!rvalid || s_axi_rready)) begin
            // 可以在以下情况接收新的读地址：
            // 1. rvalid为0（没有待处理的读数据）
            // 2. rvalid为1但master准备好接收数据
    
            case (s_axi_araddr[ADDR_WIDTH-1:2]) 
                11'h0  : rdata    <= reg0;
                11'h1  : rdata    <= reg1;
                11'h2  : rdata    <= reg2;
                11'h3  : rdata    <= reg3;
                11'h4  : rdata    <= reg4;
                11'h5  : rdata    <= reg5;
                11'h6  : rdata    <= reg6;
                11'h7  : rdata    <= reg7;
                11'h8  : rdata    <= reg8;
                
                11'h400: rdata    <= reg400;
                11'h401: rdata    <= {24'd0,drp_rdata};
                11'h402: rdata    <= {30'd0,drp_status[1], vtg_pclk_locked }; 
                11'h403: rdata    <= reg403;
                default: rdata    <= {DATA_WIDTH{1'b0}};      
            endcase
        
            rvalid <= 1'b1;                   // 标记读数据有效
        end else if (rvalid && s_axi_rready) begin
            // 当前读数据被接收，但没有新的读请求
            rvalid <= 1'b0;
        end
    end
end

// axi lite bus end 

// 添加用户逻辑
// ...
// axi pll 数据处理,实现通过总线动态配置axi pll
wire    [7:0]     drp_addr;
wire    [7:0]     drp_wdata;
wire    [7:0]     drp_rdata;
wire              drp_w_enable;

// drp_rst_n must be 1
wire              drp_rst_n = 1'b1;
assign drp_w_enable = drp_w_t;
wire   [31:0]     drp_status;  

reg [15:0] drp_w_temp1;
reg [15:0] drp_w_temp2;
reg  drp_w_t;
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        drp_w_t <= 1'b0;
        drp_w_temp1  <= {16{1'b0}};
    
    end else begin
        drp_w_temp1 <= reg400[15:0];
        drp_w_temp2 <= drp_w_temp1;
        if ( reg400[15:0] != drp_w_temp2)
           drp_w_t <= 1;
         else 
           drp_w_t <= 0;  
    end
end

assign drp_addr     = drp_w_enable ? reg400[15:8]:reg401[15:8];
assign drp_wdata    = drp_w_enable ? reg400[7:0]: 8'd0;
wire pll_reset = reg403[8];
dr1_phy_pll_vtc_e2dadf6740ca
  #(
      .FBKCLK("VCO_PHASE0"),
      .FBKCLK_INT("VCO_PHASE0"),
      .REFCLK_DIV(REFCLK_DIV),          // 使用计算得到的n值
      .FBCLK_DIV(FBCLK_DIV),            // 使用计算得到的m值
      .CLKC0_FPHASE(0),
      .CLKC0_CPHASE(29),             
      .CLKC0_DIV(CLKC0_DIV),            // 使用计算得到的c值
      .CLKC0_DUTY_INT(CLKC0_DUTY_INT),  // 使用计算得到的占空比
      .CLKC0_ENABLE("ENABLE"),
      .FIN(FIN),                        // 使用参数化的输入频率
      .FEEDBK_MODE("NOCOMP"),
      .PLL_USR_RST("ENABLE"),
      .PLL_FEED_TYPE("INTERNAL"),
      .LPF_RES(2),
      .LPF_CAP(2),
      .ICP_CUR(12),
      .GMC_GAIN(2),
      .FRAC_ENABLE("DISABLE"),
      .DITHER_ENABLE("DISABLE"),
      .SDM_FRAC(0),
      .SSC_AMP(0.0000),
      .MPHASE_ENABLE("DISABLE"),
      .DYN_PHASE_PATH_SEL("DISABLE"),
      .DYN_FPHASE_EN("DISABLE"),
      .CLKC0_FPHASE_RSTSEL(0),
      .CLKC0_DUTY50("ENABLE"),
      .INTPI(0),
      .SSC_ENABLE("DISABLE"),
      .SSC_MODE("DOWN"),
      .SSC_FREQ_DIV(0),
      .SSC_RNGE(0),
      .HIGH_SPEED_EN("DISABLE")
  )dr1_pll_vtc_Inst
  (
      .clk1_en(1'b1),
      .clk1_out(),
      .clkb1_out(),
      .clk2_en(1'b0),
      .clk2_out(),
      .clkb2_out(),
      .clk3_en(1'b0),
      .clk3_out(),
      .clkb3_out(),
      .clk4_en(1'b0),
      .clk4_out(),
      .clkb4_out(),
      .clk5_en(1'b0),
      .clk5_out(),
      .clkb5_out(),
      .clk6_en(1'b0),
      .clk6_out(),
      .clkb6_out(),
      .refclk(ref_clk),
      .ssc_en(1'b0),
      .ext_freq_mod_val(17'b00000000000000000),
      .ext_freq_mod_en(1'b0),
      .ext_freq_mod_clk(1'b0),
	  .clkc_rst(2'b00),
      .fbclk(1'b0),
      .cps_step(2'b00),
      .psclksel(3'b000),
      .psdone(),
      .psstep(1'b0),
      .psdown(1'b0),
      .psclk(1'b0),
      .pllpd(1'b0),
      .lock(vtg_pclk_locked),
      .reset(pll_reset),
      .wakeup(1'b0),
      .refclk_rst(1'b0),
      .clk0_en(reg403[0]),
      .clkb0_out(), 
      .clk0_out(pixel_clk), 
      .drp_clk(clk),
      .drp_rstn(drp_rst_n),
      .drp_sel(1'b1),
      .drp_rd(drp_r_enable),
      .drp_wr(drp_w_enable),
      .drp_addr(drp_addr),
      .drp_wdata(drp_wdata),
      .drp_err(),
      .drp_rdy(drp_status[0]),
      .drp_rdata(drp_rdata)
  );
  
//vtg时钟输出
assign vtg_pclk = pixel_clk;

 // 实例化修改后的VTG模块
vtg_v01_e2dadf6740ca #(
    .COUNTER_WIDTH(12)
) vtg_v01_inst (
    .clk(pixel_clk),
    .rst_n(vtg_pclk_locked),
    .vtg_en_n(reg8[0]),      // vtg使能信号，寄存器8的bit0控制
    .vtg_ce(vtg_ce),         // vtg使能信号, 和axi stream to video out ip 配合使用
    
    // 时序参数配置
    .h_active(reg1[15:0]), 
    .h_front(reg0[15:0]), 
    .h_sync(reg2[15:0]), 
    .h_back(reg3[15:0]),
    .v_active(reg5[15:0]), 
    .v_front(reg4[15:0]),  
    .v_sync(reg6[15:0]),  
    .v_back(reg7[15:0]),
    
    // 修改后的时序输出信号
    .vtg_hsync(vtg_hsync), 
    .vtg_vsync(vtg_vsync),
    .vtg_hblank(vtg_hblank), 
    .vtg_vblank(vtg_vblank),
    .vtg_de(vtg_active_video),
    .vtg_h_count(), 
    .vtg_v_count(),
    .vtg_frame_start(), 
    .vtg_line_start()
);
 // 用户逻辑添加结束
endmodule

