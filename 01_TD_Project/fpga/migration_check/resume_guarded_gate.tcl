# Matching gate.db provenance is verified by run_guarded_resume_vm.py.
set cooling_vm_root [file normalize [file join [file dirname [info script]] ..]]
cd $cooling_vm_root
set cooling_vm_project $::env(COOLING_VM_PROJECT)
if {[catch {
 source [file join $cooling_vm_root migration_check check_routed_timing.tcl]
 import_device dr1_90.db -package DR1M90GEG400 -speed 2
 import_db $::env(COOLING_VM_GATE)
 cd $::env(COOLING_VM_OUT)
 puts "VM_SYNTHESIS_REUSED: $cooling_vm_project; verified matching checkpoint"
 puts "VM_SYNTHESIS_PASS: $cooling_vm_project"
     set_param place opt_timing high
     set_param place post_place_opt high
     commit_param -step place
     place
     export_db place.db
     puts "VM_PLACE_PASS: $cooling_vm_project"
     set_param route effort ultimate
     set_param route fix_hold on
     if {$cooling_vm_project ne "edge_eval"} {
       set_param route post_route_opt high
       set_param route postrt_opt_extra_round 4
     }
     commit_param -step route
     route
     update_timing -mode final
     report_timing_summary -file initial_pr.timing
     if {[catch {cooling_verify_routed_file initial_pr.timing} cooling_vm_initial_timing]} {
       puts "VM_POSTROUTE_RETRY: $cooling_vm_initial_timing"
       export_db initial_pr.db
       phys_opt -post_route -effort ultra
       route -eco
       update_timing -mode final
     }
     report_timing_summary -file pr.timing
     check_timing -verbose -file chk.timing
     report_area -io_info -file phy.area
     export_db pr.db
     puts "VM_ROUTE_PASS: $cooling_vm_project"
     cooling_verify_routed_file pr.timing
     commit_param -step bitgen
     bitgen -bit ${cooling_vm_project}.bit
     puts "VM_BITGEN_PASS: $cooling_vm_project; inspect pr.timing before hardware use"
} message options]} {
 puts stderr "VM_CHECK_FAILED: $message"
 exit 1
}
puts "VM_CHECK_PASS: $cooling_vm_project"
exit 0
