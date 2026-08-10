@echo off
REM Odyssey 70mm seat sweep - Windows runner, driven by Task Scheduler.
REM Seat maps require a residential IP (Fandango 403s datacenter addresses),
REM which is why this runs on a home PC rather than GitHub Actions.

setlocal enabledelayedexpansion

REM Edit this if you cloned somewhere else.
set REPO_DIR=%USERPROFILE%\odyssey-70mm-watch

if not exist "%REPO_DIR%\seat_check.py" (
  echo ERROR: cannot find seat_check.py under "%REPO_DIR%"
  echo Clone the repo there, or edit REPO_DIR at the top of this file.
  exit /b 1
)

cd /d "%REPO_DIR%" || exit /b 1

REM Find a usable interpreter. On Windows "python" is often absent even when
REM Python is installed - only the "py" launcher exists. And Windows ships a
REM stub python.exe that opens the Microsoft Store rather than running anything,
REM so test that the interpreter actually executes instead of trusting the name.
set PYEXE=
for %%P in (py python python3) do (
  if not defined PYEXE (
    %%P -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 set PYEXE=%%P
  )
)

if not defined PYEXE (
  echo ERROR: no working Python found. Tried: py, python, python3
  echo Install from https://www.python.org/downloads/windows/ and TICK
  echo "Add python.exe to PATH" during setup, then open a NEW terminal.
  exit /b 1
)

echo === %DATE% %TIME% starting sweep (using %PYEXE%) >> "%REPO_DIR%\seat_check.log"
%PYEXE% seat_check.py --notify-issue >> "%REPO_DIR%\seat_check.log" 2>&1
set CODE=%ERRORLEVEL%
echo --- exit %CODE% --- >> "%REPO_DIR%\seat_check.log"

REM Publish the sweep results to GitHub. Without this the seat data never
REM leaves this PC: seats.yml has a persist step, but that workflow can never
REM run the sweep (datacenter IPs are 403'd). Deliberately ignores failure --
REM the results are already on disk and the next sweep retries.
%PYEXE% publish_seat_state.py >> "%REPO_DIR%\seat_check.log" 2>&1

REM 0 = nothing new, 10 = centre seats found (issue opened),
REM 2 = every check failed, 3 = found seats but could not open the issue
if "%CODE%"=="2" echo ALL CHECKS FAILED - Fandango may be blocking this machine >> "%REPO_DIR%\seat_check.log"
if "%CODE%"=="3" echo FOUND SEATS BUT COULD NOT ALERT - check the token >> "%REPO_DIR%\seat_check.log"

endlocal
exit /b 0
