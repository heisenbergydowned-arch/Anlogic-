set project_root [file normalize [file join [file dirname [info script]] ..]]
cd $project_root
import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db migration_check/closure_20261014_r1/real/gate.db
puts "COLLECTION_COMMANDS: [info commands *collection*]"
puts "OBJECT_COMMANDS: [info commands *object*]"
set target {system/design_0_inst/design_0_uihdmi_tx_0_Inst/uihdmi_tx/u_hdmi_tx_phy_wrapper/u0_lane_lvds_10_1/S_oddr_data_reg[0]}
puts "GATE_SINGLE_PROPERTY"
report_property [get_cells $target]
set targets [get_cells -hier {*S_oddr_data_reg*}]
puts "GATE_COLLECTION_LENGTH: [llength $targets]"
puts "GATE_COLLECTION_VALUE: $targets"
puts "GATE_COLLECTION_NAMES: [get_property NAME $targets]"
puts "GATE_COLLECTION_PROPERTY"
report_property $targets
puts "GATE_INSPECTION_COMPLETE"
exit 0
