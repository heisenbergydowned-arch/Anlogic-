proc cooling_verify_gate_clock_file {path} {
    set handle [open $path r]
    set report [read $handle]
    close $handle
    foreach category {{no clock} {clock definition} {invalid constraint} {pll/clock buffer clock constraints} {combinational loops}} {
        set pattern [format {checking %s\(([0-9]+)\)} $category]
        if {![regexp $pattern $report unused count] || $count != 0} {
            error "Unqualified gate clock check: $category; physical implementation blocked"
        }
    }
    puts "VM_GATE_CLOCKS_PASS: no missing/conflicting/invalid/mismatched clocks or loops"
}
