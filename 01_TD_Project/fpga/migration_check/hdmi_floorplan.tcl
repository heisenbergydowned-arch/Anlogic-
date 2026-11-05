proc cooling_apply_hdmi_floorplan {} {
    set hdmi_cells {}
    foreach candidate [get_cells -hier -filter {REF_NAME == AL_MAP_SEQ} {*uihdmi_tx*}] {
        lappend hdmi_cells [format %s $candidate]
    }
    if {[llength $hdmi_cells] < 20} {error "Incomplete HDMI physical-cell collection"}
    if {[llength [get_cells -hier {*S_oddr_data_reg*}]] != 8} {error "Expected eight HDMI output registers"}
    create_bound cooling_hdmi_local -mode fixed -width 20 -height 20 -origin {102 82}
    add_cells_to_bound -bound cooling_hdmi_local -cells $hdmi_cells
    export_db bounded_gate.db
    puts "VM_HDMI_BOUND_PASS: [llength $hdmi_cells] cells; RTL, pins and clocks retained"
}
