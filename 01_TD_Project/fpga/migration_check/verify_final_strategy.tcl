set root [file normalize [file join [file dirname [info script]] ..]]
cd $root
if {[catch {
 set f [open migration_check/check_vm.tcl r]; set text [read $f]; close $f
 if {![info complete $text]} {error "full build Tcl is incomplete"}
 import_device dr1_90.db -package DR1M90GEG400 -speed 2
 open_project soc_prj.al
 foreach {step param wanted} {place opt_timing high place post_place_opt high route effort ultimate route fix_hold on route post_route_opt high} {
   set got [get_param $step $param -run phy_1]
   puts "VM_STRATEGY_VALUE: $step $param = $got"
   if {$got ne $wanted} {error "run strategy mismatch: $step $param expected $wanted got $got"}
 }
 puts VM_STRATEGY_PROBE_PASS
} message]} {puts stderr "VM_STRATEGY_PROBE_FAILED: $message"; exit 1}
exit 0