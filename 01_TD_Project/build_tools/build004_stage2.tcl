if {[catch {
import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db C:/Users/heisenberg/FPGA_builds/cabinet_alarm_only_pwm_p52_20261103/build_004/no_indicator_routes.pr.db
disconnect_inst_pin -inst {O_led_red_syn_1} -pin {doq[0]}
connect_inst_pin -inst {O_led_red_syn_1} -pin {doq[0]} -net {O_led4_alm_dup_3}
mpnr_route_net -net {O_led4_alm_dup_3}
mpnr_save_revert -save
puts P52_ROUTE_SAVED
report_nets [get_nets {O_led4_alm_dup_3}] -connection -pin_display_limit 1000
puts {P52_RELOADED system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}
report_cells [get_cells {system/u_subsys_acq/u_control/u_regs/read_data_b1[0]_syn_938}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_RELOADED system/u_subsys_acq/environment/read_data_reg[22]_syn_2}
report_cells [get_cells {system/u_subsys_acq/environment/read_data_reg[22]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_RELOADED system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mux67_syn_166}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_RELOADED system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/trip_reasons_reg[3]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_RELOADED system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_32}] -attributes -connection -pin_loc
puts P52_CELL_END
puts {P52_RELOADED system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2}
report_cells [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2}] -attributes -connection -pin_loc
puts P52_CELL_END
export_db alarm_only.pr.db
export_adc -file after.adc -verbose
export_sdc -file after.sdc
puts P52_LOCAL_PATCH_EXPORTED
flush stdout
set deadline [expr {[clock seconds]+300}]
while {![file exists changes.pass]} {
 if {[clock seconds]>$deadline} {error {Independent review timeout}}
 after 100
}
bitgen -bit cooling_link.bit
puts P52_BITGEN_COMPLETE
} why]} {puts stderr "P52_STAGE2_FAILED: $why";exit 1}
exit 0
