puts P52_ROUTE_REJECTED_SETUP_DEGRADED
report_cells [get_cells {system/u_subsys_acq/g_features$features/mailbox/staging_reg[366]_syn_2}] -attributes -connection -pin_loc
foreach args [list {} {-help} {?}] {
 puts "P52_SINGLE_ROUTE_PROBE $args"
 catch {mpnr_route_net {*}$args} result
 puts $result
}
puts P52_REJECTED_SESSION_CLOSED
exit 0
