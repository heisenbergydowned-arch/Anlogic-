set project_root [file normalize [file join [file dirname [info script]] ..]]
cd $project_root
if {[catch {
    import_device dr1_90.db -package DR1M90GEG400 -speed 2
    open_project cooling_link.al
    import_db migration_check/closure_20261014_r1/real/gate.db
    set targets {}
    foreach candidate [get_cells -hier -filter {REF_NAME == AL_MAP_SEQ} {*uihdmi_tx*}] {
        lappend targets [get_property NAME [get_cells $candidate]]
    }
    if {[llength $targets] != 328} {error "Unexpected register collection"}
    create_bound cooling_hdmi_fixed -mode fixed -width 20 -height 20 -origin {102 82}
    foreach target $targets {
        add_cells_to_bound -bound cooling_hdmi_fixed -cells [list $target] -verbose
    }
    puts "FIXED_BOUND_REGISTER_COUNT: [llength $targets]"
    report_bounds
    export_db migration_check/closure_fixed_bound_probe_20261014.db
    puts "FIXED_BOUND_PROBE_PASS"
} message options]} {
    puts stderr "FIXED_BOUND_PROBE_FAILED: $message"
    exit 1
}
exit 0
