puts {P52_BEFORE system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}
report_cells [get_cells {system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}] -attributes -connection -pin_loc
puts P52_CELL_END
set_inst_attr -inst {system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938} -attr_key LUT5A -attr_value {=1}
puts {P52_AFTER system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}
report_cells [get_cells {system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_BEFORE system/u_subsys_acq/environment/read_data_reg[22]_syn_2}
report_cells [get_cells {system/u_subsys_acq/environment/read_data_reg[22]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
set_inst_attr -inst {system/u_subsys_acq/environment/read_data_reg[22]_syn_2} -attr_key LUT5A -attr_value {=1}
puts {P52_AFTER system/u_subsys_acq/environment/read_data_reg[22]_syn_2}
report_cells [get_cells {system/u_subsys_acq/environment/read_data_reg[22]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_BEFORE system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}] -attributes -connection -pin_loc
puts P52_CELL_END
set_inst_attr -inst {system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166} -attr_key LUT5B -attr_value {=1}
puts {P52_AFTER system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_BEFORE system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
set_inst_attr -inst {system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2} -attr_key LUT5B -attr_value {=~D}
puts {P52_AFTER system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_BEFORE system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}] -attributes -connection -pin_loc
puts P52_CELL_END
set_inst_attr -inst {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32} -attr_key LUT5A -attr_value {=C*E*A*B}
puts {P52_AFTER system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_BEFORE system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
set_inst_attr -inst {system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2} -attr_key LUT5A -attr_value {=B*(D+~A*~C*~E)}
puts {P52_AFTER system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
puts P52_ONLY_TWO_INDICATOR_NETS_UNROUTED
mpnr_unroute_net -net {system/u_subsys_acq/u_control/physical_level_b1_n}
mpnr_unroute_net -net {O_led4_alm_dup_3}
disconnect_inst_pin -inst {O_led_red_syn_1} -pin {doq[0]}
connect_inst_pin -inst {O_led_red_syn_1} -pin {doq[0]} -net {O_led4_alm_dup_3}
mpnr_route_net -net {O_led4_alm_dup_3}
puts P52_SINGLE_NET_ROUTE_RETURNED
report_nets [get_nets {O_led4_alm_dup_3}] -connection -check -pin_display_limit 1000
report_route_status -drc
export_db alarm_only.pr.db
export_adc -file after.adc -verbose
export_sdc -file after.sdc
puts P52_LOCAL_PATCH_EXPORTED
