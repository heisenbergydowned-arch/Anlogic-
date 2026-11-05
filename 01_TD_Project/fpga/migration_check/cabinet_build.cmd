@echo off
cd /d C:\Users\heisenberg\Desktop\FU_Code\soc_merge\soc_merge
call build_vm.cmd soc_prj > migration_check\cabinet_build_driver.log 2>&1
echo %errorlevel% > migration_check\cabinet_build_exit.txt
