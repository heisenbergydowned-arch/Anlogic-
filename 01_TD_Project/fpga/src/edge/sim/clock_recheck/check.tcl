import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db {D:/Desktop/FU_Code/soc_merge/soc_merge/src/edge/sim/td_link_final/cooling_link_gate.db}
clear_sdc -user
read_sdc {D:/Desktop/FU_Code/soc_merge/soc_merge/src/edge/constraints/link.sdc}
update_timing
report_timing_summary -file corrected_gate.timing
report_timing_exception -file exceptions.timing
check_timing -verbose -file check.timing
puts "CLOCK_RECHECK_COMPLETE"
exit
