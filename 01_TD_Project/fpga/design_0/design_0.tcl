si_open_design [file normalize [file dirname [info script]]]
si_design_add_inst -vlnv anlogic.com:ip:DR1_ARM_Processor_System:1.0 DR1_ARM_Processor_System_0
si_design_add_inst -vlnv anlogic.com:ip:AXI_Protocol_Converter:1.0 AXI_Protocol_Converter_0
si_design_add_inst -vlnv anlogic.com:ip:AXI_Protocol_Converter:1.0 AXI_Protocol_Converter_1
si_design_add_port -dir input -from 63 -to 0 pl_gpio_in
si_design_add_port -dir output -from 63 -to 0 pl_gpio_oe
si_design_add_port -dir output -from 63 -to 0 pl_gpio_out
si_design_add_port -dir output i2c0_scl_oe
si_design_add_port -dir output i2c0_sda_oe
si_design_add_port -dir output i2c1_scl_oe
si_design_add_port -dir output i2c1_sda_oe
si_design_add_port -dir input i2c0_scl_in
si_design_add_port -dir input i2c0_sda_in
si_design_add_port -dir input i2c1_scl_in
si_design_add_port -dir input i2c1_sda_in
si_design_add_port -dir input -from 15 -to 0 f2p_irq
si_design_add_port -dir input pl_clk_150M
si_design_add_port -dir input pl_softnpu_clk
si_design_add_port -dir input pl_softnpu_rstn
si_design_add_port -dir input pl_config_clk
si_design_add_port -dir input pl_config_rstn
