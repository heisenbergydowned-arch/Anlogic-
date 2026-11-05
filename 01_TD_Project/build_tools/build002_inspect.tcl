if {[catch {
import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db C:/Users/heisenberg/FPGA_builds/cabinet_temperature_no_current_trip_p50_20261103/build_003/no_current_threshold.pr.db
foreach n [list {system/u_subsys_acq/g_features$features/mailbox/staging_reg[366]_syn_2} {system/u_subsys_acq/u_control/u_temperature_pwm/mapped_target_reg[3]_syn_2} {system/u_subsys_acq/g_features$waveform/frame_start_reg[28]_syn_2}] {
 puts "P52_INSPECT_CELL $n"
 report_cells [get_cells $n] -attributes -connection -pin_loc
 puts P52_INSPECT_END
}
puts P52_SINGLE_ROUTE_USAGE
catch {mpnr_route_net} result
puts $result
puts P52_BUILD002_READY
flush stdout
set deadline [expr {[clock seconds]+1200}]
while {![file exists patch.tcl]} {
 if {[clock seconds]>$deadline} {error {Patch timeout}}
 after 100
}
source patch.tcl
puts P52_PATCH_DONE
flush stdout
while {![file exists finalize.tcl]} {
 if {[clock seconds]>$deadline} {error {Final review timeout}}
 after 100
}
source finalize.tcl
puts P52_BUILD002_COMPLETE
} why]} {puts stderr "P52_BUILD002_FAILED: $why";exit 1}
exit 0
