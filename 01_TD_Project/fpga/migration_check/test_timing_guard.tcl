set root [file normalize [file join [file dirname [info script]] ..]]
source [file join $root migration_check check_routed_timing.tcl]
set good "Confidence : Routed\nCheck Corner : Both (Slow and Fast)\nSWNS: 0.001ns, STNS: 0.000ns\nHWNS: 0.001ns, HTNS: 0.000ns\nSTA coverage : 99.97%\nPeriod Check WNS: 4.066ns\nclk4: 150.015 229 system/DR1_PHY_PROCESSOR_SYSTEM_Inst.GEN_PL_HP0\nclk5: 75.002 211 system/DR1_PHY_PROCESSOR_SYSTEM_Inst.GEN_PL_GP0S\nclk6: 150.015 210 system/DR1_PHY_PROCESSOR_SYSTEM_Inst.GEN_PL_GP1S\nclk7: 150.015 116 system/DR1_PHY_PROCESSOR_SYSTEM_Inst.GEN_PL_HP1\n"
if {[catch {cooling_verify_routed_text $good} message]} {puts stderr "guard positive case failed: $message"; exit 1}
set cases [list [string map [list "SWNS: 0.001ns" "SWNS: -0.001ns"] $good] [string map {HWNS:\ 0.001ns HWNS:\ -0.001ns} $good] [string map {Routed Synthesized} $good] [string map {Both Slow} $good] [string map {HWNS HWXX} $good]]
lappend cases [string map {99.97% 99.89%} $good] [string map {99.97% UNKNOWN} $good] [string map {4.066ns -0.001ns} $good] [string map {GEN_PL_HP0 GEN_OTHER_HP0} $good] [string map {75.002 150.015} $good]
foreach bad $cases {if {![catch {cooling_verify_routed_text $bad}]} {puts stderr "guard accepted invalid report"; exit 1}}
set f [open [file join $root backups gui_compile_20261008 soc_prj_Runs.before phy_1 soc_prj_pr.timing] r]
set historical [read $f]
close $f
if {![catch {cooling_verify_routed_text $historical} reason] || ![string match {*HWNS=-2.667*} $reason]} {puts stderr "historical Hold violation was not correctly rejected: $reason"; exit 1}
puts "VM_TIMING_GUARD_TEST_PASS: positive, negative setup/hold, confidence, corners, missing metrics, coverage/period/native PS clocks, historical -2.667ns Hold"
exit 0