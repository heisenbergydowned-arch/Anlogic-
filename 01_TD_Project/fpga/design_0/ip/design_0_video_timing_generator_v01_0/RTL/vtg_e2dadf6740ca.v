
//==============================================================================
// 视频时序生成器模块 (Video Timing Generator - VTG)
// 功能：生成标准视频时序信号，支持可配置的分辨率和时序参数
// 日期：
// 2025年9月14日 初始版本
// 20251022 消除vtg内部的时序违例，并去掉加密部分
//==============================================================================

module vtg_v01_e2dadf6740ca
#(
    parameter COUNTER_WIDTH = 12                // 计数器位宽，支持最大4095像素/行
)(
    // 时钟和复位接口
    input  wire                     clk,        // 像素时钟输入
    input  wire                     rst_n,      // 异步复位信号，低电平有效
    input  wire                     vtg_en_n,   // 时序生成使能信号，低电平有效
    input  wire                     vtg_ce,     // 时序生成使能信号，高电平有效
    
    // 水平时序参数配置接口
    input  wire [COUNTER_WIDTH-1:0] h_active,   // 水平有效像素数
    input  wire [COUNTER_WIDTH-1:0] h_front,    // 水平前肩时间
    input  wire [COUNTER_WIDTH-1:0] h_sync,     // 水平同步脉冲宽度
    input  wire [COUNTER_WIDTH-1:0] h_back,     // 水平后肩时间
    
    // 垂直时序参数配置接口  
    input  wire [COUNTER_WIDTH-1:0] v_active,   // 垂直有效行数
    input  wire [COUNTER_WIDTH-1:0] v_front,    // 垂直前肩时间
    input  wire [COUNTER_WIDTH-1:0] v_sync,     // 垂直同步脉冲宽度
    input  wire [COUNTER_WIDTH-1:0] v_back,     // 垂直后肩时间
    
    // 时序信号输出接口
    output reg                      vtg_hsync,   // 水平同步信号
    output reg                      vtg_vsync,   // 垂直同步信号
    output reg                      vtg_hblank,  // 水平消隐信号
    output reg                      vtg_vblank,  // 垂直消隐信号
    output reg                      vtg_de,      // 数据使能信号
    
    // 位置信息输出接口
    output wire [COUNTER_WIDTH-1:0] vtg_h_count, // 当前水平位置计数
    output wire [COUNTER_WIDTH-1:0] vtg_v_count, // 当前垂直位置计数
    
    // 状态指示输出接口
    output reg                      vtg_frame_start, // 帧起始脉冲
    output reg                      vtg_line_start,  // 行起始脉冲
    output wire                     vtg_active_video // 有效视频区域标志
);

/* 
时序图说明：

水平时序 (一行):
|<----------------------- H_TOTAL ------------------------->|
|<-Sync->|<-Back->|<-----Active Video---->|<-Front->|
|        |        |                       |         |
|________|________|_______________________|_________|
0      H_SYNC  H_SYNC+   H_SYNC+H_BACK+    H_TOTAL
              H_BACK    H_BACK+H_ACTIVE

垂直时序 (一帧):
|<----------------------- V_TOTAL ------------------------->|
|<-Sync->|<-Back->|<-----Active Video---->|<-Front->|
|        |        |                       |         |
|________|________|_______________________|_________|
0      V_SYNC  V_SYNC+   V_SYNC+V_BACK+    V_TOTAL
              V_BACK    V_BACK+V_ACTIVE

信号含义：
- Sync: 同步脉冲期间，HSYNC/VSYNC为低电平
- Back: 同步脉冲后的后肩时间
- Active Video: 有效视频数据传输期间
- Front: 前肩时间，准备下一个同步脉冲
*/

//==============================================================================
// 内部信号定义
//==============================================================================
reg  [COUNTER_WIDTH-1:0] h_counter;            // 水平扫描计数器
reg  [COUNTER_WIDTH-1:0] v_counter;            // 垂直扫描计数器

wire [COUNTER_WIDTH-1:0] h_total;              // 水平总周期
wire [COUNTER_WIDTH-1:0] v_total;              // 垂直总周期

wire [COUNTER_WIDTH-1:0] h_sync_end;           // 水平同步结束位置
wire [COUNTER_WIDTH-1:0] h_back_end;           // 水平后肩结束位置  
wire [COUNTER_WIDTH-1:0] h_active_end;         // 水平有效区结束位置

wire [COUNTER_WIDTH-1:0] v_sync_end;           // 垂直同步结束位置
wire [COUNTER_WIDTH-1:0] v_back_end;           // 垂直后肩结束位置
wire [COUNTER_WIDTH-1:0] v_active_end;         // 垂直有效区结束位置

wire h_counter_max;                            // 水平计数器到达最大值
wire v_counter_max;                            // 垂直计数器到达最大值

//==============================================================================
// 配置参数跨时钟同步
//==============================================================================
(* ASYNC_REG = "TRUE" *) reg rst_sync_ff1;    // 复位同步器一级
(* ASYNC_REG = "TRUE" *) reg rst_sync_ff2;    // 复位同步器二级
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] h_front_sync_ff1;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] h_front_sync_ff2;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] h_active_sync_ff1;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] h_active_sync_ff2;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] h_sync_sync_ff1;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] h_sync_sync_ff2;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] h_back_sync_ff1;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] h_back_sync_ff2;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] v_front_sync_ff1;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] v_front_sync_ff2;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] v_active_sync_ff1;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] v_active_sync_ff2;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] v_sync_sync_ff1;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] v_sync_sync_ff2;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] v_back_sync_ff1;
(* ASYNC_REG = "TRUE" *) reg [COUNTER_WIDTH-1:0] v_back_sync_ff2;

wire [COUNTER_WIDTH-1:0] h_front_cfg  = h_front_sync_ff2;
wire [COUNTER_WIDTH-1:0] h_active_cfg = h_active_sync_ff2;
wire [COUNTER_WIDTH-1:0] h_sync_cfg   = h_sync_sync_ff2;
wire [COUNTER_WIDTH-1:0] h_back_cfg   = h_back_sync_ff2;
wire [COUNTER_WIDTH-1:0] v_front_cfg  = v_front_sync_ff2;
wire [COUNTER_WIDTH-1:0] v_active_cfg = v_active_sync_ff2;
wire [COUNTER_WIDTH-1:0] v_sync_cfg   = v_sync_sync_ff2;
wire [COUNTER_WIDTH-1:0] v_back_cfg   = v_back_sync_ff2;
wire rst_sync_n   = rst_n;              // 复位信号
wire vtg_en_n_ff2 = rst_sync_ff2; // 使能信号同步

//==============================================================================
// 时序参数计算
//==============================================================================
// 计算各个时序边界点
assign h_total      = h_sync_cfg + h_back_cfg + h_active_cfg + h_front_cfg;
assign v_total      = v_sync_cfg + v_back_cfg + v_active_cfg + v_front_cfg;

assign h_sync_end   = h_sync_cfg - 1;
assign h_back_end   = h_sync_cfg + h_back_cfg - 1;
assign h_active_end = h_sync_cfg + h_back_cfg + h_active_cfg - 1;

assign v_sync_end   = v_sync_cfg - 1;
assign v_back_end   = v_sync_cfg + v_back_cfg - 1;  
assign v_active_end = v_sync_cfg + v_back_cfg + v_active_cfg - 1;

// 计数器到达最大值判断
assign h_counter_max = (h_counter == h_total - 1);
assign v_counter_max = (v_counter == v_total - 1);

// 输出当前计数值
assign vtg_h_count = h_counter;
assign vtg_v_count = v_counter;

// 有效视频区域标志（与vtg_de相同）
assign vtg_active_video = vtg_de;

//==============================================================================
// 水平扫描计数器
//==============================================================================
always @(posedge clk or negedge rst_sync_n) begin
    if (!rst_sync_n || !vtg_en_n_ff2) begin
        h_counter <= {COUNTER_WIDTH{1'b0}};
    end else if (vtg_ce) begin                      // 只有在使能时才计数
        if (h_counter_max) begin
            h_counter <= {COUNTER_WIDTH{1'b0}};     // 到达最大值时清零
        end else begin
            h_counter <= h_counter + 1'b1;         // 正常递增
        end
    end
    // 当disable时，计数器保持当前值
end

//==============================================================================
// 垂直扫描计数器  
//==============================================================================
always @(posedge clk or negedge rst_sync_n) begin
    if (!rst_sync_n || !vtg_en_n_ff2) begin
        v_counter <= {COUNTER_WIDTH{1'b0}};
    end else if (vtg_ce) begin                      // 只有在使能时才计数
        if (h_counter_max) begin                    // 只在行结束时更新
            if (v_counter_max) begin
                v_counter <= {COUNTER_WIDTH{1'b0}}; // 到达最大值时清零
            end else begin
                v_counter <= v_counter + 1'b1;     // 正常递增
            end
        end
    end
    // 当disable时，计数器保持当前值
end

//==============================================================================
// 同步信号生成
//==============================================================================
always @(posedge clk or negedge rst_sync_n) begin
    if (!rst_sync_n || !vtg_en_n_ff2) begin
        vtg_hsync <= 1'b1;  // 复位时为高电平（非激活状态）
        vtg_vsync <= 1'b1;
    end else if (vtg_ce ) begin
        // 水平同步信号：在同步脉冲期间为低电平
        vtg_hsync <= (h_counter > h_sync_end);
        
        // 垂直同步信号：在同步脉冲期间为低电平  
        vtg_vsync <= (v_counter > v_sync_end);
    end else begin
        // 当disable时，同步信号保持非激活状态（高电平）
        vtg_hsync <= 1'b1;
        vtg_vsync <= 1'b1;
    end
end

//==============================================================================
// 消隐信号生成
//==============================================================================
always @(posedge clk or negedge rst_sync_n) begin
    if (!rst_sync_n || !vtg_en_n_ff2) begin
        vtg_hblank <= 1'b1; // 复位时为消隐状态
        vtg_vblank <= 1'b1;
    end else if (vtg_ce) begin
        // 水平消隐：只有在有效显示区域内才为低电平
        vtg_hblank <= !((h_counter > h_back_end) && (h_counter <= h_active_end));
        
        // 垂直消隐：只有在有效显示行内才为低电平
        vtg_vblank <= !((v_counter > v_back_end) && (v_counter <= v_active_end));
    end else begin
        // 当disable时，消隐信号保持激活状态（高电平）
        vtg_hblank <= 1'b1;
        vtg_vblank <= 1'b1;
    end
end

//==============================================================================
// 数据使能信号生成
//==============================================================================  
always @(posedge clk or negedge rst_sync_n) begin
    if (!rst_sync_n || !vtg_en_n_ff2) begin
        vtg_de <= 1'b0;
    end else if (vtg_ce ) begin
        // 数据使能：只有在水平和垂直有效区域的交集内才有效
        vtg_de <= ((h_counter > h_back_end) && (h_counter <= h_active_end)) &&
                  ((v_counter > v_back_end) && (v_counter <= v_active_end));
    end else begin
        // 当disable时，数据使能信号保持低电平
        vtg_de <= 1'b0;
    end
end

//==============================================================================
// 帧和行起始脉冲生成
//==============================================================================
always @(posedge clk or negedge rst_sync_n) begin
    if (!rst_sync_n || !vtg_en_n_ff2) begin
        vtg_frame_start <= 1'b0;
        vtg_line_start <= 1'b0;
    end else if (vtg_ce) begin
        // 帧起始脉冲：在新帧开始时产生一个时钟周期的脉冲
        vtg_frame_start <= (h_counter == 0) && (v_counter == 0);
        
        // 行起始脉冲：在每行开始时产生一个时钟周期的脉冲  
        vtg_line_start <= (h_counter == 0);
    end else begin
        // 当disable时，起始脉冲保持低电平
        vtg_frame_start <= 1'b0;
        vtg_line_start <= 1'b0;
    end
end

//==============================================================================
// 配置参数同步逻辑
//==============================================================================

always @(posedge clk) begin
    rst_sync_ff1      <= vtg_en_n;
    rst_sync_ff2      <= rst_sync_ff1;
    h_front_sync_ff1  <= h_front;
    h_front_sync_ff2  <= h_front_sync_ff1;
    h_active_sync_ff1 <= h_active;
    h_active_sync_ff2 <= h_active_sync_ff1;
    h_sync_sync_ff1   <= h_sync;
    h_sync_sync_ff2   <= h_sync_sync_ff1;
    h_back_sync_ff1   <= h_back;
    h_back_sync_ff2   <= h_back_sync_ff1;
    v_front_sync_ff1  <= v_front;
    v_front_sync_ff2  <= v_front_sync_ff1;
    v_active_sync_ff1 <= v_active;
    v_active_sync_ff2 <= v_active_sync_ff1;
    v_sync_sync_ff1   <= v_sync;
    v_sync_sync_ff2   <= v_sync_sync_ff1;
    v_back_sync_ff1   <= v_back;
    v_back_sync_ff2   <= v_back_sync_ff1;
       
end

//==============================================================================
// 时序参数有效性检查 (仿真用)
//==============================================================================

endmodule
