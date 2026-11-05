foreach cmd {connect_net disconnect_net mpnr_route_net mpnr_unroute_net get_pins} {
 puts "P52_HELP_BEGIN $cmd"
 catch {help $cmd} message
 puts $message
 puts P52_HELP_END
}
puts P52_HELP_READY
flush stdout
while {![file exists mutate.tcl]} {
 if {[clock seconds]>$deadline2} {error {Mutation not provided}}
 after 100
}
source mutate.tcl
