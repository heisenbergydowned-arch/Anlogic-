<?xml version="1.0" encoding="UTF-8"?>
<Project Version="3" Minor="2" Path=".">
    <Project_Created_Time></Project_Created_Time>
    <TD_Encoding>UTF-8</TD_Encoding>
    <TD_Version>6.2.200067</TD_Version>
    <Name>cooling_link_test</Name>
    <HardWare>
        <Family>DR1</Family>
        <Device>DR1M90GEG400</Device>
        <Speed>-2</Speed>
    </HardWare>
    <Source_Files>
        <Verilog>
            <File Path="src/system_top.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="1"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/csi_unpacket.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="2"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/design_top_wrapper.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="3"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/raw10_unpacket.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="4"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/raw8_to_rgb888.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="5"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/rgb888_to_axi_stream.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="6"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/video_cuttting.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="7"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/w32_d482_shifter.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="8"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/w40_d512_fifo.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="9"/>
                </FileInfo>
            </File>
            <File Path="src/isp/axis_sobel.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="10"/>
                </FileInfo>
            </File>
            <File Path="src/isp/gray_mean.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="11"/>
                </FileInfo>
            </File>
            <File Path="src/isp/matrix_3x3.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="12"/>
                </FileInfo>
            </File>
            <File Path="src/isp/rgb2yuv_4ppc.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="13"/>
                </FileInfo>
            </File>
            <File Path="src/isp/shift_ram.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="14"/>
                </FileInfo>
            </File>
            <File Path="src/isp/ram0/ram0.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="15"/>
                </FileInfo>
            </File>
            <File Path="src/isp/ram0/ram_dca62376a38a.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="16"/>
                </FileInfo>
            </File>
            <File Path="src/write_fdma/fs_cap.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="17"/>
                </FileInfo>
            </File>
            <File Path="src/write_fdma/uiFDMA.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="18"/>
                </FileInfo>
            </File>
            <File Path="src/write_fdma/uidbuf_write.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="19"/>
                </FileInfo>
            </File>
            <File Path="src/write_fdma/wfifo.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="20"/>
                </FileInfo>
            </File>
            <File Path="src/pwm.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="21"/>
                </FileInfo>
            </File>
            <File Path="src/hdmi_tx/hdmi_phy_warpper.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="22"/>
                </FileInfo>
            </File>
            <File Path="src/hdmi_tx/hdmi_tx_controller_wrapper.enc.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="23"/>
                </FileInfo>
            </File>
            <File Path="src/hdmi_tx/lane_lvds_10_1.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="24"/>
                </FileInfo>
            </File>
            <File Path="src/hdmi_tx/uihdmi_tx.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="25"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/mipi_rx/data_lane_rx_wrapper.enc.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="26"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/mipi_rx/mipi_dphy_rx_over_lvds_wrapper.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="27"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/mipi_rx/rx_clk_gen.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="28"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/src/auto_white_balance.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="29"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/awb_1_1/awb.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="30"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/awb_1_1/signal_delay.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="31"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/awb_1_1/devider/divider_gate.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="32"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/isp_top.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="33"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/image_cut/image_cut.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="34"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/gamma.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="35"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_0_8.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="36"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_1_2.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="37"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_1_4.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="38"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_1_6.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="39"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_1_8.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="40"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_2_0.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="41"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_2_2.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="42"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_2_4.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="43"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/gamma/lut_2_6.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="44"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/Saturation_adj/Saturation_adj.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="45"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/Contrast_adjustment/contrast_adj.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="46"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/Brightness_adjustment/Brightness_adjustment.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="47"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/raw10_unpacket_4lane.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="48"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/image_correction/image_correction.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="49"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/BLC/BLC.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="50"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/data96_128/data96_128.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="51"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/data128_96/data128_96.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="52"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/demosaic_4x_2_0/bilinear_interpolation.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="53"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/demosaic_4x_2_0/line_buffer_demosaic.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="54"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/demosaic_4x_2_0/mipi_to_raw_converter.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="55"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/demosaic_4x_2_0/raw_matrix_3x3_buffer.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="56"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/demosaic_4x_2_0/top_demosaic.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="57"/>
                </FileInfo>
            </File>
            <File Path="src/ui_isp/demosaic_4x_2_0/zhenghe.v">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="58"/>
                </FileInfo>
            </File>
            <File Path="src/acq/subsys_acq.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="59"/>
                </FileInfo>
            </File>
            <File Path="src/acq/sns_sync.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="60"/>
                </FileInfo>
            </File>
            <File Path="src/acq/ads7606_if.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="61"/>
                </FileInfo>
            </File>
            <File Path="src/acq/ds18b20.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="62"/>
                </FileInfo>
            </File>
            <File Path="src/acq/fg_cap.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="63"/>
                </FileInfo>
            </File>
            <File Path="src/acq/pwm_out.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="64"/>
                </FileInfo>
            </File>
            <File Path="src/acq/i2c_master.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="65"/>
                </FileInfo>
            </File>
            <File Path="src/acq/aht20_drv.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="66"/>
                </FileInfo>
            </File>
            <File Path="src/acq/bmp280_drv.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="67"/>
                </FileInfo>
            </File>
            <File Path="src/acq/dbg_uart.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="68"/>
                </FileInfo>
            </File>
            <File Path="src/control/alarm_outputs.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="69"/>
                </FileInfo>
            </File>
            <File Path="src/control/control_arbiter.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="70"/>
                </FileInfo>
            </File>
            <File Path="src/control/cooling_axi_lite.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="71"/>
                </FileInfo>
            </File>
            <File Path="src/control/cooling_buttons.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="72"/>
                </FileInfo>
            </File>
            <File Path="src/control/cooling_control.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="73"/>
                </FileInfo>
            </File>
            <File Path="src/control/cooling_regs.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="74"/>
                </FileInfo>
            </File>
            <File Path="src/control/cooling_tick.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="75"/>
                </FileInfo>
            </File>
            <File Path="src/control/cooling_uart.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="76"/>
                </FileInfo>
            </File>
            <File Path="src/control/fault_filter.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="77"/>
                </FileInfo>
            </File>
            <File Path="src/control/protect_fsm.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="78"/>
                </FileInfo>
            </File>
            <File Path="src/control/rpm_measure.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="79"/>
                </FileInfo>
            </File>
            <File Path="src/control/rpm_pi.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="80"/>
                </FileInfo>
            </File>
            <File Path="src/control/safety_monitor.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="81"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_udiv.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="82"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_axil_router.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="83"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_csr_cdc.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="84"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_csr_mux.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="85"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_features.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="86"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_mailbox.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="87"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_test_source.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="88"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_window.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="89"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_window_mean.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="90"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_extract.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="91"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_fft_ram.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="92"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_hann_rom.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="93"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_isqrt.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="94"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_process_convert.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="95"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_q16_float.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="96"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_twiddle_rom.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="97"/>
                </FileInfo>
            </File>
            <File Path="src/features/fft1024_iter.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="98"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_rs485.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="99"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_uart_byte.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="100"/>
                </FileInfo>
            </File>
            <File Path="src/edge/rtl/edge_eval_top.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="101"/>
                </FileInfo>
            </File>
            <File Path="src/features/feature_float_serial.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="102"/>
                </FileInfo>
            </File>
<File Path="src/edge/rtl/edge_waveform.v"><FileInfo><Attr Name="BelongTo" Val="design_1"/><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="CompileOrder" Val="103"/></FileInfo></File>
<File Path="src/edge/rtl/edge_environment.v"><FileInfo><Attr Name="BelongTo" Val="design_1"/><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="CompileOrder" Val="104"/></FileInfo></File>
<File Path="src/features/feature_square64.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="105"/></FileInfo></File>
<File Path="src/edge/rtl/cooling_link_test_top.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="106"/></FileInfo></File>
<File Path="src/edge/rtl/cooling_link_top.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="107"/></FileInfo></File>
            <File Path="src/acq/sdp810_drv.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="108"/>
                </FileInfo>
            </File>
            <File Path="src/acq/i2c_arbiter3.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="109"/>
                </FileInfo>
            </File>
        <File Path="src/filter_v4/filter_age_ms_pair.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="110"/></FileInfo></File>
<File Path="src/filter_v4/filter_current_boxcar32.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="111"/></FileInfo></File>
<File Path="src/filter_v4/filter_edge_window.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="112"/></FileInfo></File>
<File Path="src/filter_v4/filter_measurement_frontend.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="113"/></FileInfo></File>
<File Path="src/filter_v4/filter_prefix_snapshot.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="114"/></FileInfo></File>
<File Path="src/filter_v4/filter_pressure_ema_q4.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="115"/></FileInfo></File>
<File Path="src/filter_v4/filter_vib_fir_shared.v"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="116"/></FileInfo></File>
</Verilog>
        <System_Verilog>
            <File Path="src/MIPI_V2/mipi_rx/channel_aligner_wrapper.enc.sv">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="117"/>
                </FileInfo>
            </File>
            <File Path="src/MIPI_V2/mipi_rx/hs_rx_wrapper.sv">
                <FileInfo>
                    <Attr Name="AutoExcluded" Val="true"/>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="118"/>
                </FileInfo>
            </File>
        </System_Verilog>
        <ADC_FILE>
            <File Path="src/constraint/top_merge.adc">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="constraint_1"/>
                    <Attr Name="CompileOrder" Val="119"/>
                </FileInfo>
            </File>
        </ADC_FILE>
        <SDC_FILE>
            <File Path="src/edge/constraints/link.sdc">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="constraint_1"/>
                    <Attr Name="CompileOrder" Val="120"/>
                </FileInfo>
            </File>
        </SDC_FILE>
        <IP_FILE>
            <File Path="design_0/design_0.xml">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="121"/>
                </FileInfo>
            </File>
        </IP_FILE>
    </Source_Files>
    <FileSets>
        <FileSet Name="design_1" Type="DesignFiles">
        </FileSet>
        <FileSet Name="constraint_1" Type="ConstrainFiles">
        </FileSet>
    </FileSets>
    <TOP_MODULE>
        <LABEL>cooling_link_test_top</LABEL>
        <MODULE>cooling_link_test_top</MODULE>
        <CREATEINDEX>user</CREATEINDEX>
    </TOP_MODULE>
    <Property>
    </Property>
    <Device_Settings>
    </Device_Settings>
    <Configurations>
    </Configurations>
    <Runs>
        <Run Name="syn_1" Type="Synthesis" ConstraintSet="constraint_1" Description="" Active="true">
            <Strategy Name="Default_Synthesis_Strategy">
                <GateProperty>
                    <map_mode>area_prior</map_mode>
                    <pack_effort>high</pack_effort>
                </GateProperty>
            </Strategy>
            <UserParams>
            </UserParams>
        </Run>
        <Run Name="phy_1" Type="PhysicalDesign" ConstraintSet="constraint_1" Description="" SynRun="syn_1" Active="true">
            <Strategy Name="Default_PhysicalDesign_Strategy">
                <BitgenProperty::GeneralOption>
                    <compress>on</compress>
                </BitgenProperty::GeneralOption>
                <PlaceProperty>
                    <opt_timing>high</opt_timing>
                </PlaceProperty>
            </Strategy>
            <UserParams>
            </UserParams>
        </Run>
    </Runs>
    <Project_Settings>
    </Project_Settings>
</Project>
