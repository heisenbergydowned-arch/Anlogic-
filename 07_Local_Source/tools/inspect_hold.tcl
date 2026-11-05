if {[catch {
import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db C:/Users/heisenberg/FPGA_builds/cabinet_temperature_no_current_trip_p50_20261103/build_003/no_current_threshold.pr.db
puts "P52_NET_COMMANDS [info commands *net*]"
puts "P52_ROUTE_COMMANDS [info commands *route*]"
foreach cmd {connect_net disconnect_net route update_design} {
 puts "HELP_BEGIN $cmd"
 catch {$cmd -help} message
 puts $message
 puts HELP_END
}
foreach n [list {system/u_subsys_acq/u_control/physical_level_b1_n} {O_led4_alm_dup_3} {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_25}] {
 puts "NET_BEGIN $n"
 report_nets [get_nets $n] -connection -pin_display_limit 1000
 puts NET_END
}
puts P52_INSPECTION_READY
flush stdout
set deadline [expr {[clock seconds]+1200}]
while {![file exists step1.tcl]} {
 if {[clock seconds]>$deadline} {error {Patch review timeout}}
 after 100
}
source step1.tcl
puts P52_STEP1_COMPLETE
flush stdout
while {![file exists step2.tcl]} {
 if {[clock seconds]>$deadline} {error {Post-patch review timeout}}
 after 100
}
source step2.tcl
puts P52_COMPLETE
} why]} {puts stderr "P52_FAILED: $why";exit 1}
exit 0
