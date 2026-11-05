import_device dr1_90.db -package DR1M90GEG400 -speed 2
open_project {D:/Desktop/FU_Code/soc_merge/soc_merge/src/edge/sim/td_link_final/cooling_link.prj}
elaborate -top cooling_link_top
export_db top_elaborate.db
puts "FINAL_ELABORATION_COMPLETE"
exit
