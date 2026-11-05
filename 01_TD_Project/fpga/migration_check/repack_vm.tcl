cd {C:/Users/heisenberg/Desktop/FU_Code/soc_merge/soc_merge}
import_device dr1_90.db -package DR1M90GEG400 -speed 2
if {[catch {
 import_db migration_check/soc_prj_synthesis/gate.db
 clear_user_sdc
 read_sdc src/constraint/top_merge.sdc
 set_param gate pack_effort high
 commit_param -step gate
 pack
 file mkdir migration_check/soc_prj_packed
 cd migration_check/soc_prj_packed
 report_area -file gate.area
 export_db gate.db
 puts VM_REPACK_PASS
} message]} {puts stderr "VM_REPACK_FAILED: $message"; exit 1}
exit 0