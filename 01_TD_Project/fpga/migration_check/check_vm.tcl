set cooling_vm_root [file normalize [file join [file dirname [info script]] ..]]
cd $cooling_vm_root
set cooling_vm_project soc_prj
if {[info exists ::env(COOLING_VM_PROJECT)]} {set cooling_vm_project $::env(COOLING_VM_PROJECT)}
set cooling_vm_tops [dict create soc_prj system_top cooling_link cooling_link_top cooling_link_test cooling_link_test_top edge_eval edge_eval_top]
if {![dict exists $cooling_vm_tops $cooling_vm_project]} {puts stderr "VM_CHECK_FAILED: invalid cooling_vm_project"; exit 1}
if {[catch {
 source [file join $cooling_vm_root migration_check check_routed_timing.tcl]
 source [file join $cooling_vm_root migration_check hdmi_floorplan.tcl]
 source [file join $cooling_vm_root migration_check check_gate_clocks.tcl]
 import_device dr1_90.db -package DR1M90GEG400 -speed 2
 open_project ${cooling_vm_project}.al
 elaborate -top [dict get $cooling_vm_tops $cooling_vm_project]
 if {[info exists ::env(COOLING_VM_SYNTH)] && $::env(COOLING_VM_SYNTH) eq "1"} {
   set cooling_vm_out [file join $cooling_vm_root migration_check ${cooling_vm_project}_synthesis]
   if {[info exists ::env(COOLING_VM_OUT)]} {set cooling_vm_out [file normalize $::env(COOLING_VM_OUT)]}
   file mkdir $cooling_vm_out
   if {$cooling_vm_project ne "edge_eval"} {
     read_sdc -ip design_0_ARM_Processor_System_0 design_0/ip/design_0_ARM_Processor_System_0/design_0_ARM_Processor_System_0.sdc
     read_sdc -ip design_0_video_timing_generator_v01_0 design_0/ip/design_0_video_timing_generator_v01_0/design_0_video_timing_generator_v01_0.sdc
     read_adc src/constraint/top_merge.adc
     if {$cooling_vm_project eq "soc_prj"} {read_sdc src/constraint/top_merge.sdc} else {read_sdc src/edge/constraints/link.sdc}
   } else {read_sdc src/edge/constraints/feature_eval.sdc}
   commit_param -step rtl
   insert_debugger
   optimize_rtl
   cd $cooling_vm_out
   report_area -file rtl.area
   export_db rtl.db
   if {$cooling_vm_project ne "edge_eval"} {
     set_param gate map_mode area_prior
     set_param gate pack_effort high
   }
   commit_param -step gate
   optimize_gate -packarea gate.area
   legalize_phy_inst
   update_timing
   report_timing_status -file gate.ts
   report_timing_summary -file gate.timing
   export_db gate.db
   puts "VM_SYNTHESIS_PASS: $cooling_vm_project"
   check_timing -verbose -file gate.chk
   cooling_verify_gate_clock_file gate.chk
   if {$cooling_vm_project in {cooling_link cooling_link_test}} {
     set cooling_reset_pad [get_cells O_adc_reset_syn_4]
     if {[llength $cooling_reset_pad] != 1} {error "RESET physical PAD missing or ambiguous"}
     foreach property {LOCATION IOTYPE DRIVE SLEWRATE PULLMODE DO_DFFMODE SRMODE DO_REGSET OUTRSTMUX} expected {W9 LVCMOS33 8 FAST PULLDOWN DFF ASYNC RESET INV} {
       if {[get_property $property $cooling_reset_pad] ne $expected} {
         error "RESET IO-register requirement failed: $property"
       }
     }
     puts "VM_RESET_PACK_PASS: W9; DFF; asynchronous clear; 8mA FAST; original 8ns budget"
   }
   set cooling_area_file [open gate.area r]
   set cooling_area_text [read $cooling_area_file]
   close $cooling_area_file
   foreach {cooling_resource cooling_limit} {slice 52480 eram 280 dsp 240} {
     set cooling_resource_pattern [format {#%s\*?\s+([0-9]+)} $cooling_resource]
     if {![regexp $cooling_resource_pattern $cooling_area_text unused cooling_used] || $cooling_used>$cooling_limit} {
       error "gate resource missing or over device capacity: $cooling_resource; physical build blocked"
     }
   }
   if {[info exists ::env(COOLING_VM_FULL)] && $::env(COOLING_VM_FULL) eq "1"} {
     set_param place opt_timing medium
     set_param place hfn_opt_effort low
     if {$cooling_vm_project ne "edge_eval"} {cooling_apply_hdmi_floorplan}
     set_param place post_place_opt high
     commit_param -step place
     place
     export_db place.db
     puts "VM_PLACE_PASS: $cooling_vm_project"
     set_param route effort ultimate
     set_param route fix_hold on
     if {$cooling_vm_project ne "edge_eval"} {
       set_param route post_route_opt ultra
       set_param route postrt_opt_extra_round 4
     }
     commit_param -step route
     route
     update_timing -mode final
     report_timing_summary -file initial_pr.timing
     if {[catch {cooling_verify_routed_file initial_pr.timing} cooling_vm_initial_timing]} {
       puts "VM_POSTROUTE_RETRY: $cooling_vm_initial_timing"
       export_db initial_pr.db
       phys_opt -post_route -effort ultra -mode reroute
       route -eco
       update_timing -mode final
     }
     report_timing_summary -file pr.timing
     if {$cooling_vm_project in {cooling_link cooling_link_test}} {
       report_timing_path -to [get_ports O_adc_reset] -report_type max -file reset_setup.timing
       report_timing_path -to [get_ports O_adc_reset] -report_type min -file reset_hold.timing
       set cooling_reset_pad [get_cells O_adc_reset_syn_4]
       foreach property {LOCATION IOTYPE DRIVE SLEWRATE PULLMODE DO_DFFMODE SRMODE DO_REGSET OUTRSTMUX} expected {W9 LVCMOS33 8 FAST PULLDOWN DFF ASYNC RESET INV} {
         if {[get_property $property $cooling_reset_pad] ne $expected} {error "Routed RESET IO-register setting changed: $property"}
       }
       report_property $cooling_reset_pad
       puts "VM_RESET_ROUTED_PACK_PASS: W9 IO DFF retained"
     }
     check_timing -verbose -file chk.timing
     report_area -io_info -file phy.area
     export_db pr.db
     puts "VM_ROUTE_PASS: $cooling_vm_project"
     cooling_verify_routed_file pr.timing
     commit_param -step bitgen
     bitgen -bit ${cooling_vm_project}.bit
     puts "VM_BITGEN_PASS: $cooling_vm_project; inspect pr.timing before hardware use"
   }
 }
} message options]} {
 puts stderr "VM_CHECK_FAILED: $message"
 exit 1
}
puts "VM_CHECK_PASS: $cooling_vm_project"
exit 0
