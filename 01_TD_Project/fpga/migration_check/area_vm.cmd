@echo off
cd /d "C:\Users\heisenberg\Desktop\FU_Code\soc_merge\soc_merge"
"C:\Anlogic\TD_Release_2026.1_SP2.200.067\bin\td_commands_prompt.exe" migration_check/area_vm.tcl > migration_check/area_vm.log 2>&1
echo %ERRORLEVEL% > migration_check/area_exit.txt