@echo off
cd /d C:\Users\heisenberg\Desktop\FU_Code\soc_merge\soc_merge
"C:\Anlogic\TD_Release_2026.1_SP2.200.067\bin\td_commands_prompt.exe" migration_check/resume_vm_postroute.tcl <nul > migration_check/postroute_verified.log 2>&1
echo %errorlevel% > migration_check/postroute_verified_exit.txt