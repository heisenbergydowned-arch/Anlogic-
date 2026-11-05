foreach n [list {system/u_subsys_acq/environment/read_data_reg[22]_syn_2} {system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2} {system/u_subsys_acq/g_features$waveform/frame_start_reg[28]_syn_2}] {
 puts "P52_FINAL_REVIEW_CELL $n"
 report_cells [get_cells $n] -attributes -connection -pin_loc
 puts P52_FINAL_REVIEW_END
}
puts P52_CE_INSPECTION_READY
flush stdout
while {![file exists last_logic.tcl]} {
 if {[clock seconds]>$deadline2} {error {Final logic review timeout}}
 after 100
}
source last_logic.tcl
