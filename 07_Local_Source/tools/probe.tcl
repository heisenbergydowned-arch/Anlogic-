import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db C:/Users/heisenberg/FPGA_builds/cabinet_temperature_no_current_trip_p50_20261103/build_003/no_current_threshold.pr.db
puts {PATTERN *O_led_red*}
foreach net [get_nets -hier {*O_led_red*}] {report_nets $net -connection -pin_display_limit 1000}
puts {PATTERN *O_buzzer*}
foreach net [get_nets -hier {*O_buzzer*}] {report_nets $net -connection -pin_display_limit 1000}
puts {PATTERN *O_led4_alm*}
foreach net [get_nets -hier {*O_led4_alm*}] {report_nets $net -connection -pin_display_limit 1000}
puts {PATTERN *error_b8_n4*}
foreach net [get_nets -hier {*error_b8_n4*}] {report_nets $net -connection -pin_display_limit 1000}
puts {PATTERN *denominator_b_n_syn_2*}
foreach net [get_nets -hier {*denominator_b_n_syn_2*}] {report_nets $net -connection -pin_display_limit 1000}
puts {PATTERN *armed_n10_syn_2*}
foreach net [get_nets -hier {*armed_n10_syn_2*}] {report_nets $net -connection -pin_display_limit 1000}
puts {PATTERN *monitor_status[12]*}
foreach net [get_nets -hier {*monitor_status[12]*}] {report_nets $net -connection -pin_display_limit 1000}
foreach cell [get_cells -hier {*u_alarm*}] {puts "CELL_BEGIN $cell";report_cells $cell -attributes -connection -pin_loc;puts CELL_END}
puts {CELL_BEGIN system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_25}
set c [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/lease_age_b[15]_syn_25}]
if {[llength $c]>0} {report_cells $c -attributes -connection -pin_loc}
puts CELL_END
puts {CELL_BEGIN system/u_subsys_acq/u_control/u_temperature_pwm/denominator_b_n_syn_2}
set c [get_cells {system/u_subsys_acq/u_control/u_temperature_pwm/denominator_b_n_syn_2}]
if {[llength $c]>0} {report_cells $c -attributes -connection -pin_loc}
puts CELL_END
exit 0
