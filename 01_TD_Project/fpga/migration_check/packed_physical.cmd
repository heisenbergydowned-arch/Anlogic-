@echo off
cd /d "C:\Users\heisenberg\Desktop\FU_Code\soc_merge\soc_merge"
"C:\Anlogic\TD_Release_2026.1_SP2.200.067\bin\td_commands_prompt.exe" migration_check/packed_physical.tcl > migration_check/packed_physical.log 2>&1
echo %ERRORLEVEL% > migration_check/packed_physical_exit.txt