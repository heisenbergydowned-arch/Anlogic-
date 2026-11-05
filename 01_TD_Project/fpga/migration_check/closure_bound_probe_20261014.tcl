set project_root [file normalize [file join [file dirname [info script]] ..]]
cd $project_root
if {[catch {
    import_device dr1_90.db -package DR1M90GEG400 -speed 2
    import_db migration_check/closure_20261014_r1/real/gate.db
    set targets [get_cells -hier -filter {REF_NAME == AL_MAP_SEQ} {*uihdmi_tx*}]
    set outputs [get_cells -hier {*S_oddr_data_reg*}]
    puts "BOUND_REGISTER_COUNT: [llength $targets]"
    puts "BOUND_OUTPUT_COUNT: [llength $outputs]"
    if {[llength $targets] < 20 || [llength $outputs] != 8} {error "Incomplete register collection"}
    puts "BOUND_FIRST_REGISTER: [lindex $targets 0]"
    create_bound cooling_hdmi_local -mode soft -width 20 -height 20 -origin {102 82}
    add_cells_to_bound -bound cooling_hdmi_local -cells $targets
    report_bounds
    puts "BOUND_PROBE_PASS"
} message options]} {
    puts stderr "BOUND_PROBE_FAILED: $message"
    exit 1
}
exit 0
