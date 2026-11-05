set cooling_vm_root [file normalize [file join [file dirname [info script]] ..]]
cd $cooling_vm_root
if {[catch {
 import_device dr1_90.db -package DR1M90GEG400 -speed 2
 import_db migration_check/soc_prj_synthesis/gate.db
 set cooling_vm_out [file join $cooling_vm_root migration_check soc_prj_physical_verified]
 file mkdir $cooling_vm_out
 cd $cooling_vm_out
 set_param place opt_timing high
 set_param place post_place_opt high
 commit_param -step place
 place
 export_db place.db
 update_timing -mode manhattan
 report_timing_summary -file place.timing
 report_area -io_info -file place.area
 puts VM_VERIFIED_PLACE_PASS
 set_param route effort ultimate
 set_param route fix_hold on
 commit_param -step route
 route
 update_timing -mode final
 report_timing_summary -file pr.timing
 report_timing_status -file pr.ts
 check_timing -verbose -file chk.timing
 report_area -io_info -file phy.area
 export_db pr.db
 puts VM_VERIFIED_ROUTE_PASS
 set cooling_vm_f [open pr.timing r]
 set cooling_vm_timing [read $cooling_vm_f]
 close $cooling_vm_f
 if {![regexp {SWNS:\s*(-?[0-9.]+)ns} $cooling_vm_timing unused cooling_vm_swns] || ![regexp {HWNS:\s*(-?[0-9.]+)ns} $cooling_vm_timing unused cooling_vm_hwns]} {error "routed timing report missing SWNS/HWNS"}
 if {$cooling_vm_swns < 0 || $cooling_vm_hwns < 0} {error "routed timing failed: SWNS=$cooling_vm_swns HWNS=$cooling_vm_hwns; bitgen blocked"}
 commit_param -step bitgen
 bitgen -bit soc_prj.bit
 puts VM_VERIFIED_BITGEN_PASS
} cooling_vm_error]} {puts stderr "VM_VERIFIED_PHYSICAL_FAILED: $cooling_vm_error"; exit 1}
exit 0