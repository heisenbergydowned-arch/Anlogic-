set project_root [file normalize [file join [file dirname [info script]] ..]]
cd $project_root
if {[catch {
    import_device dr1_90.db -package DR1M90GEG400 -speed 2
    import_db migration_check/closure_20261014_r1/real/gate.db
    set targets {}
    foreach candidate [get_cells -hier -filter {REF_NAME == AL_MAP_SEQ} {*uihdmi_tx*}] {
        lappend targets [format %s $candidate]
    }
    puts "BOUND_PLAIN_REGISTER_COUNT: [llength $targets]"
    if {[llength $targets] != 328} {error "Unexpected register collection"}
    create_bound cooling_hdmi_local -mode soft -width 20 -height 20 -origin {102 82}
    add_cells_to_bound -bound cooling_hdmi_local -cells $targets -verbose
    puts "BOUND_PLAIN_ADD_FINISHED"
    export_db migration_check/closure_bound_probe2_20261014.db
    puts "BOUND_PLAIN_PROBE_PASS"
} message options]} {
    puts stderr "BOUND_PLAIN_PROBE_FAILED: $message"
    exit 1
}
exit 0
