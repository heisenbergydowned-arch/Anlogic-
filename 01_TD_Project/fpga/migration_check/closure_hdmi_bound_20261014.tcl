set project_root [file normalize [file join [file dirname [info script]] ..]]
cd $project_root
if {[catch {
    source migration_check/check_routed_timing.tcl
    import_device dr1_90.db -package DR1M90GEG400 -speed 2
    open_project cooling_link.al
    import_db $::env(COOLING_REPAIR_CHECKPOINT)
    cd $::env(COOLING_REPAIR_OUTPUT)
    set hdmi_cells {}
    foreach candidate [get_cells -hier -filter {REF_NAME == AL_MAP_SEQ} {*uihdmi_tx*}] {
        lappend hdmi_cells [format %s $candidate]
    }
    if {[llength $hdmi_cells] < 20} {error "Incomplete HDMI physical-cell collection"}
    if {[llength [get_cells -hier {*S_oddr_data_reg*}]] != 8} {error "Expected eight HDMI output registers"}
    create_bound cooling_hdmi_local -mode fixed -width 20 -height 20 -origin {102 82}
    add_cells_to_bound -bound cooling_hdmi_local -cells $hdmi_cells
    export_db bounded_gate.db
    puts "VM_HDMI_BOUND_PASS: [llength $hdmi_cells] cells; original RTL, pins and clocks retained"
    set_param place opt_timing high
    set_param place post_place_opt high
    set_param place preplace_floorplan on
    commit_param -step place
    place
    export_db place.db
    puts "VM_PLACE_PASS: cooling_link"
    set_param route effort ultimate
    set_param route fix_hold on
    set_param route post_route_opt ultra
    set_param route postrt_opt_extra_round 4
    commit_param -step route
    route
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
