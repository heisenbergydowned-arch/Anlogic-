module cooling_link_top(
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
    output wire O_fan_pwm,         // fan PWM 25kHz
    output wire O_buzzer_en,       // FCB1 local protection buzzer
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
system_top #(.ENABLE_CAMERA(0),.ENABLE_EDGE_FEATURES(1),.LINK_TEST_MODE(0),.CONTROL_BENCH_ENABLE(0)) system(
.O_hdmi_tx_p(O_hdmi_tx_p),
.O_hdmi_clk_p(O_hdmi_clk_p),
.SCL0(SCL0),
.SDA0(SDA0),
.led(led),
.I_clk_hs_p(I_clk_hs_p),
.I_data_hs_p(I_data_hs_p),
.I_data_lp_p(I_data_lp_p),
.I_data_lp_n(I_data_lp_n),
.O_imx334_clk_24m(O_imx334_clk_24m),
.O_imax334_rst_n(O_imax334_rst_n),
.I_sysclk(I_sysclk),
.O_spi_sclk(O_spi_sclk),
.O_spi_mosi(O_spi_mosi),
.I_spi_miso(I_spi_miso),
.O_cs_icm_a(O_cs_icm_a),
.O_cs_icm_b(O_cs_icm_b),
.O_adc_convst(O_adc_convst),
.O_adc_sclk(O_adc_sclk),
.O_adc_reset(O_adc_reset),
.I_adc_douta(I_adc_douta),
.O_adc_cs(O_adc_cs),
.I_adc_busy(I_adc_busy),
.I_adc_frstdata(I_adc_frstdata),
.IO_j12_19_reserved(IO_j12_19_reserved),
.IO_temp_core_dq(IO_temp_core_dq),
.IO_i2c_sda_ext(IO_i2c_sda_ext),
.IO_i2c_scl_ext(IO_i2c_scl_ext),
.I_fan_fg(I_fan_fg),
.IO_j12_22_reserved(IO_j12_22_reserved),
.O_fan_pwm(O_fan_pwm),
.O_buzzer_en(O_buzzer_en),
.O_led_grn(O_led_grn),
.O_led_red(O_led_red),
.O_rs485_tx(O_rs485_tx),
.I_rs485_rx(I_rs485_rx),
.O_rs485_de(O_rs485_de),
.O_led3_hb(O_led3_hb),
.O_led4_alm(O_led4_alm),
.I_key1(I_key1),
.I_key2(I_key2),
.O_pl_uart_tx(O_pl_uart_tx),
.I_pl_uart_rx(I_pl_uart_rx),
.IO_iic_sda(IO_iic_sda),
.IO_iic_scl(IO_iic_scl)
);
endmodule
