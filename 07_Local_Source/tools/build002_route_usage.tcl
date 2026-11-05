puts P52_UNROUTE_USAGE
catch {mpnr_unroute_net} result
puts $result
puts P52_SINGLE_NET_API_READY
flush stdout
while {![file exists apply_local.tcl]} {
 if {[clock seconds]>$deadline} {error {Local patch timeout}}
 after 100
}
source apply_local.tcl
