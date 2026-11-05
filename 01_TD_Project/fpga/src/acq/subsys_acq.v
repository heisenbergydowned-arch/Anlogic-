// Cabinet cooling acquisition + FCB1 control, v0.9 (2026-10-07).
// Sensors retain their original 100MHz drivers. src/control adds cause-based
// protection, PI, arbitration, local sound/light and CRC16 UART registers.
// Default is unqualified BENCH (legacy 50% output), never certified AUTO.
// KEY1: leased local duty; zero requires stop permission. KEY2 short: silence;
// hold 2s: local fault-reset request + temporary configuration permission.
// Green indicates qualified stable RUN, not merely an ICM WHO_AM_I response.
// Optional full 39D windows, PS AXI transport and WAV1 fault capture are integrated.
// See src/control/README.md for units, configuration, interfaces and validation.
module subsys_acq #(
    parameter POR_BITS=20,
    parameter ACQ_CLK_HZ=100000000,
    parameter ENABLE_PS_LINK=0, ENABLE_FEATURES=0, LINK_TEST_MODE=0,
    parameter ENABLE_SDP810=1,
    parameter ENV_MAX_AGE_MS=2500,
    parameter DS_CONV_MS   = 800,   // DS18B20 转换等待（12 位最长 750ms；仿真压缩为 1）
    parameter FG_SPINUP_MS = 2000,  // 风扇 0%→非0% 起转宽限（期间不判停转）
    parameter CONTROL_BENCH_ENABLE = 1, // unqualified bench output, not AUTO
    parameter GRACE_MS     = 4000   // 上电传感器慢启动宽限（期间温湿压/FG 不计入告警）
)(
    input  wire I_sysclk,          // 100MHz 板载晶振

    // J12 GPIO 排针 —— SPI 传感器总线（ICM-20602×2，Mode0）
    output wire O_spi_sclk,
    output wire O_spi_mosi,
    input  wire I_spi_miso,
    output wire O_cs_icm_a,
    output wire O_cs_icm_b,

    // J12 —— AD7606 串行接口（独立 SCLK 12.5MHz，单线 DOUTA）
    output wire O_adc_convst,     // 启动转换脉冲
    output wire O_adc_sclk,
    output wire O_adc_reset,
    input  wire I_adc_douta,      // 串行数据 V1→V8（MSB first）
    output wire O_adc_cs,         // 读窗口（低有效）
    input  wire I_adc_busy,       // 转换进行中
    input  wire I_adc_frstdata,   // 首通道指示

    // J12 —— 数字传感器 / 执行
    inout  wire IO_j12_19_reserved,
    inout  wire IO_temp_core_dq,
    inout  wire IO_i2c_sda_ext,   // AHT20+BMP280 I2C SDA（0x38/0x76，模块自带上拉）
    inout  wire IO_i2c_scl_ext,   // AHT20+BMP280 I2C SCL
    input  wire I_fan_fg,         // 风扇 FG（外部 10kΩ 上拉）
    inout wire IO_j12_22_reserved,
    output wire O_fan_pwm,        // 风扇 PWM（20kHz）
    output wire O_buzzer_en,      // FCB1 local L2/L3 alarm output
    output wire O_led_grn,        // qualified, stable automatic control
    output wire O_led_red,        // 外接红灯 = 告警

    // 板载固定资源
    output wire O_rs485_tx,       // RS485 framed alarm/register transport
    input  wire I_rs485_rx,
    output wire O_rs485_de,
    output wire O_led3_hb,        // 心跳
    output wire O_led4_alm,       // 告警
    input  wire I_key1,           // local manual override (leased)
    input  wire I_key2,           // short silence / hold local reset+maintenance
    output wire O_pl_uart_tx,     // PL 调试串口（dbg_uart 115200 快照帧）
    input  wire I_pl_uart_rx,
    inout  wire IO_iic_sda,       // 板载 EEPROM/RTC（本版释放）
    inout  wire IO_iic_scl,
    output wire O_led1,           // ~1.5Hz 慢闪
    output wire O_led2,
    input wire edge_clk,edge_rst_n,
    input wire [15:0] edge_awaddr,
    input wire edge_awvalid,
    output wire edge_awready,
    input wire [31:0] edge_wdata,
    input wire [3:0] edge_wstrb,
    input wire edge_wvalid,
    output wire edge_wready,
    output wire [1:0] edge_bresp,
    output wire edge_bvalid,
    input wire edge_bready,
    input wire [15:0] edge_araddr,
    input wire edge_arvalid,
    output wire edge_arready,
    output wire [31:0] edge_rdata,
    output wire [1:0] edge_rresp,
    output wire edge_rvalid,
    input wire edge_rready
);
    localparam [31:0] FW_VERSION = 32'h2026_1146;

    //====================================================================
    // 时钟与上电复位（FPGA 配置后寄存器初值有效）
    // sys_rst_n 打一拍再分发：释放与 clk 上升沿对齐（异步复位、同步释放），
    // 各子模块异步复位与顶层同步复位见到的是同一个寄存器化信号
    //====================================================================
    wire clk = I_sysclk;

    reg [POR_BITS-1:0] por_cnt = 0;
    always @(posedge clk) begin
        if (!(&por_cnt)) por_cnt <= por_cnt + 1'b1;
    end
    reg sys_rst_n = 1'b0;
    always @(posedge clk) sys_rst_n <= &por_cnt;   // ~10ms

    //====================================================================
    // sns_sync — ICM-20602×2 振动采集
    //====================================================================
    wire        cs_icm_a_n, cs_icm_b_n;
    wire        spi_sclk_w, spi_mosi_w;
    wire signed [15:0] a_ax, a_ay, a_az, a_t, a_gx, a_gy, a_gz;
    wire signed [15:0] b_ax, b_ay, b_az, b_t, b_gx, b_gy, b_gz;
    wire        vld_icm_a, vld_icm_b, sns_init_done, sns_err_a, sns_err_b;
    wire [15:0] sns_seq_a, sns_seq_b, sns_tick, sns_vld_a, sns_vld_b;
    wire [15:0] sns_drdy0_a, sns_drdy0_b;
    wire [7:0]  sns_wd_a, sns_wd_b;
    wire [15:0] sns_dup_a, sns_dup_b;
    wire [7:0] sns_who_a, sns_who_b, sns_status_a, sns_status_b;
    wire [9:0] sns_config_bad_a, sns_config_bad_b;
    wire [23:0] sns_config_failure_a, sns_config_failure_b;
    wire [15:0] sns_retries_a, sns_retries_b;
    wire [31:0] sns_diagnostic_state;

    assign O_spi_sclk = spi_sclk_w;
    assign O_spi_mosi = spi_mosi_w;

    sns_sync #(
        .CLK_FREQ    (ACQ_CLK_HZ),
        .SAMPLE_HZ   (8000),         // 8kHz 节拍 > ODR 4kHz：零丢样（论证见 sns_sync 头注释）
        .SPI_DIV     (8),
        .REGISTER_SPI_DIV (50),
        .STATUS_SPI_DIV (25),
        .ACCEPT_WHO_2E (1)
    ) u_sns (
        .clk         (clk),
        .rst_n       (sys_rst_n),
        .spi_sclk    (spi_sclk_w),
        .spi_mosi    (spi_mosi_w),
        .spi_miso    (I_spi_miso),
        .cs_icm_a_n  (cs_icm_a_n),
        .cs_icm_b_n  (cs_icm_b_n),
        .icm_a_ax    (a_ax), .icm_a_ay (a_ay), .icm_a_az (a_az),
        .icm_a_t     (a_t),  .icm_a_gx (a_gx), .icm_a_gy (a_gy), .icm_a_gz (a_gz),
        .vld_icm_a   (vld_icm_a),
        .icm_b_ax    (b_ax), .icm_b_ay (b_ay), .icm_b_az (b_az),
        .icm_b_t     (b_t),  .icm_b_gx (b_gx), .icm_b_gy (b_gy), .icm_b_gz (b_gz),
        .vld_icm_b   (vld_icm_b),
        .init_done   (sns_init_done),
        .err_icm_a   (sns_err_a),
        .err_icm_b   (sns_err_b),
        .seq_a       (sns_seq_a),
        .seq_b       (sns_seq_b),
        .tick_cnt    (sns_tick),
        .vld_a_cnt   (sns_vld_a),
        .vld_b_cnt   (sns_vld_b),
        .drdy0_a_cnt (sns_drdy0_a),
        .drdy0_b_cnt (sns_drdy0_b),
        .wd_a_cnt    (sns_wd_a),
        .wd_b_cnt    (sns_wd_b),
        .dup_a_cnt   (sns_dup_a),
        .dup_b_cnt   (sns_dup_b),
        .who_a(sns_who_a),.who_b(sns_who_b),
        .config_bad_a(sns_config_bad_a),.config_bad_b(sns_config_bad_b),
        .config_failure_a(sns_config_failure_a),.config_failure_b(sns_config_failure_b),
        .status_a(sns_status_a),.status_b(sns_status_b),
        .retries_a(sns_retries_a),.retries_b(sns_retries_b),
        .diagnostic_state(sns_diagnostic_state)
    );

    assign O_cs_icm_a = cs_icm_a_n;
    assign O_cs_icm_b = cs_icm_b_n;

    //====================================================================
    // ads7606_if — AD7606 8 通道同步采样（电流/压差/电压等模拟量）
    //====================================================================
    wire signed [15:0] adc_ch1, adc_ch2, adc_ch3, adc_ch4;
    wire signed [15:0] adc_ch5, adc_ch6, adc_ch7, adc_ch8;
    wire        vld_adc, err_adc;

    ads7606_if #(
        .CLK_FREQ  (ACQ_CLK_HZ),
        .SAMPLE_HZ (50_000),       // 每通道 50kSPS
        .SCLK_DIV  (4)             // SCLK = 12.5MHz（≤17MHz）
    ) u_adc (
        .clk         (clk),
        .rst_n       (sys_rst_n),
        .o_reset     (O_adc_reset),
        .o_convst    (O_adc_convst),
        .i_busy      (I_adc_busy),
        .o_sclk      (O_adc_sclk),
        .i_douta     (I_adc_douta),
        .o_cs_n      (O_adc_cs),
        .i_frstdata  (I_adc_frstdata),
        .ch1_code    (adc_ch1),
        .ch2_code    (adc_ch2),
        .ch3_code    (adc_ch3),
        .ch4_code    (adc_ch4),
        .ch5_code    (adc_ch5),
        .ch6_code    (adc_ch6),
        .ch7_code    (adc_ch7),
        .ch8_code    (adc_ch8),
        .vld         (vld_adc),
        .err         (err_adc)
    );

    //====================================================================
    // S4b is the only DS18B20; the inlet source is AHT20.
    //====================================================================
    wire signed [15:0] inlet_aht_raw, temp_core_raw;
    wire        inlet_aht_vld, temp_core_vld;
    wire        inlet_aht_present, temp_core_present;
    wire        inlet_aht_stale, temp_core_stale;
    wire        temp_core_short;
    assign IO_j12_19_reserved = 1'bz;

    ds18b20 #(
        .CLK_FREQ  (ACQ_CLK_HZ),
        .CONV_MS   (DS_CONV_MS),
        .PERIOD_MS (1000)
    ) u_ds18b20_core (
        .clk        (clk),
        .rst_n      (sys_rst_n),
        .dq         (IO_temp_core_dq),
        .temperature(temp_core_raw),
        .vld        (temp_core_vld),
        .present    (temp_core_present),
        .stale      (temp_core_stale),
        .bus_short  (temp_core_short)
    );

    //====================================================================
    // i2c_master + 仲裁 — AHT20（0x38）/ BMP280（0x76）共享外部 I2C
    //====================================================================
    wire        aht_req, bmp_req;
    wire [6:0]  aht_dev, bmp_dev;
    wire [2:0]  aht_nwr, bmp_nwr;
    wire [7:0]  aht_wr0, aht_wr1, aht_wr2;
    wire [7:0]  bmp_wr0, bmp_wr1, bmp_wr2;
    wire [4:0]  aht_nrd, bmp_nrd;
    wire        m_ack, m_err, m_rd_valid;
    wire [7:0]  m_rd_data;
    wire [4:0]  m_rd_idx;

    wire sdp_req;
    wire [6:0] sdp_dev;
    wire [2:0] sdp_nwr;
    wire [7:0] sdp_wr0,sdp_wr1,sdp_wr2;
    wire [4:0] sdp_nrd;
    wire sdp_sample_valid,sdp_present,sdp_err,sdp_stale;
    wire signed [15:0] sdp_pressure_raw,sdp_temperature_raw;
    wire [15:0] sdp_scale_factor;
    wire [31:0] sdp_age_ms,sdp_product_number;
    wire [63:0] sdp_serial_number;
    wire [7:0] sdp_error_code;
    wire req_gnt,i2c_reset_n;
    wire [6:0] master_dev;
    wire [2:0] master_nwr;
    wire [7:0] master_wr0,master_wr1,master_wr2;
    wire [4:0] master_nrd;
    wire [2:0] client_ack,client_err,client_read_valid;

    i2c_arbiter3 #(.CLK_FREQ(ACQ_CLK_HZ)) u_i2c_arbiter(
        .clk(clk),.rst_n(sys_rst_n),.requests({sdp_req,bmp_req,aht_req}),
        .devices({sdp_dev,bmp_dev,aht_dev}),.write_counts({sdp_nwr,bmp_nwr,aht_nwr}),
        .write_byte0({sdp_wr0,bmp_wr0,aht_wr0}),.write_byte1({sdp_wr1,bmp_wr1,aht_wr1}),
        .write_byte2({sdp_wr2,bmp_wr2,aht_wr2}),.read_counts({sdp_nrd,bmp_nrd,aht_nrd}),
        .master_req(req_gnt),.master_dev(master_dev),.master_nwr(master_nwr),
        .master_wr0(master_wr0),.master_wr1(master_wr1),.master_wr2(master_wr2),.master_nrd(master_nrd),
        .master_ack(m_ack),.master_err(m_err),.master_rd_valid(m_rd_valid),
        .acknowledgements(client_ack),.errors(client_err),.read_valid(client_read_valid),.master_reset_n(i2c_reset_n));

    generate if(ENABLE_SDP810)begin:g_sdp810
        sdp810_drv #(.CLK_FREQ(ACQ_CLK_HZ)) driver(
            .clk(clk),.rst_n(sys_rst_n),.i2c_req(sdp_req),.i2c_dev(sdp_dev),.i2c_nwr(sdp_nwr),
            .i2c_wr0(sdp_wr0),.i2c_wr1(sdp_wr1),.i2c_wr2(sdp_wr2),.i2c_nrd(sdp_nrd),
            .i2c_ack(client_ack[2]),.i2c_err(client_err[2]),.i2c_rd_valid(client_read_valid[2]),
            .i2c_rd_data(m_rd_data),.i2c_rd_idx(m_rd_idx),.sample_valid(sdp_sample_valid),
            .pressure_raw(sdp_pressure_raw),.temperature_raw(sdp_temperature_raw),.scale_factor(sdp_scale_factor),
            .product_number(sdp_product_number),.serial_number(sdp_serial_number),
            .present(sdp_present),.err(sdp_err),.stale(sdp_stale),.age_ms(sdp_age_ms),.error_code(sdp_error_code));
    end else begin:g_analog_pressure
        assign sdp_req=0;assign sdp_dev=0;assign sdp_nwr=0;assign sdp_wr0=0;assign sdp_wr1=0;assign sdp_wr2=0;assign sdp_nrd=0;
        assign sdp_sample_valid=0;assign sdp_pressure_raw=0;assign sdp_temperature_raw=0;assign sdp_scale_factor=0;
        assign sdp_product_number=0;assign sdp_serial_number=0;assign sdp_present=0;assign sdp_err=1;assign sdp_stale=1;
        assign sdp_age_ms=32'hffffffff;assign sdp_error_code=0;
    end endgenerate
    wire pressure_sample_new=ENABLE_SDP810 ? sdp_sample_valid:vld_adc;
    wire pressure_sample_bad=ENABLE_SDP810 ? (!sdp_present || sdp_err || sdp_stale):err_adc;
    wire signed [15:0] pressure_sample_raw=ENABLE_SDP810 ? sdp_pressure_raw:adc_ch2;

    i2c_master #(
        .CLK_FREQ   (ACQ_CLK_HZ),
        .I2C_FREQ   (400_000),
        .STRETCH_US (5_000)
    ) u_i2c (
        .clk        (clk),
        .rst_n      (sys_rst_n && i2c_reset_n),
        .io_sda     (IO_i2c_sda_ext),
        .io_scl     (IO_i2c_scl_ext),
        .u_req      (req_gnt),
        .u_dev      (master_dev),
        .u_nwr      (master_nwr),
        .u_wr0      (master_wr0),
        .u_wr1      (master_wr1),
        .u_wr2      (master_wr2),
        .u_nrd      (master_nrd),
        .u_ack      (m_ack),
        .u_err      (m_err),
        .u_rd_valid (m_rd_valid),
        .u_rd_data  (m_rd_data),
        .u_rd_idx   (m_rd_idx)
    );

    wire aht_ack = client_ack[0];
    wire bmp_ack = client_ack[1];

    wire        aht_busy, aht_present, aht_err, aht_sample_valid;
    wire [19:0] aht_hum_code, aht_temp_code;
    aht20_drv #(
        .CLK_FREQ  (ACQ_CLK_HZ),
        .PERIOD_MS (1000),
        .MEAS_MS   (80)
    ) u_aht20 (
        .clk         (clk),
        .rst_n       (sys_rst_n),
        .i2c_req     (aht_req),
        .i2c_dev     (aht_dev),
        .i2c_nwr     (aht_nwr),
        .i2c_wr0     (aht_wr0),
        .i2c_wr1     (aht_wr1),
        .i2c_wr2     (aht_wr2),
        .i2c_nrd     (aht_nrd),
        .i2c_ack     (aht_ack),
        .i2c_err     (client_err[0]),
        .i2c_rd_valid(client_read_valid[0]),
        .i2c_rd_data (m_rd_data),
        .i2c_rd_idx  (m_rd_idx),
        .busy        (aht_busy),
        .hum_code    (aht_hum_code),
        .temp_code   (aht_temp_code),
        .present     (aht_present),
        .err         (aht_err),
        .sample_valid(aht_sample_valid)
    );

    wire         bmp_busy, bmp_present, bmp_err, bmp_sample_valid;
    wire [7:0]   bmp_chip_id;
    wire [191:0] bmp_cal_regs;
    wire [19:0]  bmp_t_raw, bmp_p_raw;
    bmp280_drv #(
        .CLK_FREQ  (ACQ_CLK_HZ),
        .PERIOD_MS (1000),
        .MEAS_MS   (10)
    ) u_bmp280 (
        .clk         (clk),
        .rst_n       (sys_rst_n),
        .i2c_req     (bmp_req),
        .i2c_dev     (bmp_dev),
        .i2c_nwr     (bmp_nwr),
        .i2c_wr0     (bmp_wr0),
        .i2c_wr1     (bmp_wr1),
        .i2c_wr2     (bmp_wr2),
        .i2c_nrd     (bmp_nrd),
        .i2c_ack     (bmp_ack),
        .i2c_err     (client_err[1]),
        .i2c_rd_valid(client_read_valid[1]),
        .i2c_rd_data (m_rd_data),
        .i2c_rd_idx  (m_rd_idx),
        .busy        (bmp_busy),
        .chip_id     (bmp_chip_id),
        .cal_regs    (bmp_cal_regs),
        .t_raw       (bmp_t_raw),
        .p_raw       (bmp_p_raw),
        .present     (bmp_present),
        .err         (bmp_err),
        .sample_valid(bmp_sample_valid)
    );

    //====================================================================
    // fg_cap — 风扇转速反馈
    //====================================================================
    wire [31:0] fg_period, fg_pcount;
    wire        fg_vld, fg_timeout;
    fg_cap #(
        .CLK_FREQ   (ACQ_CLK_HZ),
        .GLITCH_US  (20),
        .TIMEOUT_US (400_000)     // 卡死门限 250rpm(2 脉冲/转≈120ms) 的 ~3.3 倍
    ) u_fg (
        .clk        (clk),
        .rst_n      (sys_rst_n),
        .fg         (I_fan_fg),
        .period_cnt (fg_period),
        .vld        (fg_vld),
        .pulse_count(fg_pcount),
        .timeout    (fg_timeout)
    );

    //====================================================================
    // Independent control/protection, with FCB1 UART register transport.
    //====================================================================
    wire [15:0] fan_duty;
    wire uart_req,uart_write,uart_response;wire [15:0] uart_address;wire [31:0] uart_wdata,uart_rdata;wire [7:0] uart_error;
    wire control_req, control_write, control_response;
    wire [15:0] control_address;
    wire [31:0] control_wdata, control_rdata;
    wire [7:0] control_error;
    wire ctrl_tx, ctrl_tx_active, dbg_tx, dbg_busy, dbg_holdoff;
    wire [31:0] bad_control_frames, dropped_control_frames;
    wire manual_step, local_silence, local_reset, local_permit;
    wire initial_config_permit;
    wire ctrl_tick;
    wire [31:0] button_time;
    cooling_tick #(.CLK_FREQ(ACQ_CLK_HZ)) u_button_tick(
        .clk(clk),.rst_n(sys_rst_n),.tick_ms(ctrl_tick),.now_ms(button_time));
    cooling_buttons u_buttons(.clk(clk),.rst_n(sys_rst_n),.tick_ms(ctrl_tick),
        .key1_n(I_key1),.key2_n(I_key2),.manual_step(manual_step),
        .local_silence(local_silence),.local_reset(local_reset),.local_permit(local_permit));
    cooling_uart #(.CLK_FREQ(ACQ_CLK_HZ)) u_control_uart(.clk(clk),.rst_n(sys_rst_n),.rx(I_pl_uart_rx),.dbg_busy(dbg_busy),
        .dbg_holdoff(dbg_holdoff),.tx(ctrl_tx),.tx_active(ctrl_tx_active),
        .req(uart_req),.write_en(uart_write),.address(uart_address),.write_data(uart_wdata),
        .response(uart_response),.read_data(uart_rdata),.error(uart_error),
        .bad_frames(bad_control_frames),.busy_drops(dropped_control_frames));
    assign O_pl_uart_tx=ctrl_tx_active ? ctrl_tx:dbg_tx;
    wire [31:0] control_active, control_latched;
    wire [1:0] control_level;
    wire [2:0] control_fan_action;
    wire [3:0] control_mode;
    wire control_stable, control_inhibit, control_red_flash, control_red_on;
    assign IO_j12_22_reserved = 1'bz;
    wire [767:0] control_config;
    wire [1023:0] control_monitor;wire [31:0] rs485_bad;
    wire [255:0] rs485_holding;
    assign rs485_holding={control_monitor[29*32+:16],control_monitor[28*32+:16],control_monitor[16*32+:16],control_monitor[15*32+:16],control_monitor[18*32+:32],control_monitor[21*32+:32],control_monitor[23*32+:16],control_monitor[8*32+:16],control_monitor[7*32+:16],control_monitor[2*32+:16],control_latched,control_active};
    edge_rs485 #(.CLK_HZ(ACQ_CLK_HZ)) rs485(.clk(clk),.rst_n(sys_rst_n),.rx(I_rs485_rx),.holding(rs485_holding),.tx(O_rs485_tx),.de(O_rs485_de),.bad_frames(rs485_bad));
    // EDGE_LINK_ACQ_BEGIN
    wire ps_req,ps_write,ps_response;wire [15:0] ps_address;wire [31:0] ps_wdata,ps_rdata;wire [7:0] ps_error;
    wire csr_req,csr_write,csr_response;wire [15:0] csr_address;wire [31:0] csr_wdata,csr_rdata;wire [7:0] csr_error;
    wire feature_response,wave_response,environment_response;
    wire [31:0] feature_rdata,wave_rdata,environment_rdata;
    wire [7:0] feature_error,wave_error,environment_error;
    wire environment_select=csr_address>=16'h3000 && csr_address<16'h3100;
    wire icm_select=csr_address>=16'h3100 && csr_address<16'h3200;
    reg icm_response,icm_request_seen;
    reg [31:0] icm_rdata,icm_snapshot_id;
    reg [7:0] icm_error;
    reg [1151:0] icm_snapshot;
    reg [63:0] icm_time,icm_last_a,icm_last_b;
    wire [31:0] icm_flags={28'd0,(LINK_TEST_MODE!=0),sns_init_done,sns_err_b,sns_err_a};
    localparam [31:0] ICM_CORE_HZ=ACQ_CLK_HZ;
    localparam [31:0] ICM_BURST_HZ=ACQ_CLK_HZ/32;
    localparam [31:0] ICM_REGISTER_HZ=ACQ_CLK_HZ/200;
    localparam [31:0] ICM_STATUS_HZ=ACQ_CLK_HZ/100;
    wire [1151:0] icm_live={ICM_STATUS_HZ,32'd45,8'd0,sns_config_failure_b,8'd0,sns_config_failure_a,
        icm_last_b,icm_last_a,
        16'd0,b_gz,b_gy,b_gx,b_t,b_az,b_ay,b_ax,
        16'd0,a_gz,a_gy,a_gx,a_t,a_az,a_ay,a_ax,
        sns_retries_b,sns_retries_a,16'd0,sns_status_b,sns_status_a,sns_diagnostic_state,
        6'd0,sns_config_bad_b,6'd0,sns_config_bad_a,16'd0,sns_who_b,sns_who_a,
        sns_dup_b,sns_dup_a,16'd0,sns_wd_b,sns_wd_a,sns_drdy0_b,sns_drdy0_a,
        sns_vld_b,sns_vld_a,sns_seq_b,sns_seq_a,
        ICM_REGISTER_HZ,ICM_BURST_HZ,32'd8000,ICM_CORE_HZ,icm_time,icm_flags,
        icm_snapshot_id+32'd1,32'h00020000,32'h49434d31};
    always @(posedge clk or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            icm_time<=0; icm_last_a<=0; icm_last_b<=0;
            icm_snapshot<=0; icm_snapshot_id<=0; icm_response<=0;
            icm_request_seen<=0; icm_rdata<=0; icm_error<=0;
        end else begin
            icm_time<=icm_time+1'b1;
            if (vld_icm_a) icm_last_a<=icm_time;
            if (vld_icm_b) icm_last_b<=icm_time;
            icm_response<=0;
            if (!csr_req || !icm_select) icm_request_seen<=0;
            if (csr_req && icm_select && !icm_request_seen) begin
                icm_request_seen<=1; icm_response<=1; icm_rdata<=0; icm_error<=0;
                if (csr_write || csr_address[1:0]!=0 || csr_address>16'h3190) icm_error<=8'h02;
                else if (csr_address==16'h3100) begin
                    icm_snapshot<=icm_live; icm_snapshot_id<=icm_snapshot_id+1'b1; icm_rdata<=32'h49434d31;
                end else if (csr_address==16'h3190) icm_rdata<=FW_VERSION;
                else icm_rdata<=icm_snapshot[csr_address[7:2]*32+:32];
            end
        end
    end
    wire environment_aht_valid,environment_bmp_valid,environment_auxiliary_bad,environment_bmp_stale;
    edge_environment #(.MAX_AGE_MS(ENV_MAX_AGE_MS), .REQUIRE_BMP280(1'b0)) environment(
        .clk(clk),.rst_n(sys_rst_n),.now_ms(button_time),
        .aht_new(aht_sample_valid),.aht_present(aht_present),.aht_error(aht_err),
        .aht_temperature(aht_temp_code),.aht_humidity(aht_hum_code),
        .bmp_new(bmp_sample_valid),.bmp_present(bmp_present),.bmp_error(bmp_err),
        .bmp_temperature(bmp_t_raw),.bmp_pressure(bmp_p_raw),.bmp_calibration(bmp_cal_regs),
        .aht_valid(environment_aht_valid),.bmp_valid(environment_bmp_valid),
        .auxiliary_bad(environment_auxiliary_bad),.aht_stale(inlet_aht_stale),.bmp_stale(environment_bmp_stale),
        .req(csr_req && environment_select),.write_en(csr_write),.address(csr_address),
        .response(environment_response),.read_data(environment_rdata),.error(environment_error));
    wire [31:0] inlet_scaled = ({12'd0,aht_temp_code}<<11)+({12'd0,aht_temp_code}<<10)+({12'd0,aht_temp_code}<<7)+32'd524288;
    assign inlet_aht_raw = $signed({4'd0,inlet_scaled[31:20]})-16'sd800;
    assign inlet_aht_vld = aht_sample_valid;
    assign inlet_aht_present = environment_aht_valid;
    wire wave_select=csr_address>=16'h2000 && csr_address<16'h3000;
    assign control_req=csr_req && csr_address<16'h1000;
    assign control_write=csr_write;assign control_address=csr_address;assign control_wdata=csr_wdata;
    assign csr_response=control_response || feature_response || wave_response || environment_response || icm_response;
    assign csr_rdata=icm_response ? icm_rdata:(environment_response ? environment_rdata:(wave_response ? wave_rdata:(feature_response ? feature_rdata:control_rdata)));
    assign csr_error=icm_response ? icm_error:(environment_response ? environment_error:(wave_response ? wave_error:(feature_response ? feature_error:control_error)));
    generate if(ENABLE_PS_LINK)begin:g_ps_link
        wire ac_req,ac_write,ac_response;wire [15:0] ac_address;wire [31:0] ac_wdata,ac_rdata;wire [7:0] ac_error;
        cooling_axi_lite adapter(.clk(edge_clk),.rst_n(edge_rst_n),
            .awaddr(edge_awaddr),
            .awvalid(edge_awvalid),
            .awready(edge_awready),
            .wdata(edge_wdata),
            .wstrb(edge_wstrb),
            .wvalid(edge_wvalid),
            .wready(edge_wready),
            .bresp(edge_bresp),
            .bvalid(edge_bvalid),
            .bready(edge_bready),
            .araddr(edge_araddr),
            .arvalid(edge_arvalid),
            .arready(edge_arready),
            .rdata(edge_rdata),
            .rresp(edge_rresp),
            .rvalid(edge_rvalid),
            .rready(edge_rready),
            .req(ac_req),.write_en(ac_write),.address(ac_address),.write_data(ac_wdata),
            .response(ac_response),.read_data(ac_rdata),.error(ac_error));
        edge_csr_cdc cdc(.s_clk(edge_clk),.s_rst_n(edge_rst_n),.s_req(ac_req),.s_write(ac_write),.s_address(ac_address),.s_wdata(ac_wdata),
            .s_response(ac_response),.s_rdata(ac_rdata),.s_error(ac_error),.d_clk(clk),.d_rst_n(sys_rst_n),
            .d_req(ps_req),.d_write(ps_write),.d_address(ps_address),.d_wdata(ps_wdata),.d_response(ps_response),.d_rdata(ps_rdata),.d_error(ps_error));
    end else begin:g_no_ps_link
        assign ps_req=0;assign ps_write=0;assign ps_address=0;assign ps_wdata=0;
        assign edge_awready=0;assign edge_wready=0;assign edge_bresp=2;assign edge_bvalid=0;
        assign edge_arready=0;assign edge_rdata=0;assign edge_rresp=2;assign edge_rvalid=0;
    end endgenerate
    edge_csr_mux csr_mux(.clk(clk),.rst_n(sys_rst_n),
        .a_req(uart_req),.a_write(uart_write),.a_address(uart_address),.a_wdata(uart_wdata),.a_response(uart_response),.a_rdata(uart_rdata),.a_error(uart_error),
        .b_req(ps_req),.b_write(ps_write),.b_address(ps_address),.b_wdata(ps_wdata),.b_response(ps_response),.b_rdata(ps_rdata),.b_error(ps_error),
        .req(csr_req),.write_en(csr_write),.address(csr_address),.wdata(csr_wdata),.response(csr_response),.rdata(csr_rdata),.error(csr_error));
    // Each measurement point keeps its physical identity through every sink.
    // A missing sensor must never borrow the other sensor's samples or health.
    wire eff_b_new = vld_icm_b && !sns_err_b;
    wire signed [15:0] eff_b_ax = b_ax;
    wire signed [15:0] eff_b_ay = b_ay;
    wire signed [15:0] eff_b_az = b_az;
    wire [15:0] eff_b_seq = sns_seq_b;
    wire eff_b_bad = sns_err_b;

    wire eff_a_new = vld_icm_a && !sns_err_a;
    wire signed [15:0] eff_a_ax = a_ax;
    wire signed [15:0] eff_a_ay = a_ay;
    wire signed [15:0] eff_a_az = a_az;
    wire [15:0] eff_a_seq = sns_seq_a;
    wire eff_a_bad = sns_err_a;

    generate if(ENABLE_FEATURES)begin:g_features
        wire [63:0] acquisition_cycles,latest_window_start,latest_window_end;wire [31:0] latest_frame_id;
        wire mock_sample,mock_adc,mock_temp,mock_fg;wire signed [15:0] maxis,may,maz,mbx,mby,mbz,mi,mp,mt;
        wire [15:0] mock_sequence;wire [31:0] mock_period;
        if(LINK_TEST_MODE)begin:g_test_source
            edge_test_source #(.CLK_HZ(ACQ_CLK_HZ)) source(.clk(clk),.rst_n(sys_rst_n),.sample_new(mock_sample),.adc_new(mock_adc),.temp_new(mock_temp),.fg_new(mock_fg),
                .ax(maxis),.ay(may),.az(maz),.bx(mbx),.by(mby),.bz(mbz),.sample_seq(mock_sequence),.current_raw(mi),.pressure_raw(mp),.temp_raw(mt),.fg_period(mock_period));
        end
        edge_features #(.CLK_HZ(ACQ_CLK_HZ),.TEST_MODE(LINK_TEST_MODE),
            .PRESSURE_INDEPENDENT(ENABLE_SDP810 && !LINK_TEST_MODE),.BUILD_ID(32'h202610f7),.HAS_ENVIRONMENT(1)) features(.clk(clk),.rst_n(sys_rst_n),.now_ms(button_time),
            .a_new(LINK_TEST_MODE ? mock_sample:eff_a_new),.b_new(LINK_TEST_MODE ? mock_sample:eff_b_new),
            .ax(LINK_TEST_MODE ? maxis:eff_a_ax),.ay(LINK_TEST_MODE ? may:eff_a_ay),.az(LINK_TEST_MODE ? maz:eff_a_az),
            .bx(LINK_TEST_MODE ? mbx:eff_b_ax),.by(LINK_TEST_MODE ? mby:eff_b_ay),.bz(LINK_TEST_MODE ? mbz:eff_b_az),
            .a_seq(LINK_TEST_MODE ? mock_sequence:eff_a_seq),.b_seq(LINK_TEST_MODE ? mock_sequence:eff_b_seq),
            .a_bad(LINK_TEST_MODE ? 1'b0:eff_a_bad),.b_bad(LINK_TEST_MODE ? 1'b0:eff_b_bad),
            .adc_new(LINK_TEST_MODE ? mock_adc:vld_adc),.adc_bad(LINK_TEST_MODE ? 1'b0:err_adc),
            .current_raw(LINK_TEST_MODE ? mi:adc_ch1),.pressure_raw(LINK_TEST_MODE ? mp:pressure_sample_raw),
            .pressure_new(LINK_TEST_MODE ? mock_adc:pressure_sample_new),.pressure_bad(LINK_TEST_MODE ? 1'b0:pressure_sample_bad),
            .temp_new(LINK_TEST_MODE ? mock_temp:temp_core_vld),.temp_bad(LINK_TEST_MODE ? 1'b0:(!temp_core_present || temp_core_stale || temp_core_short)),
            .temp_raw(LINK_TEST_MODE ? mt:temp_core_raw),.fg_new(LINK_TEST_MODE ? mock_fg:fg_vld),.fg_bad(LINK_TEST_MODE ? 1'b0:fg_timeout),.fg_period(LINK_TEST_MODE ? mock_period:fg_period),
            .control_mode(control_mode),.local_permit(local_permit),.initial_config_permit(initial_config_permit),.req(csr_req && csr_address>=16'h1000 && !wave_select && !environment_select && !icm_select),.write_en(csr_write),.address(csr_address),.wdata(csr_wdata),
            .response(feature_response),.rdata(feature_rdata),.error(feature_error),.frame_available(),.busy(),.acquisition_cycles(acquisition_cycles),
            .latest_frame_id(latest_frame_id),.latest_window_start(latest_window_start),.latest_window_end(latest_window_end));
        // Capture new physical fault causes independently of feature backpressure.
        // Soft/model events may request a marked manual capture via WAV1 CSR.
        wire [31:0] physical_reasons=(control_active | control_latched) & 32'h0002cfff;
        reg [31:0] previous_physical;
        always @(posedge clk or negedge sys_rst_n)
            if(!sys_rst_n)previous_physical<=0;else previous_physical<=physical_reasons;
        edge_waveform #(.CLK_HZ(ACQ_CLK_HZ),.TEST_MODE(LINK_TEST_MODE)) waveform(
            .clk(clk),.rst_n(sys_rst_n),.now_cycles(acquisition_cycles),.now_ms(button_time),
            .enable(1'b1),.stop(1'b0),
            .a_new(LINK_TEST_MODE ? mock_sample:eff_a_new),.b_new(LINK_TEST_MODE ? mock_sample:eff_b_new),
            .ax(LINK_TEST_MODE ? maxis:eff_a_ax),.ay(LINK_TEST_MODE ? may:eff_a_ay),.az(LINK_TEST_MODE ? maz:eff_a_az),
            .bx(LINK_TEST_MODE ? mbx:eff_b_ax),.by(LINK_TEST_MODE ? mby:eff_b_ay),.bz(LINK_TEST_MODE ? mbz:eff_b_az),
            .a_seq(LINK_TEST_MODE ? mock_sequence:eff_a_seq),.b_seq(LINK_TEST_MODE ? mock_sequence:eff_b_seq),
            .a_bad(LINK_TEST_MODE ? 1'b0:eff_a_bad),.b_bad(LINK_TEST_MODE ? 1'b0:eff_b_bad),
            .trigger(|(physical_reasons & ~previous_physical)),.trigger_reason(physical_reasons),
            .trigger_frame_id(latest_frame_id),.trigger_frame_start(latest_window_start),.trigger_frame_end(latest_window_end),
            .release_req(1'b0),.release_id(32'd0),.release_ack(),.armed(),.capturing(),.event_available(),.event_id(),.dropped_triggers(),
            .req(csr_req && wave_select),.write_en(csr_write),.address(csr_address),.wdata(csr_wdata),
            .response(wave_response),.rdata(wave_rdata),.error(wave_error));
    end else begin:g_no_features
        reg response_r;always @(posedge clk or negedge sys_rst_n)if(!sys_rst_n)response_r<=0;else response_r<=csr_req && csr_address>=16'h1000 && !environment_select && !icm_select;
        assign feature_response=response_r;assign feature_rdata=0;assign feature_error=1;
        assign wave_response=0;assign wave_rdata=0;assign wave_error=1;
    end endgenerate
    // EDGE_LINK_ACQ_END
    cooling_control #(.CLK_FREQ(ACQ_CLK_HZ),.GRACE_MS(GRACE_MS),.STARTUP_MS(FG_SPINUP_MS),
        .PRESSURE_INDEPENDENT(ENABLE_SDP810),.BENCH_ENABLE(LINK_TEST_MODE ? 0:CONTROL_BENCH_ENABLE)) u_control(
        .clk(clk),.rst_n(sys_rst_n),.adc_new(vld_adc),.adc_error(err_adc),
        .current_raw(adc_ch1),.pressure_raw(pressure_sample_raw),
        .pressure_new(pressure_sample_new),.pressure_error(pressure_sample_bad),
        .temp_new(temp_core_vld),.temp_present(temp_core_present),.temp_stale(temp_core_stale),
        .temp_short(temp_core_short),.temp_raw(temp_core_raw),
        .fg_new(fg_vld),.fg_timeout(fg_timeout),.fg_period(fg_period),.fg_pulses(fg_pcount),
        .a_new(eff_a_new),.b_new(eff_b_new),.ax(eff_a_ax),.ay(eff_a_ay),.az(eff_a_az),.bx(eff_b_ax),.by(eff_b_ay),.bz(eff_b_az),
        .diagnostic_bad(sns_err_a || sns_err_b),
        .auxiliary_bad(environment_auxiliary_bad),
        .transport_bad_frames(bad_control_frames+rs485_bad),.transport_busy_drops(dropped_control_frames),
        .manual_step(manual_step),.local_silence(local_silence),.local_reset(local_reset),.local_permit(local_permit),
        .req(control_req),.write_en(control_write),.address(control_address),.write_data(control_wdata),
        .response(control_response),.read_data(control_rdata),.error(control_error),
        .applied_duty(fan_duty),.hard_inhibit(control_inhibit),.buzzer(O_buzzer_en),
        .red_on(control_red_on),.red_flash(control_red_flash),
        .active(control_active),.latched(control_latched),.alarm_level(control_level),
        .fan_action(control_fan_action),.mode(control_mode),
        .stable_run(control_stable),.monitor_status(control_monitor),.active_config(control_config),.initial_config_permit(initial_config_permit));
    pwm_out #(.CLK_FREQ(ACQ_CLK_HZ),.PWM_HZ(20_000),.ENABLE_INHIBIT(1),.DUTY_FULL_SCALE(4000),.PIPELINE_DUTY(1)) u_pwm(
        .clk(clk),.rst_n(sys_rst_n),.duty(fan_duty),.inhibit(control_inhibit || LINK_TEST_MODE),.pwm(O_fan_pwm));

    //====================================================================
    // 状态灯 / 告警
    //====================================================================
    reg [26:0] hb_cnt;
    reg        led_hb;
    always @(posedge clk) begin
        if (!sys_rst_n) begin
            hb_cnt <= 27'd0; led_hb <= 1'b0;
        end else if (hb_cnt >= (ACQ_CLK_HZ/2-1)) begin // 0.5s 翻转 → 1Hz
            hb_cnt <= 27'd0;
            led_hb <= ~led_hb;
        end else begin
            hb_cnt <= hb_cnt + 27'd1;
        end
    end

    // 独立自由计数器（不复位清零循环截断）：bit24/25/26 方波
    // ≈ 2.98 / 1.49 / 0.75 Hz @100MHz
    reg [26:0] bl_cnt;
    always @(posedge clk) begin
        if (!sys_rst_n) bl_cnt <= 27'd0;
        else            bl_cnt <= bl_cnt + 27'd1;
    end
    wire bl_hi  = bl_cnt[24];   // ~3Hz（告警闪烁）
    wire bl_mid = bl_cnt[25];   // ~1.5Hz
    wire bl_lo  = bl_cnt[26];   // ~0.75Hz

    // Alarm severity comes from causes/actions, never a direct level-to-PWM map.
    wire alarm=control_red_on;
    wire fg_stall=control_active[6] || control_latched[7] || control_latched[8];

    assign O_led3_hb  = led_hb;
    assign O_led4_alm = control_red_flash;
    assign O_led_grn  = control_stable && control_level==0;
    assign O_led_red  = control_red_flash;
    assign O_led1     = bl_mid;
    assign O_led2     = bl_lo;

    //====================================================================
    // dbg_uart — 调试帧流（115200 8N1）
    // 帧 A 77B@~9.4Hz（frm_tmr 仅空闲期计数，帧传输 6.7ms 不计入）：状态字
    //   + ICM 样本序号/诊断计数（含 dup_a/b_cnt 相邻 vld 样本全同审计）
    //   + 14 路测量量（给全部数据真实出口防综合裁剪；上位机按 seq/tick 审计）
    // 帧 B 27B（每 10 个 A 周期一帧，~1.18s）：BMP280 校准 24 字节
    //   （无此帧原始码无法换算气压）
    // 帧格式与状态字位定义见 dbg_uart.v 头注释
    //====================================================================
    wire bmp_cal_vld = bmp_present & ~bmp_err;   // id 过 + 无错 → 校准数据可信

    wire [15:0] dbg_status =
        {bmp_present,      // bit15
         aht_present,      // bit14
         bmp_cal_vld,      // bit13
         fg_timeout,       // bit12（原始超时标志，未过宽限门控）
         temp_core_stale,   // bit11
         inlet_aht_stale,    // bit10
         sns_init_done,    // bit9
         alarm,            // bit8
         fg_stall,         // bit7（宽限后）
         bmp_err,          // bit6
         aht_err,          // bit5
         temp_core_present, // bit4
         inlet_aht_present,  // bit3
         err_adc,          // bit2
         sns_err_b,        // bit1
         sns_err_a};       // bit0

    dbg_uart #(
        .CLK_FREQ (ACQ_CLK_HZ),
        .BAUD     (115_200),
        .FRAME_MS (100),
        .ARBITRATION(1),
        .CAL_DIV  (10)
    ) u_dbg (
        .clk           (clk),
        .rst_n         (sys_rst_n),
        .d_status      (dbg_status),
        .d_seq_a       (sns_seq_a),
        .d_seq_b       (sns_seq_b),
        .d_tick        (sns_tick),
        .d_vld_a       (sns_vld_a),
        .d_vld_b       (sns_vld_b),
        .d_drdy0_a     (sns_drdy0_a),
        .d_drdy0_b     (sns_drdy0_b),
        .d_wd_a        (sns_wd_a),
        .d_wd_b        (sns_wd_b),
        .d_dup_a       (sns_dup_a),
        .d_dup_b       (sns_dup_b),
        .d_bmp_cal     (bmp_cal_regs),
        .d_bmp_cal_vld (bmp_cal_vld),
        .d_a_ax     (a_ax),  .d_a_ay (a_ay),  .d_a_az (a_az),
        .d_b_ax     (b_ax),  .d_b_ay (b_ay),  .d_b_az (b_az),
        .d_adc1     (adc_ch1), .d_adc2 (adc_ch2), .d_adc3 (adc_ch3), .d_adc4 (adc_ch4),
        .d_adc5     (adc_ch5), .d_adc6 (adc_ch6), .d_adc7 (adc_ch7), .d_adc8 (adc_ch8),
        .d_fg_period(fg_period),
        .d_fg_pcount(fg_pcount),
        .d_inlet_aht_q4   (inlet_aht_raw), .d_core_temp_q4 (temp_core_raw),
        .d_aht_hum  (aht_hum_code), .d_aht_temp (aht_temp_code),
        .d_bmp_t    (bmp_t_raw),  .d_bmp_p (bmp_p_raw),
        .holdoff(dbg_holdoff),
        .frame_busy(dbg_busy),
        .tx         (dbg_tx)
    );

    //====================================================================
    // 本版空闲资源（安全默认态）
    //====================================================================     // UART 空闲电平     // 485 接收态
    assign IO_iic_sda   = 1'bz;     // 释放给板载 EEPROM/RTC（约束已上拉）
    assign IO_iic_scl   = 1'bz;

    // 未使用输入/内部量（防 lint；陀螺/片内温度本版不外发，留待特征提取版本）
    wire _unused = &{1'b0, I_rs485_rx,
                     button_time[0], control_config[0],
                     a_t[0], a_gx[0], a_gy[0], a_gz[0],
                     b_t[0], b_gx[0], b_gy[0], b_gz[0],
                     inlet_aht_vld, temp_core_vld,
                     fg_vld,
                     aht_busy, bmp_busy, bmp_chip_id[0],
                     vld_icm_a, vld_icm_b, vld_adc,
                     1'b0};

endmodule
