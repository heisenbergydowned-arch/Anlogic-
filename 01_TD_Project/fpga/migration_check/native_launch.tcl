cd {C:/Users/heisenberg/Desktop/FU_Code/soc_merge/soc_merge}
import_device dr1_90.db -package DR1M90GEG400 -speed 2
open_project vm_gui_probe.al
elaborate -top system_top
launch_runs syn_1 -step read_design -jobs 1
puts VM_NATIVE_LAUNCH_RETURNED
wait_run syn_1
exit 0
