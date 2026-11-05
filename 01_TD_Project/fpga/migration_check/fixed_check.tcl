cd [file normalize [file join [file dirname [info script]] ..]]
import_device dr1_90.db -package DR1M90GEG400 -speed 2
if {[catch {
  open_project soc_prj.al
  elaborate -top system_top
} problem options]} {
  puts stderr "MIGRATION_CHECK_FAILED: $problem"
  exit 1
}
puts "MIGRATION_ELABORATE_PASS"
exit 0