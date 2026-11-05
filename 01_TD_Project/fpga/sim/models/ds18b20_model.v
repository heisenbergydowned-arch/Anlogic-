//============================================================================
// ds18b20_model.v — DS18B20 1-Wire 从机行为模型（仅仿真）
//
// 开漏 + 外部上拉（tb 用 pullup 原语）。
// 实现：复位脉冲识别（低 ≥200µs）→ presence（释放后 30µs 拉低 90µs）；
//       位接收（主机下降沿后 30µs 采样：低=0 高=1）；
//       命令解码：Skip ROM(0xCC) + Convert T(0x44) / Read Scratchpad(0xBE)；
//       Scratchpad 发送：收到 0x44 时锁存 temp_code 并组 9 字节暂存器
//       （2 字节温度 + TH/TL/Config + 3 保留 + Dallas CRC8），
//       0xBE 后 LSB first 发 72 位，CRC 与 DUT 校验算法一致。
// 转换时间简化为 0（DUT 的 CONV_MS 等待覆盖真实 750ms）。
// frame_zero（运行时注入，v0.8）：1 = 下次 0x44 锁存的暂存器为 72 位
//       全 0（含 CRC 字节）——复现"总线读段恒 0"：Dallas CRC8 初值 0
//       喂 72 个 0 恰好校验通过，未修复的 DUT 会把 0x0000 当有效 0℃
//       发 vld。供 TB 验证 ds18b20 v0.8 全 0 帧拒绝（S_DONE nz_seen）。
//       presence 应答正常（总线本身健康）——与对地短路（总线释放检查
//       拦截）区分开，单独覆盖第二层防护。
//============================================================================
`timescale 1ns/1ps
module ds18b20_model #(
    parameter real  RST_TH_US = 200.0,   // 低电平 ≥ 此值判为复位脉冲
    parameter integer PRES_D_US = 30,    // presence 延迟（主机释放后）
    parameter integer PRES_W_US = 90     // presence 拉低宽度
)(
    inout  wire        dq,
    input  wire        en,         // 0 = 器件离线（不响应，无 presence）
    input  wire [15:0] temp_code,  // 0x44 时锁存的温度原始码
    input  wire        crc_bad,    // 1 = 发出的 CRC 字节取反（TB 注入坏帧）
    input  wire        frame_zero  // 1 = 全 0 帧注入（v0.8；未连接时为 z，不影响）
);
    // Dallas CRC8（多项式 X^8+X^5+X^4+1，初值 0，LSB first）
    // 与 ds18b20.v 中逐位移位实现等价：d 为 8 字节，d[0] 第 1 个喂入位
    function [7:0] crc8_dallas;
        input [63:0] d;
        integer k;
        reg [7:0] c;
        reg b;
        begin
            c = 8'h00;
            for (k = 0; k < 64; k = k + 1) begin
                b = d[k] ^ c[0];
                c = {1'b0, c[7:1]};
                if (b) c = c ^ 8'h8C;
            end
            crc8_dallas = c;
        end
    endfunction

    reg        drv;        // 开漏驱动
    reg [71:0] scratch;    // 9 字节暂存器（byte0 = 温度 LSB，LSB first 发送）
    reg [2:0]  state;      // 0=待命令1 1=待命令2 2=读发送 3=错误等待复位
    reg [7:0]  bit_acc;
    reg [3:0]  bit_idx;
    reg [6:0]  rd_idx;
    reg        bit_val;
    reg        is_reset;

    assign dq = drv ? 1'b0 : 1'bz;

    localparam [2:0] S_CMD1 = 3'd0, S_CMD2 = 3'd1, S_READ = 3'd2, S_BAD = 3'd3;

    // 位/复位时隙处理：返回 bit_val 与 is_reset
    // 采样点固定在下降沿后 30µs（1-Wire 从机采样窗 15~45µs），
    // 之后再监测低电平持续时间区分普通位与复位脉冲。
    task slot_rx;
        integer t_lo;
        begin
            #(30_000);                        // 到 30µs 采样点
            bit_val = (dq === 1'b1) ? 1'b1 : 1'b0;  // 高=1 低=0
            t_lo = 30;
            while (dq === 1'b0 && t_lo < 600) begin
                #(1000);   // 1µs 步进
                t_lo = t_lo + 1;
            end
            if (t_lo >= RST_TH_US) begin
                is_reset = 1'b1;
                if (en) begin
                    wait (dq === 1'b1);          // 主机已释放
                    #(PRES_D_US * 1000);
                    drv = 1'b1;                  // presence 拉低
                    #(PRES_W_US * 1000);
                    drv = 1'b0;
                end else begin
                    wait (dq === 1'b1);          // 离线：不驱动
                end
            end else begin
                is_reset = 1'b0;
            end
        end
    endtask

    // 读时隙发送一位（主机下降沿已发生）：2µs 后驱动
    task slot_tx;
        input b;
        integer t_lo;
        begin
            is_reset = 1'b0;
            #(2000);
            if (!b) begin
                drv = 1'b1;
            end
            #(30000);
            drv = 1'b0;
            // A real DS18B20 also recognises reset while a scratchpad read
            // is interrupted. Without this, aborting a bad frame leaves the
            // model in S_READ forever and falsely prevents fault recovery.
            t_lo = 32;
            while (dq === 1'b0 && t_lo < 600) begin
                #(1000);
                t_lo = t_lo + 1;
            end
            if (t_lo >= RST_TH_US) begin
                is_reset = 1'b1;
                wait (dq === 1'b1);
                if (en) begin
                    #(PRES_D_US * 1000);
                    drv = 1'b1;
                    #(PRES_W_US * 1000);
                    drv = 1'b0;
                end
            end
        end
    endtask

    // 组暂存器：byte0/1 温度、byte2/3 TH/TL、byte4 Config、byte5-7 保留、byte8 CRC
    task build_scratch;
        reg [63:0] body;
        begin
            body = {8'h00, 8'h00, 8'h00, 8'h7F, 8'h4B, 8'h4B,
                    temp_code[15:8], temp_code[7:0]};
            scratch = {crc8_dallas(body), body};
            if (frame_zero === 1'b1)          // 全 0 帧注入（v0.8）
                scratch = 72'd0;              // CRC=0x00：恰好通过 CRC 校验
        end
    endtask

    initial begin
        drv = 1'b0; state = S_CMD1;
        bit_acc = 0; bit_idx = 0; rd_idx = 0;
        bit_val = 0; is_reset = 0;
        build_scratch;                       // 上电默认 85°C 由 tb 传入 temp_code
        forever begin
            @(negedge dq);
            if (state == S_READ) begin
                slot_tx(scratch[rd_idx]);    // LSB first，72 位
                if (is_reset) begin
                    state = S_CMD1;
                    bit_idx = 0;
                    bit_acc = 0;
                    rd_idx = 0;
                end else begin
                    rd_idx = rd_idx + 1;
                    if (rd_idx == 7'd72) state = S_BAD;  // 发完，等下一复位
                end
            end else begin
                slot_rx;
                if (is_reset) begin
                    state   = S_CMD1;
                    bit_idx = 0;
                    bit_acc = 0;
                end else begin
                    bit_acc = {bit_val, bit_acc[7:1]};   // LSB first：先收位入低位
                    bit_idx = bit_idx + 1;
                    if (bit_idx == 4'd8) begin
                        case (state)
                            S_CMD1: state = (bit_acc == 8'hCC) ? S_CMD2 : S_BAD;
                            S_CMD2: begin
                                if (bit_acc == 8'h44) begin
                                    build_scratch;          // 转换完成：锁存温度
                                    if (crc_bad)            // 注入坏 CRC（TB stale 测试）
                                        scratch[71:64] = ~scratch[71:64];
                                    state = S_BAD;         // 等主机复位后读
                                end else if (bit_acc == 8'hBE) begin
                                    state = S_READ; rd_idx = 0;
                                end else begin
                                    state = S_BAD;
                                end
                            end
                            default: ;
                        endcase
                        bit_idx = 0;
                    end
                end
            end
        end
    end

endmodule
