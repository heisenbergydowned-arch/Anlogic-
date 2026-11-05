import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db C:/Users/heisenberg/FPGA_builds/cabinet_temperature_no_current_trip_p50_20261103/build_003/no_current_threshold.pr.db
puts {CELL_BEGIN O_led_red_syn_1}
report_cells [get_cells {O_led_red_syn_1}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN O_buzzer_en_syn_2}
report_cells [get_cells {O_buzzer_en_syn_2}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/u_bmp280/t_raw_reg[17]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_bmp280/t_raw_reg[17]_syn_2}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/u_dbg/snap_reg[260]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_dbg/snap_reg[260]_syn_2}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/g_features$waveform/end_a_reg[51]_syn_2}
report_cells [get_cells {system/u_subsys_acq/g_features$waveform/end_a_reg[51]_syn_2}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/environment/read_data_reg[22]_syn_2}
report_cells [get_cells {system/u_subsys_acq/environment/read_data_reg[22]_syn_2}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}
report_cells [get_cells {system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}] -attributes -connection -pin_loc
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}] -attributes -connection -pin_loc
puts CELL_END
report_nets [get_nets {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_25}] -connection -pin_display_limit 1000
exit 0
