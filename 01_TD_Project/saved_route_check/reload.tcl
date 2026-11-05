import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db C:/Users/heisenberg/FPGA_builds/cabinet_alarm_only_pwm_p52_20261103/build_008/alarm_only.pr.db
puts {RELOAD_CELL system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}
report_cells [get_cells {system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}] -attributes -connection -pin_loc
puts RELOAD_END
puts {RELOAD_CELL system/u_subsys_acq/environment/read_data_reg[22]_syn_2}
report_cells [get_cells {system/u_subsys_acq/environment/read_data_reg[22]_syn_2}] -attributes -connection -pin_loc
puts RELOAD_END
puts {RELOAD_CELL system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}] -attributes -connection -pin_loc
puts RELOAD_END
puts {RELOAD_CELL system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}] -attributes -connection -pin_loc
puts RELOAD_END
puts {RELOAD_CELL system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}] -attributes -connection -pin_loc
puts RELOAD_END
puts {RELOAD_CELL system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2}] -attributes -connection -pin_loc
puts RELOAD_END
report_nets [get_nets {O_led4_alm_dup_3}] -connection -pin_display_limit 1000
bitgen -bit reloaded.bit
puts RELOAD_COMPLETE
exit 0
