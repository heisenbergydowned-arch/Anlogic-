foreach command {move_cells place phys_opt multi_try_route set_inst_assignment set_inst_init_loc get_cells get_pins get_nets add_cells_to_bound create_bound report_property} {
    puts "CLOSURE_HELP: $command"
    catch {$command -help}
}
puts "CLOSURE_BOUND_COMMANDS: [info commands *bound*]"
exit 0
