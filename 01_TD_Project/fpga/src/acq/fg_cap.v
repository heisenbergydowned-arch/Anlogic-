//============================================================================
// fg_cap.v — 风扇 FG（转速反馈）输入捕获
//
// 测周法：统计两次有效上升沿之间的时钟周期数（period_cnt），
// 上位机换算 RPM = 60 × CLK_FREQ / (period_cnt × 每转脉冲数)。
// 两级同步 + 积分式毛刺滤波（电平持续 GLITCH_US 才翻转）+ 超时检测。
// period_cnt 有效性门控：复位后首个边沿（armed=0，基准从复位起算）与
// 超时后首个边沿（间隔为停转间隙而非转动周期）均只校准基准、
// 不更新 period_cnt、不发 vld——下游见到的每个 vld 均为真实转动周期。
//============================================================================
module fg_cap #(
    parameter CLK_FREQ   = 100_000_000,
    parameter GLITCH_US  = 20,        // 毛刺过滤窗（FG 波形振铃抑制）
    parameter TIMEOUT_US = 400_000    // 无边沿判超时（卡死门限 250rpm ≈ 120ms/脉冲的 ~3.3 倍）
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        fg,             // 风扇 FG（外部 10kΩ 上拉到 3.3V）
    output reg  [31:0] period_cnt,     // 上次测得的周期（时钟数）
    output reg         vld,            // 新周期值有效脉冲
    output reg  [31:0] pulse_count,    // 累计脉冲数
    output reg         timeout         // 1 = 超时无 FG
);
    // 两级同步
    reg [1:0] fg_sync;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) fg_sync <= 2'b11;
        else        fg_sync <= {fg_sync[0], fg};
    end
    wire fg_c = fg_sync[1];

    // 积分式毛刺滤波：电平须持续 FILTER_TICKS 才翻转输出
    localparam [19:0] FILTER_TICKS = (CLK_FREQ / 1_000_000) * GLITCH_US;
    reg        filt;
    reg [19:0] cnt_f;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            filt <= 1'b1; cnt_f <= 20'd0;
        end else if (fg_c == filt) begin
            cnt_f <= 20'd0;
        end else if (cnt_f >= FILTER_TICKS) begin
            filt <= fg_c;
            cnt_f <= 20'd0;
        end else begin
            cnt_f <= cnt_f + 20'd1;
        end
    end

    // 上升沿检测（滤波后）
    reg filt_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) filt_d <= 1'b1;
        else        filt_d <= filt;
    end
    wire edge_ok = filt & ~filt_d;

    // 周期计数 / 脉冲累计 / 超时
    reg [31:0] per_run;
    reg [31:0] to_cnt;
    reg        armed;         // 复位后已见过首个边沿（其 period 无效，丢弃）
    localparam [31:0] TO_TICKS = (CLK_FREQ / 1_000_000) * TIMEOUT_US;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            period_cnt <= 32'd0; vld <= 1'b0; pulse_count <= 32'd0;
            timeout <= 1'b0; per_run <= 32'd0; to_cnt <= 32'd0; armed <= 1'b0;
        end else begin
            vld <= 1'b0;
            per_run <= per_run + 32'd1;
            to_cnt  <= to_cnt + 32'd1;
            if (to_cnt >= TO_TICKS) timeout <= 1'b1;

            if (edge_ok) begin
                if (armed && !timeout) begin
                    period_cnt <= per_run;
                    vld        <= 1'b1;
                end
                pulse_count<= pulse_count + 32'd1;
                per_run    <= 32'd1;
                to_cnt     <= 32'd0;
                timeout    <= 1'b0;
                armed      <= 1'b1;   // 首个边沿只校准基准，不发 vld
            end
        end
    end

endmodule
