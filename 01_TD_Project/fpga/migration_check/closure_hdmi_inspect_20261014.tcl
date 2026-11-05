set project_root [file normalize [file join [file dirname [info script]] ..]]
cd $project_root
import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db migration_check/closure_20261014_r1/real/pr.db
set target {system/design_0_inst/design_0_AXI_Protocol_Converter_1_Inst/axi_protocol_converter_merge_809bc02bc44a_Inst/conversion_to_lite$axi_axilite/RD$r_channel/rd_data_fifo_0/mux0_syn_1136}
puts "CLOSURE_CELL_PROPERTIES"
report_property [get_cells $target]
puts "CLOSURE_CELL_REPORT"
report_cells [get_cells $target] -pin_loc -connection
puts "CLOSURE_CELL_QUERY_HELP"
get_inst_info -help
puts "CLOSURE_INSPECTION_COMPLETE"
exit 0
