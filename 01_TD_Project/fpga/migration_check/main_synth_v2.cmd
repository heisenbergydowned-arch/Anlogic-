@echo off
cd /d "C:\Users\heisenberg\Desktop\FU_Code\soc_merge\soc_merge"
call synth_vm.cmd soc_prj
echo %errorlevel% > migration_check\main_synth_exit_v2.txt
