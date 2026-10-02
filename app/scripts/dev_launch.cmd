@echo off
REM Development launcher: opens the window with a console attached so tracebacks stay visible.
REM The delivered entry point is CyDecompilator.exe at the root.
cd /d "%~dp0..\.."
if not exist "runtime\python\Scripts\python.exe" (
  echo The private runtime is missing. See app\README.md.
  pause
  exit /b 1
)
"runtime\python\Scripts\python.exe" "app\desktop.py" %*
pause
