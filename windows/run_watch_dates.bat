@echo off
REM Odyssey 70mm showtime (new-dates) scan - Windows runner, Task Scheduler.
REM
REM Runs here rather than in Actions because GitHub dropped ~83% of the
REM scheduled runs (40 of ~239 expected over 55h, worst gap 5.9h). This scan
REM needs no residential IP - unlike the seat sweep - it moved for reliability.
REM
REM Usage: run_watch_dates.bat [frontier|full]     (default: frontier)

setlocal enabledelayedexpansion

set REPO_DIR=%USERPROFILE%\odyssey-70mm-watch

set MODE=%~1
if "%MODE%"=="" set MODE=frontier

if not exist "%REPO_DIR%\watch_dates.py" (
  echo ERROR: cannot find watch_dates.py under "%REPO_DIR%"
  exit /b 1
)

pushd "%REPO_DIR%" || exit /b 1

REM Same interpreter probe as the seat runner: Windows ships a stub python.exe
REM that opens the Microsoft Store, so test that it actually executes.
set PYEXE=
for %%P in (py python python3) do (
  if not defined PYEXE (
    %%P -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 set PYEXE=%%P
  )
)

if not defined PYEXE (
  echo ERROR: no working Python found. Tried: py, python, python3
  exit /b 1
)

REM Keep the log from growing without bound; this runs every 15 minutes.
%PYEXE% rotate_log.py watch_dates.log >nul 2>&1

echo === %DATE% %TIME% starting date scan mode=%MODE% (using %PYEXE%) >> "%REPO_DIR%\watch_dates.log"
%PYEXE% watch_dates.py %MODE% >> "%REPO_DIR%\watch_dates.log" 2>&1
set CODE=%ERRORLEVEL%
echo --- exit %CODE% --- >> "%REPO_DIR%\watch_dates.log"

REM Publish the scan results. Nothing in Actions commits state.json anymore.
REM Only the 2-hourly full scan stamps the heartbeat: the heartbeat always
REM changes, so stamping it every 15 minutes would mean ~96 commits a day.
set HB=
if /I "%MODE%"=="full" set HB=--heartbeat dates
%PYEXE% publish_state.py --file state.json --message "state: horizon update" %HB% >> "%REPO_DIR%\watch_dates.log" 2>&1

if "%CODE%"=="2" echo ALL DATE REQUESTS FAILED - endpoint may have changed >> "%REPO_DIR%\watch_dates.log"
if "%CODE%"=="3" echo FOUND SHOWTIMES BUT COULD NOT ALERT - check the token >> "%REPO_DIR%\watch_dates.log"

popd
endlocal
exit /b 0
