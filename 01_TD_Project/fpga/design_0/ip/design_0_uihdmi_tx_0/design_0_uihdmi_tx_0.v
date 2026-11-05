/************************************************************\
**	Copyright (c) 2012-2025 anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Gen time	:	2025-11-19 22:42:46
**	DI version	:	178912 2025/11/03
**	TD version	:	6.2.1(build number:178840)
\************************************************************/

module design_0_uihdmi_tx_0 
#(
    parameter DEVICE = "DR1"
)
(
    input             I_pixel_clk ,
    input             I_serial_clk ,
    input             I_rst ,
    input      [23:0] I_video_in_data ,
    input             I_video_in_de ,
    input             I_video_in_vs ,
    input             I_video_in_hs ,
    output            O_hdmi_clk_p ,
    output      [2:0] O_hdmi_tx_p
) ;

    uihdmi_tx #(
        .DEVICE(DEVICE)
    ) uihdmi_tx (
        .I_pixel_clk(I_pixel_clk) ,
        .I_serial_clk(I_serial_clk) ,
        .I_rst(I_rst) ,
        .I_video_in_data(I_video_in_data) ,
        .I_video_in_de(I_video_in_de) ,
        .I_video_in_vs(I_video_in_vs) ,
        .I_video_in_hs(I_video_in_hs) ,
        .O_hdmi_clk_p(O_hdmi_clk_p) ,
        .O_hdmi_tx_p(O_hdmi_tx_p)
    );


endmodule
