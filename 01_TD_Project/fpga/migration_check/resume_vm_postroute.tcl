set cooling_vm_root [file normalize [file join [file dirname [info script]] ..]]
cd $cooling_vm_root
if {[catch {
 source migration_check/check_routed_timing.tcl
 import_device dr1_90.db -package DR1M90GEG400 -speed 2
 import_db migration_check/soc_prj_physical_verified/pr.db
 set cooling_vm_out [file join $cooling_vm_root migration_check soc_prj_postroute_verified]
 file mkdir $cooling_vm_out
 cd $cooling_vm_out
 set_param route effort ultimate
 set_param route fix_hold on
 set_param route post_route_opt high
 set_param route postrt_opt_extra_round 4
 commit_param -step route
 update_timing -mode final
 phys_opt -post_route -effort ultra
 export_db optimized.db
 puts VM_POSTROUTE_OPT_PASS
 route -eco
 update_timing -mode final
 report_timing_summary -file pr.timing
 report_timing_status -file pr.ts
 check_timing -verbose -file chk.timing
 report_area -io_info -file phy.area
 export_db pr.db
 puts VM_POSTROUTE_ROUTE_PASS
 cooling_verify_routed_file pr.timing
 commit_param -step bitgen
 bitgen -bit soc_prj.bit
 puts VM_POSTROUTE_BITGEN_PASS
} cooling_vm_error]} {puts stderr "VM_POSTROUTE_FAILED: $cooling_vm_error"; exit 1}
exit 0