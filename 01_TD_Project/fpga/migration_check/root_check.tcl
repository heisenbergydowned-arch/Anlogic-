cd {C:/Users/heisenberg/Desktop/FU_Code/soc_merge/soc_merge}
import_device dr1_90.db -package DR1M90GEG400 -speed 2
open_project soc_prj.al
elaborate -top system_top
puts "MIGRATION_ELABORATE_PASS"
exit