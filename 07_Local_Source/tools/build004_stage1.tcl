if {[catch {
import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db C:/Users/heisenberg/FPGA_builds/cabinet_temperature_no_current_trip_p50_20261103/build_003/no_current_threshold.pr.db
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
mpnr_unroute_net -net {system/u_subsys_acq/u_control/physical_level_b1_n}
mpnr_unroute_net -net {O_led4_alm_dup_3}
mpnr_save_revert -save
export_db no_indicator_routes.pr.db
puts P52_STAGE1_SAVED
} why]} {puts stderr "P52_STAGE1_FAILED: $why";exit 1}
exit 0
