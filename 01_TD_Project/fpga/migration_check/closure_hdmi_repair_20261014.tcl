set cooling_vm_root [file normalize [file join [file dirname [info script]] ..]]
cd $cooling_vm_root
if {[catch {
    source migration_check/check_routed_timing.tcl
    import_device dr1_90.db -package DR1M90GEG400 -speed 2
    import_db $::env(COOLING_REPAIR_CHECKPOINT)
    cd $::env(COOLING_REPAIR_OUTPUT)
    set output_register {system/design_0_inst/design_0_AXI_Protocol_Converter_1_Inst/axi_protocol_converter_merge_809bc02bc44a_Inst/conversion_to_lite$axi_axilite/RD$r_channel/rd_data_fifo_0/mux0_syn_1136}
    set green_register {system/design_0_inst/design_0_uihdmi_tx_0_Inst/uihdmi_tx/u_hdmi_tx_phy_wrapper/u1_lane_lvds_10_1/S_shift_data_reg[7]_syn_2}
    set red_register {system/design_0_inst/design_0_uihdmi_tx_0_Inst/uihdmi_tx/u_hdmi_tx_phy_wrapper/u2_lane_lvds_10_1/S_shift_data_reg[0]_syn_2}
    foreach target [list $output_register $green_register $red_register] {
        if {[llength [get_cells $target]] != 1} {error "Expected exactly one checkpoint cell: $target"}
    }
    foreach target [list $output_register $green_register $red_register] location {{x121y96} {x120y118} {x118y117}} {
        set candidate [get_cells $target]
        set original [list [get_property PLACED_COL $candidate] [get_property PLACED_ROW $candidate] [get_property PLACED_OFFSET $candidate]]
        move_cells -inst $target -location $location -mode enforce -step route
        set updated [list [get_property PLACED_COL $candidate] [get_property PLACED_ROW $candidate] [get_property PLACED_OFFSET $candidate]]
        if {$original eq $updated} {error "Target did not move: $target"}
    }
    puts "VM_HDMI_RELOCATION_PASS: three checkpoint cells; clocks and RTL unchanged"
    export_db relocated.db
    set_param route effort ultimate
    set_param route fix_hold on
    set_param route post_route_opt ultra
    set_param route postrt_opt_extra_round 4
    commit_param -step route
    route -eco
    update_timing -mode final
    report_timing_summary -file pr.timing
    check_timing -verbose -file chk.timing
    report_area -io_info -file phy.area
    export_db pr.db
    puts "VM_ROUTE_PASS: cooling_link"
    cooling_verify_routed_file pr.timing
    commit_param -step bitgen
    bitgen -bit cooling_link.bit
    puts "VM_BITGEN_PASS: cooling_link"
} message options]} {
    puts stderr "VM_CHECK_FAILED: $message"
    exit 1
}
puts "VM_CHECK_PASS: cooling_link"
exit 0
