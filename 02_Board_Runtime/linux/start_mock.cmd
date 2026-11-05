@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 run_edge.py --mock --collector
) else (
  python run_edge.py --mock --collector
)
if errorlevel 1 pause
