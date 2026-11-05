set project_root [file normalize [file join [file dirname [info script]] ..]]
cd $project_root
if {[catch {
    import_device dr1_90.db -package DR1M90GEG400 -speed 2
    import_db migration_check/closure_20261014_r1/real/pr.db
    set output_register {system/design_0_inst/design_0_AXI_Protocol_Converter_1_Inst/axi_protocol_converter_merge_809bc02bc44a_Inst/conversion_to_lite$axi_axilite/RD$r_channel/rd_data_fifo_0/mux0_syn_1136}
    set target [get_cells $output_register]
    set original [list [get_property PLACED_COL $target] [get_property PLACED_ROW $target] [get_property PLACED_OFFSET $target]]
    set macro_name [get_property MACRO $target]
    puts "CLOSURE_MACRO_ROOT: $macro_name"
    report_property [get_cells $macro_name]
    move_cells -inst $macro_name -location {x121y96} -mode enforce -step route
    set updated [list [get_property PLACED_COL $target] [get_property PLACED_ROW $target] [get_property PLACED_OFFSET $target]]
    puts "CLOSURE_CONFIRMED_LOCATION: $original -> $updated"
    if {$original eq $updated} {error "Macro relocation did not move the target"}
    export_db migration_check/closure_macro_probe_20261014.db
    puts "CLOSURE_MACRO_PROBE_PASS"
} message options]} {
    puts stderr "CLOSURE_MACRO_PROBE_FAILED: $message"
    exit 1
}
exit 0
