cd {C:/Users/heisenberg/Desktop/FU_Code/soc_merge/soc_merge}
import_device dr1_90.db -package DR1M90GEG400 -speed 2
if {[catch {
 import_db migration_check/soc_prj_packed/gate.db
 clear_user_sdc
 read_sdc src/constraint/top_merge.sdc
 file mkdir migration_check/soc_prj_packed_physical
 cd migration_check/soc_prj_packed_physical
 commit_param -step place
 insert_debugger
 place
 update_timing -mode manhattan
 report_timing_status -file place.ts
 report_timing_summary -file place.timing
 report_area -io_info -file phy.area
 export_db place.db
 commit_param -step route
 route
 report_area -io_info -file phy.area
 update_timing -mode final
 report_timing_status -file phy.ts
 report_timing_summary -file pr.timing
 report_timing_exception -file exception.timing
 check_timing -verbose -file chk.timing
 export_db pr.db
 commit_param -step bitgen
 bitgen -bit soc_prj.bit
 puts VM_PHYSICAL_BITGEN_PASS
} cooling_vm_error]} {puts stderr "VM_PHYSICAL_FAILED: $cooling_vm_error"; exit 1}
exit 0
