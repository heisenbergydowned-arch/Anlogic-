puts "P52_HELP_COMMANDS [info commands *help*]"
foreach cmd {connect_net disconnect_net mpnr_route_net mpnr_unroute_net} {
 puts "P52_PROC_BEGIN $cmd"
 catch {info args $cmd} message
 puts $message
 catch {info body $cmd} message
 puts $message
 puts P52_PROC_END
}
puts P52_INSPECT_CONNECTION_API_READY
flush stdout
set deadline2 [expr {[clock seconds]+1200}]
while {![file exists apply_patch.tcl]} {
 if {[clock seconds]>$deadline2} {error {Patch not provided}}
 after 100
}
source apply_patch.tcl
