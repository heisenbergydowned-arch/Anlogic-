# Explicit physical requests only. The original clocks, IO pins, limits and bounding geometry are unchanged.
proc cooling_request_hdmi_locations {} {
 set assignments [dict create \
 {system/design_0_inst/design_0_uihdmi_tx_0_Inst/uihdmi_tx/u_hdmi_tx_controller_wrapper/u1_hdmi_tmds_encode/O_tmds_code_data_reg[1]} x121y98z6 \
 {system/design_0_inst/design_0_uihdmi_tx_0_Inst/uihdmi_tx/u_hdmi_tx_phy_wrapper/u1_lane_lvds_10_1/S_shift_data_reg[8]} x121y98z1 \
 {system/design_0_inst/design_0_uihdmi_tx_0_Inst/uihdmi_tx/u_hdmi_tx_phy_wrapper/u1_lane_lvds_10_1/S_shift_data_reg[6]} x121y98z1]
 dict for {name loc} $assignments {
  puts "R46_PRE_GATE_LOCATION_REQUEST: $name = $loc"
  set_inst_assignment $name [format {location = %s;} $loc]
 }
}
proc cooling_audit_hdmi_locations {phase} {
 puts "PACKING_AUDIT_${phase}_BEGIN"
 foreach c [get_cells -hier {*uihdmi_tx*}] {
  set n [format %s $c]
  puts "PACK_CELL_BEGIN: $n"
  report_cells $n -attributes -connection -pin_loc
  puts "PACK_CELL_END"
 }
 report_bounds -all
 puts "PACKING_AUDIT_${phase}_END"
 flush stdout
}
