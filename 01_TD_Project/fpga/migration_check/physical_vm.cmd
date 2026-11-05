@echo off
cd /d "C:\Users\heisenberg\Desktop\FU_Code\soc_merge\soc_merge"
"C:\Anlogic\TD_Release_2026.1_SP2.200.067\bin\td_commands_prompt.exe" migration_check/physical_vm.tcl < nul > migration_check\soc_prj_physical.log 2>&1
echo %errorlevel% > migration_check\physical_exit.txt
