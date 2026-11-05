//============================================================================
// tb_sns_sync.v — sns_sync 集成测试（三场景并行）
//
// 场景1：ICM-A/B 全在线（共用 SPI 总线、双片选）
//   A 模型 ODR=3960Hz、B 模型 ODR=3980Hz——均偏离标称 4kHz（真实晶振偏差）。
//   校验：init_done；初始化寄存器写入值（含 INT_PIN_CFG=0 显式锁定
//         DRDY 清零语义；PWR_MGMT_2=0x07 陀螺 standby、ACCEL_CONFIG2=0x08
//         4kHz 档——v0.7 4kSps 配方）；A/B 14 字节突发读固定样式（ax/gx
//         等通路）；
//         零丢样（节拍 8kHz > ODR 4kHz，论证见 sns_sync.v 头注释）：
//         250ms 窗口内每个落地样本恰好发射一次 vld——
//         dup==0（无重复样本）、jump==0（无序号跳变，样本不被跳过）、
//         vld ≈ 窗口时长×ODR（A≈990、B≈995），tick==2000（8kHz）；
//         诊断计数器自检：seq_a==vld 计数、drdy0 == tick−vld（±2，
//         窗口边界相位差）；
//         A/B 读出间隔 < 100µs。注意：这只是两片 SPI 读出完成的时刻差，
//         两片各自内部时钟自由采样，实际采样时刻差需台架实测，
//         本参数不作为同步精度指标。
//   注：SPI_DIV 不在此覆盖，沿用 RTL 默认（=综合上板值），保证仿真/实现一致。
//   注：模型 CS 期间冻结样本装载（icm20602_model 头注释），把"撕裂帧"
//       （真实器件存在、概率性，见 sns_sync.v 头注释残余风险①）与
//       "逻辑丢样"解耦，dup/jump 才能做精确断言。
//
// 场景2：ICM-B 悬空（miso 下拉为 0，模拟器件缺席）
//   校验：err_icm_b=1 但 init_done=1（容错不阻塞）；
//         vld_icm_a 照常；vld_icm_b 无脉冲。
//
// 场景3：ICM-A 悬空（对称场景）
//   校验：err_icm_a=1、init_done=1；vld_icm_b 照常有数据（单侧掉线
//         不拖累对侧——A 掉线后 B 仍每拍被读）。
//
// 场景4：ICM-A 冻结输出注入（模型 FROZEN=1：样本字节恒定、DRDY 照常
//        置位）+ ICM-B 悬空
//   校验：dup_a_cnt 每次 vld（首样本除外）+1 → dup == vld − 1（负向
//         注入验证 dup 计数器确实能检出"重复消费/器件冻结输出"）；
//         B 悬空无 vld → dup_b 恒 0；正常场景 1 的 dup_a/b_cnt 必须为 0。
//
// 场景5（v0.8）：ICM-A 停发新数据注入（模型 halt=1：SPI 应答正常、
//        WHO_AM_I 照常回读、DRDY 恒 0、数据字节保持陈旧值）+ B 正常在线
//   复现审核问题③：坏帧看门狗（全 0x00/全 0xFF）对"应答正常但停发"
//        完全失明，err 永不置位。
//   校验：SAMPLE_TIMEOUT_MS(20ms 压缩) 无 vld → err_icm_a=1 且
//         wd_a_cnt+1；停发期间 vld_a 冻结（DRDY=0 不消费）；
//         对侧 B 全程健康（err_b 恒 0、vld 持续——验证重试间隙
//         不误判健康侧）；halt 释放后经周期重试（RETRY_MS=50ms 压缩）
//         自愈：err 清 0、vld_a 恢复增长。
//
// 参数压缩：POWERUP/RESET/POSTINIT = 1ms（场景5 另压缩 RETRY/超时）。
//============================================================================
`timescale 1ns/1ps
module tb_sns_sync;
    parameter CLK_FREQ=100_000_000, SPI_DIV_TEST=4;
    localparam integer CLK_NS = 1000000000/CLK_FREQ;
    // Optional faster simulation: CLK_FREQ=25MHz, SPI_DIV_TEST=2.
    // ODR and observation windows remain real-time; SCLK becomes 3.125MHz; SPI_DIV >= 2 preserves MISO synchronizer latency.

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #(CLK_NS/2.0) clk = ~clk;

    integer errors = 0;
    task check;
        input cond;
        input [255:0] tag;
        begin
            if (cond !== 1'b1) begin
                errors = errors + 1;
                $display("[%0s] FAIL @%0t", tag, $time);
            end
        end
    endtask

    //====================================================================
    // 场景 1：全在线
    //====================================================================
    wire        sclk1, mosi1;
    tri         miso1;
    wire        cs_a1_n, cs_b1_n;
    wire signed [15:0] a1_ax, a1_ay, a1_az, a1_t, a1_gx, a1_gy, a1_gz;
    wire signed [15:0] b1_ax, b1_ay, b1_az, b1_t, b1_gx, b1_gy, b1_gz;
    wire        vld_a1, vld_b1, done1, err_a1, err_b1;
    wire [15:0] seq_a1, seq_b1, tick1, vlca1, vlcb1, d0a1, d0b1;
    wire [7:0]  wda1, wdb1;
    wire [15:0] dup_a1, dup_b1;

    sns_sync #(
        .CLK_FREQ   (CLK_FREQ),
        .SPI_DIV    (SPI_DIV_TEST),
        .SAMPLE_HZ  (8000),
        .POWERUP_MS (1),
        .RESET_MS   (1),
        .POSTINIT_MS(1)
    ) dut1 (
        .clk (clk), .rst_n (rst_n),
        .spi_sclk (sclk1), .spi_mosi (mosi1), .spi_miso (miso1),
        .cs_icm_a_n (cs_a1_n), .cs_icm_b_n (cs_b1_n),
        .icm_a_ax (a1_ax), .icm_a_ay (a1_ay), .icm_a_az (a1_az),
        .icm_a_t (a1_t),  .icm_a_gx (a1_gx), .icm_a_gy (a1_gy), .icm_a_gz (a1_gz),
        .vld_icm_a (vld_a1),
        .icm_b_ax (b1_ax), .icm_b_ay (b1_ay), .icm_b_az (b1_az),
        .icm_b_t (b1_t),  .icm_b_gx (b1_gx), .icm_b_gy (b1_gy), .icm_b_gz (b1_gz),
        .vld_icm_b (vld_b1),
        .init_done (done1), .err_icm_a (err_a1), .err_icm_b (err_b1),
        .seq_a (seq_a1), .seq_b (seq_b1), .tick_cnt (tick1),
        .vld_a_cnt (vlca1), .vld_b_cnt (vlcb1),
        .drdy0_a_cnt (d0a1), .drdy0_b_cnt (d0b1),
        .wd_a_cnt (wda1), .wd_b_cnt (wdb1),
        .dup_a_cnt (dup_a1), .dup_b_cnt (dup_b1)
    );

    icm20602_model #(.WHO_ID(8'h12), .DATA_BASE(8'h01), .ODR_HZ(3960)) u_a1 (
        .sclk(sclk1), .mosi(mosi1), .miso(miso1), .cs_n(cs_a1_n));
    icm20602_model #(.WHO_ID(8'h12), .DATA_BASE(8'h11), .ODR_HZ(3980)) u_b1 (
        .sclk(sclk1), .mosi(mosi1), .miso(miso1), .cs_n(cs_b1_n));

    //====================================================================
    // 场景 2：ICM-B 悬空
    //====================================================================
    wire        sclk2, mosi2;
    tri0        miso2;      // 无器件驱动时读 0
    wire        cs_a2_n, cs_b2_n;
    wire signed [15:0] a2_ax, a2_ay, a2_az, a2_t, a2_gx, a2_gy, a2_gz;
    wire signed [15:0] b2_ax, b2_ay, b2_az, b2_t, b2_gx, b2_gy, b2_gz;
    wire        vld_a2, vld_b2, done2, err_a2, err_b2;

    sns_sync #(
        .CLK_FREQ   (CLK_FREQ),
        .SPI_DIV    (SPI_DIV_TEST),
        .SAMPLE_HZ  (8000),
        .POWERUP_MS (1),
        .RESET_MS   (1),
        .POSTINIT_MS(1)
    ) dut2 (
        .clk (clk), .rst_n (rst_n),
        .spi_sclk (sclk2), .spi_mosi (mosi2), .spi_miso (miso2),
        .cs_icm_a_n (cs_a2_n), .cs_icm_b_n (cs_b2_n),
        .icm_a_ax (a2_ax), .icm_a_ay (a2_ay), .icm_a_az (a2_az),
        .icm_a_t (a2_t),  .icm_a_gx (a2_gx), .icm_a_gy (a2_gy), .icm_a_gz (a2_gz),
        .vld_icm_a (vld_a2),
        .icm_b_ax (b2_ax), .icm_b_ay (b2_ay), .icm_b_az (b2_az),
        .icm_b_t (b2_t),  .icm_b_gx (b2_gx), .icm_b_gy (b2_gy), .icm_b_gz (b2_gz),
        .vld_icm_b (vld_b2),
        .init_done (done2), .err_icm_a (err_a2), .err_icm_b (err_b2)
    );

    icm20602_model #(.WHO_ID(8'h12), .DATA_BASE(8'h21)) u_a2 (
        .sclk(sclk2), .mosi(mosi2), .miso(miso2), .cs_n(cs_a2_n));
    // ICM-B 悬空：无模型

    //====================================================================
    // 场景 3：ICM-A 悬空（B 存活）
    //====================================================================
    wire        sclk3, mosi3;
    tri0        miso3;
    wire        cs_a3_n, cs_b3_n;
    wire signed [15:0] a3_ax, a3_ay, a3_az, a3_t, a3_gx, a3_gy, a3_gz;
    wire signed [15:0] b3_ax, b3_ay, b3_az, b3_t, b3_gx, b3_gy, b3_gz;
    wire        vld_a3, vld_b3, done3, err_a3, err_b3;

    sns_sync #(
        .CLK_FREQ   (CLK_FREQ),
        .SPI_DIV    (SPI_DIV_TEST),
        .SAMPLE_HZ  (8000),
        .POWERUP_MS (1),
        .RESET_MS   (1),
        .POSTINIT_MS(1)
    ) dut3 (
        .clk (clk), .rst_n (rst_n),
        .spi_sclk (sclk3), .spi_mosi (mosi3), .spi_miso (miso3),
        .cs_icm_a_n (cs_a3_n), .cs_icm_b_n (cs_b3_n),
        .icm_a_ax (a3_ax), .icm_a_ay (a3_ay), .icm_a_az (a3_az),
        .icm_a_t (a3_t),  .icm_a_gx (a3_gx), .icm_a_gy (a3_gy), .icm_a_gz (a3_gz),
        .vld_icm_a (vld_a3),
        .icm_b_ax (b3_ax), .icm_b_ay (b3_ay), .icm_b_az (b3_az),
        .icm_b_t (b3_t),  .icm_b_gx (b3_gx), .icm_b_gy (b3_gy), .icm_b_gz (b3_gz),
        .vld_icm_b (vld_b3),
        .init_done (done3), .err_icm_a (err_a3), .err_icm_b (err_b3)
    );

    // ICM-A 悬空：无模型
    icm20602_model #(.WHO_ID(8'h12), .DATA_BASE(8'h31)) u_b3 (
        .sclk(sclk3), .mosi(mosi3), .miso(miso3), .cs_n(cs_b3_n));

    //====================================================================
    // 场景 4：ICM-A 冻结输出（FROZEN 负向注入）+ ICM-B 悬空
    //====================================================================
    wire        sclk4, mosi4;
    tri0        miso4;
    wire        cs_a4_n, cs_b4_n;
    wire signed [15:0] a4_ax, a4_ay, a4_az, a4_t, a4_gx, a4_gy, a4_gz;
    wire signed [15:0] b4_ax, b4_ay, b4_az, b4_t, b4_gx, b4_gy, b4_gz;
    wire        vld_a4, vld_b4, done4, err_a4, err_b4;
    wire [15:0] dup_a4, dup_b4;

    sns_sync #(
        .CLK_FREQ   (CLK_FREQ),
        .SPI_DIV    (SPI_DIV_TEST),
        .SAMPLE_HZ  (8000),
        .POWERUP_MS (1),
        .RESET_MS   (1),
        .POSTINIT_MS(1)
    ) dut4 (
        .clk (clk), .rst_n (rst_n),
        .spi_sclk (sclk4), .spi_mosi (mosi4), .spi_miso (miso4),
        .cs_icm_a_n (cs_a4_n), .cs_icm_b_n (cs_b4_n),
        .icm_a_ax (a4_ax), .icm_a_ay (a4_ay), .icm_a_az (a4_az),
        .icm_a_t (a4_t),  .icm_a_gx (a4_gx), .icm_a_gy (a4_gy), .icm_a_gz (a4_gz),
        .vld_icm_a (vld_a4),
        .icm_b_ax (b4_ax), .icm_b_ay (b4_ay), .icm_b_az (b4_az),
        .icm_b_t (b4_t),  .icm_b_gx (b4_gx), .icm_b_gy (b4_gy), .icm_b_gz (b4_gz),
        .vld_icm_b (vld_b4),
        .init_done (done4), .err_icm_a (err_a4), .err_icm_b (err_b4),
        .dup_a_cnt (dup_a4), .dup_b_cnt (dup_b4)
    );

    icm20602_model #(.WHO_ID(8'h12), .DATA_BASE(8'h41), .ODR_HZ(3960), .FROZEN(1)) u_a4 (
        .sclk(sclk4), .mosi(mosi4), .miso(miso4), .cs_n(cs_a4_n));
    // ICM-B 悬空：无模型

    //====================================================================
    // 场景 5（v0.8）：ICM-A 停发新数据（halt 注入）+ B 正常在线
    //   RETRY_MS/SAMPLE_TIMEOUT_MS 压缩：重试 50ms、超时 20ms
    //   （20 > 重试流程 ~5ms，健康侧不误判；50 > 超时，err 必先于
    //    下次重试置位）
    //====================================================================
    wire        sclk5, mosi5;
    tri         miso5;
    wire        cs_a5_n, cs_b5_n;
    wire signed [15:0] a5_ax, a5_ay, a5_az, a5_t, a5_gx, a5_gy, a5_gz;
    wire signed [15:0] b5_ax, b5_ay, b5_az, b5_t, b5_gx, b5_gy, b5_gz;
    wire        vld_a5, vld_b5, done5, err_a5, err_b5;
    wire [7:0]  wd_a5, wd_b5;
    reg         halt_a5 = 1'b0;     // 1 = A 采样停摆（运行时注入）

    sns_sync #(
        .CLK_FREQ   (CLK_FREQ),
        .SPI_DIV    (SPI_DIV_TEST),
        .SAMPLE_HZ  (8000),
        .POWERUP_MS (1),
        .RESET_MS   (1),
        .POSTINIT_MS(1),
        .RETRY_MS   (50),
        .SAMPLE_TIMEOUT_MS (20)
    ) dut5 (
        .clk (clk), .rst_n (rst_n),
        .spi_sclk (sclk5), .spi_mosi (mosi5), .spi_miso (miso5),
        .cs_icm_a_n (cs_a5_n), .cs_icm_b_n (cs_b5_n),
        .icm_a_ax (a5_ax), .icm_a_ay (a5_ay), .icm_a_az (a5_az),
        .icm_a_t (a5_t),  .icm_a_gx (a5_gx), .icm_a_gy (a5_gy), .icm_a_gz (a5_gz),
        .vld_icm_a (vld_a5),
        .icm_b_ax (b5_ax), .icm_b_ay (b5_ay), .icm_b_az (b5_az),
        .icm_b_t (b5_t),  .icm_b_gx (b5_gx), .icm_b_gy (b5_gy), .icm_b_gz (b5_gz),
        .vld_icm_b (vld_b5),
        .init_done (done5), .err_icm_a (err_a5), .err_icm_b (err_b5),
        .wd_a_cnt (wd_a5), .wd_b_cnt (wd_b5)
    );

    icm20602_model #(.WHO_ID(8'h12), .DATA_BASE(8'h51), .ODR_HZ(3960)) u_a5 (
        .sclk(sclk5), .mosi(mosi5), .miso(miso5), .cs_n(cs_a5_n), .halt(halt_a5));
    icm20602_model #(.WHO_ID(8'h12), .DATA_BASE(8'h61), .ODR_HZ(3980)) u_b5 (
        .sclk(sclk5), .mosi(mosi5), .miso(miso5), .cs_n(cs_b5_n));

    //====================================================================
    // 监测
    //====================================================================
    integer vld_a1_cnt = 0, vld_b1_cnt = 0;
    integer vld_a2_cnt = 0, vld_b2_cnt = 0;
    integer vld_a3_cnt = 0, vld_b3_cnt = 0;
    integer vld_a4_cnt = 0, vld_b4_cnt = 0;
    integer vld_a5_cnt = 0, vld_b5_cnt = 0;   // 场景5（v0.8 停发注入）
    integer vld_a5_snp = 0, vld_b5_snp = 0;   // 停发冻结断言快照
    integer tick_cnt   = 0;          // 场景1 采样节拍累计（dut1 层次引用）
    integer tick0 = 0, vld_a0 = 0, vld_b0 = 0, d0a_0 = 0, d0b_0 = 0;  // 窗口快照
    integer model_a0=0,model_b0=0;
    integer diff_d0a = 0, exp_d0a = 0;   // drdy0 计数校验中间量
    real t_a1_first = 0.0, t_b1_first = 0.0;

    // 样本序号跟踪（模型温度对 = 样本序号）：vld 时捕获
    reg [15:0] last_id_a = 16'hFFFF, last_id_b = 16'hFFFF;
    integer dup_a = 0, dup_b = 0;    // 重复序号（同一样本二次发射）——必须 0
    integer jump_a = 0, jump_b = 0;  // 跳号 ≥2（落地但未被发射的样本）——必须 0

    always @(posedge clk) begin
        if (dut1.sample_tick) tick_cnt = tick_cnt + 1;
        if (vld_a1) begin
            vld_a1_cnt = vld_a1_cnt + 1;
            if (vld_a1_cnt == 1) t_a1_first = $realtime;
            if (last_id_a != 16'hFFFF) begin
                if (a1_t == last_id_a)        dup_a  = dup_a  + 1;
                else if (a1_t != last_id_a + 16'd1) jump_a = jump_a + 1;
            end
            last_id_a = a1_t;
        end
        if (vld_b1) begin
            vld_b1_cnt = vld_b1_cnt + 1;
            if (vld_b1_cnt == 1) t_b1_first = $realtime;
            if (last_id_b != 16'hFFFF) begin
                if (b1_t == last_id_b)        dup_b  = dup_b  + 1;
                else if (b1_t != last_id_b + 16'd1) jump_b = jump_b + 1;
            end
            last_id_b = b1_t;
        end
        if (vld_a2)   vld_a2_cnt = vld_a2_cnt + 1;
        if (vld_b2)   vld_b2_cnt   = vld_b2_cnt + 1;
        if (vld_a3)   vld_a3_cnt = vld_a3_cnt + 1;
        if (vld_b3)   begin vld_b3_cnt = vld_b3_cnt + 1; end
        if (vld_a4)   vld_a4_cnt = vld_a4_cnt + 1;
        if (vld_b4)   vld_b4_cnt = vld_b4_cnt + 1;
        if (vld_a5)   vld_a5_cnt = vld_a5_cnt + 1;
        if (vld_b5)   vld_b5_cnt = vld_b5_cnt + 1;
    end

    //====================================================================
    // 场景 5 主流程（v0.8）：停发 → 超时置位 → 冻结 → 释放 → 重试自愈
    //   时间轴（相对 rst_n 释放，节拍读窗占空比使重试实效 ~60ms/次）：
    //   init ~6ms；16ms halt；37ms 超时置位 err_a；~65ms 首次重试
    //   （WHO 通过清 err，DRDY 仍 0 → ~85ms 再超时）；95ms 释放 halt；
    //   ~130ms 二次重试成功 → ~135ms 起 vld 恢复（检查点 170ms）。
    //====================================================================
    initial begin : s5_flow
        wait (done5 === 1'b1);
        #(10_000_000);                                  // t≈16ms：数据已流动
        check(vld_a5_cnt >= 20, "s5_a_streaming_before_stall");
        check(err_a5 === 1'b0, "s5_a_healthy_before_stall");
        check(err_b5 === 1'b0, "s5_b_healthy_before_stall");

        halt_a5 = 1'b1;                                 // 停发注入：DRDY 冻结 0
        #(25_000_000);                                  // t≈41ms：超时(20ms)已触发
        $display("s5 stall: err_a=%b wd_a=%0d vld_a=%0d (streaming was >=20)",
                 err_a5, wd_a5, vld_a5_cnt);
        check(err_a5 === 1'b1, "s5_err_a_set_on_timeout");   // 审核问题③核心断言
        check(wd_a5 >= 8'd1, "s5_wd_a_incremented");
        vld_a5_snp = vld_a5_cnt;
        vld_b5_snp = vld_b5_cnt;

        #(54_000_000);                                  // t≈95ms：停发持续中
        // 期间首次重试 WHO 通过、err 短暂清零、DRDY 仍 0 → 再次超时——
        // 整个停发窗口 vld_a 必须冻结（不得消费陈旧数据）
        check(vld_a5_cnt == vld_a5_snp, "s5_vld_a_frozen_during_stall");
        check(vld_b5_cnt > vld_b5_snp, "s5_b_keeps_flowing");
        check(err_b5 === 1'b0, "s5_b_never_err");       // 重试间隙不误判健康侧
        check(wd_b5 == 8'd0, "s5_b_no_watchdog");

        halt_a5 = 1'b0;                                 // 释放：等周期重试自愈
        #(75_000_000);                                  // t≈170ms：二次重试已成功
        $display("s5 recover: err_a=%b wd_a=%0d vld_a=%0d (frozen at %0d)",
                 err_a5, wd_a5, vld_a5_cnt, vld_a5_snp);
        check(err_a5 === 1'b0, "s5_err_a_cleared_by_retry");
        check(vld_a5_cnt >= vld_a5_snp + 10, "s5_vld_a_resumed");
        check(err_b5 === 1'b0, "s5_b_healthy_at_end");
    end

    //====================================================================
    // 主流程
    //====================================================================
    initial begin
        repeat (10) @(posedge clk);
        rst_n = 1'b1;

        // 初始化完成（POWERUP 1ms + A/B 各 ~2ms ≈ 5.5ms；场景2 少一次 WHO 复位流程；
        // 场景3 A 失败跳过其复位/初始化，B 正常 ~4.5ms）
        #(12_000_000);
        check(done1 === 1'b1, "s1_init_done");
        check(done2 === 1'b1, "s2_init_done");
        check(done3 === 1'b1, "s3_init_done");
        $display("init: s1 done=%b err_a=%b err_b=%b | s2 done=%b err_a=%b err_b=%b | s3 done=%b err_a=%b err_b=%b @%0t",
                 done1, err_a1, err_b1, done2, err_a2, err_b2, done3, err_a3, err_b3, $time);
        check(err_a1 === 1'b0, "s1_err_a");
        check(err_b1 === 1'b0, "s1_err_b");
        check(err_a2 === 1'b0, "s2_err_a");
        check(err_b2 === 1'b1, "s2_err_b_fault");
        check(err_a3 === 1'b1, "s3_err_a_fault");
        check(err_b3 === 1'b0, "s3_err_b");

        // 初始化寄存器写入校验（场景1，模型寄存器堆层次引用）
        check(u_a1.regs[8'h70] == 8'h40, "s1_A_I2C_IF");        // I2C_IF_DIS is register 0x70 bit 6
        check(u_a1.regs[8'h6B] == 8'h01, "s1_A_PWR_MGMT_1");     // 时钟+唤醒
        check(u_a1.regs[8'h6C] == 8'h07, "s1_A_PWR_MGMT_2");     // 陀螺 standby（v0.7）
        check(u_a1.regs[8'h19] == 8'h00, "s1_A_SMPLRT_DIV");
        check(u_a1.regs[8'h1A] == 8'h01, "s1_A_CONFIG");         // 陀螺 DLPF 176Hz
        check(u_a1.regs[8'h1C] == 8'h10, "s1_A_ACCEL_CFG");      // ±8g
        check(u_a1.regs[8'h1D] == 8'h08, "s1_A_ACCEL_CFG2");     // FCHOICE_B=1: 4kHz 档/BW 1046Hz（v0.7）
        check(u_a1.regs[8'h1B] == 8'h10, "s1_A_GYRO_CFG");       // ±1000dps
        check(u_a1.regs[8'h38] == 8'h01, "s1_A_INT_ENABLE");     // RAW_DATA_0_RDY_EN
        check(u_a1.regs[8'h37] == 8'h00, "s1_A_INT_PIN_CFG");    // INT_RD_CLEAR=0 显式锁定
        check(u_b1.regs[8'h37] == 8'h00, "s1_B_INT_PIN_CFG");
        check(u_a1.wr_count >= 11, "s1_A_wr_count");             // 复位 1 + 初始化 10

        // 采样数据（等 ~8ms：两侧各有发射）
        #(8_000_000);
        $display("vld counts: s1 A=%0d B=%0d | s2 A=%0d B=%0d | s3 A=%0d B=%0d",
                 vld_a1_cnt, vld_b1_cnt, vld_a2_cnt, vld_b2_cnt, vld_a3_cnt, vld_b3_cnt);
        check(vld_a1_cnt >= 3, "s1_vld_a");
        check(vld_b1_cnt >= 3, "s1_vld_b");
        check(vld_a2_cnt >= 3, "s2_vld_a_alive");
        check(vld_b2_cnt == 0, "s2_vld_b_silent");
        check(vld_a3_cnt == 0, "s3_vld_a_silent");
        check(vld_b3_cnt >= 3, "s3_vld_b_alive");

        // ICM 数据通路（A：0x0102..，B：0x1112..；场景3 B：0x3132..）
        // 温度对不再为固定样式（模型改为携带样本序号），门控窗口单独校验
        $display("s1 A: ax=%04x ay=%04x az=%04x t=%04x(sample#) gx=%04x gy=%04x gz=%04x",
                 a1_ax, a1_ay, a1_az, a1_t, a1_gx, a1_gy, a1_gz);
        $display("s1 B: ax=%04x ay=%04x az=%04x t=%04x(sample#) gx=%04x gy=%04x gz=%04x",
                 b1_ax, b1_ay, b1_az, b1_t, b1_gx, b1_gy, b1_gz);
        check(a1_ax == 16'sh0102 && a1_ay == 16'sh0304 && a1_az == 16'sh0506, "s1_A_accel");
        check(a1_gx == 16'sh090A && a1_gy == 16'sh0B0C && a1_gz == 16'sh0D0E, "s1_A_gyro");
        check(b1_ax == 16'sh1112 && b1_ay == 16'sh1314 && b1_az == 16'sh1516, "s1_B_accel");
        check(b1_gx == 16'sh191A && b1_gz == 16'sh1D1E, "s1_B_gyro");
        check(a2_ax == 16'sh2122 && a2_az == 16'sh2526 && a2_gz == 16'sh2D2E, "s2_A_data");
        check(b3_ax == 16'sh3132 && b3_az == 16'sh3536 && b3_gz == 16'sh3D3E, "s3_B_data");

        // A/B 读出间隔：两片 SPI 读出完成的时刻差（非同步精度指标——
        // 两片各自内部时钟自由采样，实际采样时刻差需台架实测）
        $display("A/B readout interval = %.1f us", (t_b1_first - t_a1_first) / 1000.0);
        check((t_b1_first - t_a1_first) < 100_000.0, "ab_readout_interval_100us");

        // 零丢样窗口（250ms；节拍 8kHz → 2000 拍；A ODR=3960 → ~990 样、
        // B ODR=3980 → ~995 样）：
        //   ① dup==0：DRDY 门控，无重复样本；
        //   ② jump==0：节拍 2 倍于 ODR，每个落地样本被恰好发射一次；
        //   ③ vld ≈ 250ms×ODR（A 988~990 / B 993~995）；
        //   ④ tick ≈ 2000；drdy0 == tick − vld（本拍无新样本的正常节拍）；
        //   ⑤ 诊断计数器与 TB 独立计数一致（seq/vld_cnt 自检）。
        //   vld 下界按 ODR 偏离标称 4kHz 的 1%（A）/0.5%（B）×窗口样本数放宽：
        //   A −12、B −8（上界 +3~4 覆盖窗口边界相位）。
        tick0 = tick_cnt; vld_a0 = vld_a1_cnt; vld_b0 = vld_b1_cnt;
        d0a_0 = d0a1; d0b_0 = d0b1;
        model_a0=u_a1.sample_id;model_b0=u_b1.sample_id;
        #(250_000_000);
        $display("zero-loss window: ticks=%0d | A vld=%0d dup=%0d jump=%0d last_id=%0d | B vld=%0d dup=%0d jump=%0d last_id=%0d",
                 tick_cnt - tick0,
                 vld_a1_cnt - vld_a0, dup_a, jump_a, last_id_a,
                 vld_b1_cnt - vld_b0, dup_b, jump_b, last_id_b);
        check(dup_a == 0, "s1_A_no_duplicate_sample");
        check(dup_b == 0, "s1_B_no_duplicate_sample");
        check(dup_a1 == 0, "s1_A_dup_cnt_zero");    // RTL dup 计数器自检（TB 独立判据旁证）
        check(dup_b1 == 0, "s1_B_dup_cnt_zero");
        check(jump_a == 0, "s1_A_no_lost_sample");
        check(jump_b == 0, "s1_B_no_lost_sample");
        check(tick_cnt - tick0 >= 1998 && tick_cnt - tick0 <= 2002, "s1_tick_8khz");
        // The model defers sample loading during CS, so its actual ODR can
        // be slightly lower at a slower simulated SCLK. Match the project's
        // 4k +/-3% frame contract AND independently count samples produced by
        // each model. No-duplicate/no-jump checks above remain exact.
        check(vld_a1_cnt-vld_a0 >= (tick_cnt-tick0)*97/200 &&
              vld_a1_cnt-vld_a0 <= (tick_cnt-tick0)*103/200, "s1_A_vld_matches_odr");
        check(vld_b1_cnt-vld_b0 >= (tick_cnt-tick0)*97/200 &&
              vld_b1_cnt-vld_b0 <= (tick_cnt-tick0)*103/200, "s1_B_vld_matches_odr");
        check(vld_a1_cnt-vld_a0 >= u_a1.sample_id-model_a0-1 &&
              vld_a1_cnt-vld_a0 <= u_a1.sample_id-model_a0+1,"s1_A_matches_model_produced");
        check(vld_b1_cnt-vld_b0 >= u_b1.sample_id-model_b0-1 &&
              vld_b1_cnt-vld_b0 <= u_b1.sample_id-model_b0+1,"s1_B_matches_model_produced");
        check(vld_a1_cnt - vld_a0 < tick_cnt - tick0 - 2, "s1_A_gating_active");
        diff_d0a = d0a1 - d0a_0;
        exp_d0a  = (tick_cnt - tick0) - (vld_a1_cnt - vld_a0);
        check(diff_d0a >= exp_d0a - 1 && diff_d0a <= exp_d0a + 1, "s1_A_drdy0_counter");
        check(err_a1 === 1'b0 && err_b1 === 1'b0, "s1_no_runtime_err");

        // 场景4：冻结输出注入——dup 计数器负向检出（首样本外每 vld 一次）
        $display("s4 frozen-inject: A vld=%0d dup=%0d | B vld=%0d dup=%0d err_b=%b",
                 vld_a4_cnt, dup_a4, vld_b4_cnt, dup_b4, err_b4);
        check(done4 === 1'b1, "s4_init_done");
        check(err_a4 === 1'b0, "s4_err_a");
        check(err_b4 === 1'b1, "s4_err_b_fault");
        check(vld_a4_cnt >= 101, "s4_vld_a_frozen_stream");
        check(vld_b4_cnt == 0, "s4_vld_b_silent");
        check(dup_a4 == vld_a4_cnt - 1, "s4_dup_a_exact");
        check(dup_a4 >= 100, "s4_dup_a_accumulates");
        check(dup_b4 == 0, "s4_dup_b_zero");

        // 诊断计数器自检（模块输出 vs TB 独立计数；uint16 回绕取模比较）
        check(seq_a1 == (vld_a1_cnt % 65536), "s1_seq_a_counter");
        check(seq_b1 == (vld_b1_cnt % 65536), "s1_seq_b_counter");
        check(vlca1 == (vld_a1_cnt % 65536), "s1_vld_a_counter");
        check(vlcb1 == (vld_b1_cnt % 65536), "s1_vld_b_counter");
        check(tick1 == (tick_cnt % 65536), "s1_tick_counter");
        check(wda1 == 8'd0 && wdb1 == 8'd0, "s1_no_watchdog");

        if (errors == 0) begin
            $display("tb_sns_sync: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_sns_sync: %0d ERRORS", errors);
        end
    end

    // 超时保护（主流程 ~270ms、场景5 ~170ms 均在窗口内；挂起则 $fatal(2)）
    initial begin
        #350_000_000;
        $fatal(2, "tb_sns_sync: TIMEOUT — errors=%0d", errors);
    end
endmodule
