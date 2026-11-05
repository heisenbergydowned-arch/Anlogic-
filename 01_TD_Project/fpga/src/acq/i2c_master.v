//============================================================================
// i2c_master.v — I2C 主机（事务级，开漏 SDA/SCL，Fast-mode 时序，拉伸容错）
//
// 事务（u_req 电平发起，保持到 u_ack；u_ack 1clk 结束）：
//   写段：START + 器件地址(W) + u_nwr 字节（u_wr0/1/2，首字节=子地址/命令）
//   读段：u_nrd>0 时 RESTART + 器件地址(R) + 读 u_nrd 字节（末字节 NACK）
//   u_nwr=0 且 u_nrd>0：纯读（START + 地址(R) 直接读，AHT20 用）
// u_err（随 u_ack 有效）：总线卡死 / 任一字节无应答 / 时钟拉伸超时。
//
// 位时序：SDA 只在 SCL↓ 后 T_HOLD 才变化（杜绝同沿竞争产生伪 START/STOP）；
//         SCL 高 T_HIGH / 低 T_LOW（400kHz 时 1.2µs/1.3µs，满足 Fast-mode）。
// 读数据经 u_rd_valid/u_rd_data/u_rd_idx 流式输出（单事务最多 24 字节）。
//============================================================================
module i2c_master #(
    parameter CLK_FREQ   = 100_000_000,
    parameter I2C_FREQ   = 400_000,
    parameter STRETCH_US = 5_000        // 时钟拉伸上限，超时判错放弃本事务
)(
    input  wire       clk,
    input  wire       rst_n,
    inout  wire       io_sda,
    inout  wire       io_scl,

    input  wire       u_req,
    input  wire [6:0] u_dev,
    input  wire [2:0] u_nwr,
    input  wire [7:0] u_wr0,
    input  wire [7:0] u_wr1,
    input  wire [7:0] u_wr2,
    input  wire [4:0] u_nrd,
    output reg        u_ack,
    output reg        u_err,
    output reg        u_rd_valid,
    output reg [7:0]  u_rd_data,
    output reg [4:0]  u_rd_idx
);
    //--------------------------------------------------------------------
    // 时序参数（换算为时钟周期数）
    //--------------------------------------------------------------------
    localparam [15:0] T_PERIOD  = CLK_FREQ / I2C_FREQ;
    localparam [15:0] T_HIGH    = T_PERIOD * 12 / 25;    // 0.48×周期
    localparam [15:0] T_LOW     = T_PERIOD - T_HIGH;     // 0.52×周期
    localparam [15:0] T_HOLD    = T_PERIOD / 10;         // SDA 保持窗
    localparam [23:0] T_STRETCH = STRETCH_US * (CLK_FREQ / 1_000_000);

    // 开漏：oe=1 拉低，oe=0 释放（外部上拉）
    reg sda_oe, scl_oe;
    assign io_sda = sda_oe ? 1'b0 : 1'bz;
    assign io_scl = scl_oe ? 1'b0 : 1'bz;

    // SDA/SCL 输入 2FF 同步（外部开漏总线为异步电平信号；相对 400kHz
    // 位时序（2.5µs）两拍延迟 20ns 可忽略）
    reg [1:0] sda_sync, scl_sync;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sda_sync <= 2'b11; scl_sync <= 2'b11;
        end else begin
            sda_sync <= {sda_sync[0], io_sda};
            scl_sync <= {scl_sync[0], io_scl};
        end
    end
    wire sda_in = sda_sync[1];
    wire scl_in = scl_sync[1];

    localparam [4:0]
        S_IDLE = 5'd0,
        S_ST1  = 5'd1,   // START：SDA↓（SCL 高）
        S_ST2  = 5'd2,   //        SCL↓，保持 SDA
        S_B0   = 5'd3,   // 位：SCL 已低，SDA 保持旧值 T_HOLD
        S_B1   = 5'd4,   //     ：SDA 置位/释放，低电平余段
        S_B2   = 5'd5,   //     ：SCL↑（拉伸等待），高电平末采样
        S_A0   = 5'd6,   // 第 9 钟低段 a：SDA 保持（防伪 START 竞争）
        S_A0B  = 5'd7,   // 第 9 钟低段 b：释放（写）/ 驱动 ACK·NACK（读）
        S_A1   = 5'd8,   // 第 9 钟高段：末沿判 ACK / 完成读字节
        S_RS1  = 5'd9,   // RESTART：SDA↑（SCL 低）
        S_RS2  = 5'd10,  //          SCL↑
        S_RS3  = 5'd11,  //          SDA↓（重复 START）
        S_RS4  = 5'd12,  //          SCL↓，保持
        S_SP1  = 5'd13,  // STOP：SDA↓（SCL 低，保持窗后）
        S_SP2  = 5'd14,  //       SCL↑
        S_SP3  = 5'd15;  //       SDA↑（STOP 条件）→ 事务结束

    reg [4:0]  st;
    reg [15:0] ph, ph_lim;
    reg [23:0] stretch;
    reg [15:0] bufree;      // STOP 后总线空闲计时（tBUF）
    reg [2:0]  bit_cnt;
    reg [4:0]  byte_idx;    // 0=地址，1..3=u_wr0/1/2
    reg [4:0]  rd_cnt;      // 已完成读字节数
    reg [7:0]  sh_tx, sh_rx;
    reg        in_rd;       // 地址(R) 已发（纯读或 RESTART 后）
    reg        rx_byte;     // 当前字节为读数据（从机驱动 SDA）
    reg [2:0]  wr_left;
    reg [4:0]  rd_left;
    reg        err_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_IDLE; ph <= 16'd0; ph_lim <= 16'd0; stretch <= 24'd0;
            bufree <= 16'd0; bit_cnt <= 3'd0; byte_idx <= 5'd0; rd_cnt <= 5'd0;
            sh_tx <= 8'd0; sh_rx <= 8'd0; in_rd <= 1'b0; rx_byte <= 1'b0;
            wr_left <= 3'd0; rd_left <= 5'd0; err_r <= 1'b0;
            sda_oe <= 1'b0; scl_oe <= 1'b0;
            u_ack <= 1'b0; u_err <= 1'b0; u_rd_valid <= 1'b0;
            u_rd_data <= 8'd0; u_rd_idx <= 5'd0;
        end else begin
            u_ack      <= 1'b0;
            u_err      <= 1'b0;
            u_rd_valid <= 1'b0;

            case (st)
            //--------------------------------------------------------------
            S_IDLE: begin
                sda_oe <= 1'b0; scl_oe <= 1'b0;
                if (bufree != 16'd0) bufree <= bufree - 16'd1;
                if (u_req && bufree == 16'd0) begin
                    if (u_nwr == 3'd0 && u_nrd == 5'd0) begin
                        u_ack <= 1'b1;                    // 空事务
                    end else if (!sda_in || !scl_in) begin
                        u_ack <= 1'b1; u_err <= 1'b1;     // 总线卡死
                    end else begin
                        wr_left  <= u_nwr; rd_left <= u_nrd;
                        byte_idx <= 5'd0; rd_cnt <= 5'd0; bit_cnt <= 3'd0;
                        in_rd    <= (u_nwr == 3'd0);      // 纯读：地址直接带 R
                        rx_byte  <= 1'b0;
                        sh_tx    <= {u_dev, (u_nwr == 3'd0)};
                        err_r    <= 1'b0;
                        sda_oe   <= 1'b1;                 // START：SDA↓
                        ph <= 16'd0; ph_lim <= T_HIGH; st <= S_ST1;
                    end
                end
            end
            //--------------------------------------------------------------
            S_ST1: if (ph == ph_lim - 16'd1) begin
                scl_oe <= 1'b1;                           // SCL↓
                ph <= 16'd0; ph_lim <= T_HOLD; st <= S_ST2;
            end else ph <= ph + 16'd1;

            S_ST2: if (ph == ph_lim - 16'd1) begin
                sda_oe <= ~sh_tx[7];                      // 首位（oe=1 拉低=发 0）
                ph <= 16'd0; ph_lim <= T_LOW; st <= S_B1;
            end else ph <= ph + 16'd1;
            //--------------------------------------------------------------
            S_B0: if (ph == ph_lim - 16'd1) begin
                sda_oe <= rx_byte ? 1'b0 : ~sh_tx[7];     // SDA 保持窗后置位
                ph <= 16'd0; ph_lim <= T_LOW; st <= S_B1;
            end else ph <= ph + 16'd1;

            S_B1: if (ph == ph_lim - 16'd1) begin
                scl_oe <= 1'b0;                           // SCL↑
                stretch <= 24'd0; ph <= 16'd0; ph_lim <= T_HIGH; st <= S_B2;
            end else ph <= ph + 16'd1;

            S_B2: begin
                if (!scl_in) begin                        // 拉伸等待
                    stretch <= stretch + 24'd1;
                    if (stretch >= T_STRETCH) begin
                        err_r <= 1'b1;
                        ph <= 16'd0; ph_lim <= T_HOLD; st <= S_SP1;
                    end
                end else if (ph == ph_lim - 16'd1) begin
                    if (rx_byte) sh_rx <= {sh_rx[6:0], sda_in};
                    scl_oe <= 1'b1;                       // SCL↓（SDA 暂保持）
                    if (bit_cnt == 3'd7) begin            // → 第 9 钟
                        ph <= 16'd0; ph_lim <= T_HOLD; st <= S_A0;
                    end else begin
                        bit_cnt <= bit_cnt + 3'd1;
                        sh_tx <= {sh_tx[6:0], 1'b0};      // 发送移位：下一bit
                        ph <= 16'd0; ph_lim <= T_HOLD; st <= S_B0;
                    end
                end else ph <= ph + 16'd1;
            end
            //--------------------------------------------------------------
            S_A0: if (ph == ph_lim - 16'd1) begin         // 保持窗结束
                if (rx_byte)                              // 读：主机应答位
                    sda_oe <= (rd_cnt == rd_left - 5'd1) ? 1'b0 : 1'b1;
                else                                      // 写：释放给从机应答
                    sda_oe <= 1'b0;
                ph <= 16'd0; ph_lim <= T_LOW - T_HOLD; st <= S_A0B;
            end else ph <= ph + 16'd1;

            S_A0B: if (ph == ph_lim - 16'd1) begin
                scl_oe <= 1'b0;                           // SCL↑
                stretch <= 24'd0; ph <= 16'd0; ph_lim <= T_HIGH; st <= S_A1;
            end else ph <= ph + 16'd1;

            S_A1: begin
                if (!scl_in) begin
                    stretch <= stretch + 24'd1;
                    if (stretch >= T_STRETCH) begin
                        err_r <= 1'b1;
                        ph <= 16'd0; ph_lim <= T_HOLD; st <= S_SP1;
                    end
                end else if (ph == ph_lim - 16'd1) begin
                    scl_oe <= 1'b1;                       // SCL↓
                    if (!rx_byte) begin                   // 地址/写字节完成
                        if (sda_in) begin                 // 无应答
                            err_r <= 1'b1;
                            ph <= 16'd0; ph_lim <= T_HOLD; st <= S_SP1;
                        end else if (!in_rd) begin
                            if (byte_idx < {2'b0, wr_left}) begin
                                case (byte_idx[1:0])
                                    2'd0:    sh_tx <= u_wr0;
                                    2'd1:    sh_tx <= u_wr1;
                                    default: sh_tx <= u_wr2;
                                endcase
                                byte_idx <= byte_idx + 5'd1;
                                bit_cnt  <= 3'd0;
                                ph <= 16'd0; ph_lim <= T_HOLD; st <= S_B0;
                            end else if (rd_left != 5'd0) begin
                                sh_tx <= {u_dev, 1'b1};   // 地址(R)
                                in_rd <= 1'b1;
                                bit_cnt <= 3'd0;
                                ph <= 16'd0; ph_lim <= T_HOLD; st <= S_RS1;
                            end else begin
                                ph <= 16'd0; ph_lim <= T_HOLD; st <= S_SP1;
                            end
                        end else begin                    // 地址(R) 已应答 → 读数据
                            bit_cnt <= 3'd0; rx_byte <= 1'b1;
                            ph <= 16'd0; ph_lim <= T_HOLD; st <= S_B0;
                        end
                    end else begin                        // 读字节完成
                        u_rd_valid <= 1'b1; u_rd_data <= sh_rx; u_rd_idx <= rd_cnt;
                        rd_cnt <= rd_cnt + 5'd1;
                        if (rd_cnt + 5'd1 < rd_left) begin
                            bit_cnt <= 3'd0;
                            ph <= 16'd0; ph_lim <= T_HOLD; st <= S_B0;
                        end else begin
                            ph <= 16'd0; ph_lim <= T_HOLD; st <= S_SP1;
                        end
                    end
                end else ph <= ph + 16'd1;
            end
            //--------------------------------------------------------------
            S_RS1: if (ph == ph_lim - 16'd1) begin        // SDA↑（SCL 低）
                sda_oe <= 1'b0;
                ph <= 16'd0; ph_lim <= T_HOLD; st <= S_RS2;
            end else ph <= ph + 16'd1;

            S_RS2: if (ph == ph_lim - 16'd1) begin        // SCL↑
                scl_oe <= 1'b0;
                ph <= 16'd0; ph_lim <= T_HIGH; st <= S_RS3;
            end else ph <= ph + 16'd1;

            S_RS3: if (ph == ph_lim - 16'd1) begin        // SDA↓ = 重复 START
                sda_oe <= 1'b1;
                ph <= 16'd0; ph_lim <= T_HIGH; st <= S_RS4;
            end else ph <= ph + 16'd1;

            S_RS4: if (ph == ph_lim - 16'd1) begin        // SCL↓，保持
                scl_oe <= 1'b1;
                // 走 S_B0：保持窗后装载地址首位（直接进 S_B1 会导致
                // SDA 停留在 0 且 SCL 低电平仅 T_HOLD，地址 MSB=1 时出错）
                ph <= 16'd0; ph_lim <= T_HOLD; st <= S_B0;
            end else ph <= ph + 16'd1;
            //--------------------------------------------------------------
            // STOP：S_SP1 入口时 SCL 已低；SDA↓ 须在保持窗后（本状态计 T_HOLD）
            S_SP1: if (ph == ph_lim - 16'd1) begin
                sda_oe <= 1'b1;                           // SDA↓（SCL 低）
                ph <= 16'd0; ph_lim <= T_HIGH; st <= S_SP2;
            end else ph <= ph + 16'd1;

            S_SP2: if (ph == ph_lim - 16'd1) begin
                scl_oe <= 1'b0;                           // SCL↑
                ph <= 16'd0; ph_lim <= T_HIGH; st <= S_SP3;
            end else ph <= ph + 16'd1;

            // SCL↑ 后保持 T_HIGH 再放 SDA↑（tSU;STO ≥ 0.6µs；
            // 400kHz 时 T_HIGH=1.2µs，S_SP2/S_SP3 各计一段）
            S_SP3: if (ph == ph_lim - 16'd1) begin
                sda_oe <= 1'b0;                           // SDA↑ = STOP
                u_ack  <= 1'b1; u_err <= err_r;           // 事务结束
                bufree <= T_LOW;                          // tBUF
                st <= S_IDLE;
            end else ph <= ph + 16'd1;
            //--------------------------------------------------------------
            default: st <= S_IDLE;
            endcase
        end
    end
endmodule
