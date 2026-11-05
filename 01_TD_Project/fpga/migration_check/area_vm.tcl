cd {C:/Users/heisenberg/Desktop/FU_Code/soc_merge/soc_merge}
import_device dr1_90.db -package DR1M90GEG400 -speed 2
if {[catch {
 import_db migration_check/soc_prj_synthesis/rtl.db
 clear_user_sdc
 read_sdc src/constraint/top_merge.sdc
 set_param gate map_mode area_prior
 set_param gate pack_effort high
 commit_param -step gate
 file mkdir migration_check/soc_prj_area
 cd migration_check/soc_prj_area
 optimize_gate -packarea gate.area
 legalize_phy_inst
 export_db gate.db
 puts VM_AREA_SYNTH_PASS
 commit_param -step place
 set_param place opt_timing high
 commit_param -step place
 place
 report_area -io_info -file phy.area
 export_db place.db
 puts VM_AREA_PLACE_PASS
 commit_param -step route
 route
 update_timing -mode final
 report_timing_summary -file pr.timing
 check_timing -verbose -file chk.timing
 report_area -io_info -file phy.area
 export_db pr.db
 puts VM_AREA_ROUTE_PASS
 commit_param -step bitgen
 bitgen -bit soc_prj.bit
 puts VM_AREA_BITGEN_PASS
} message]} {puts stderr "VM_AREA_FAILED: $message"; exit 1}
exit 0