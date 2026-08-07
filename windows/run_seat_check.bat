@echo off
REM Odyssey 70mm seat sweep - Windows runner, driven by Task Scheduler.
REM Seat maps require a residential IP (Fandango 403s datacenter addresses),
REM which is why this runs on a home PC rather than GitHub Actions.

setlocal

REM Edit this if you cloned somewhere else.
set REPO_DIR=%USERPROFILE%\odyssey-70mm-watch

cd /d "%REPO_DIR%" || exit /b 1

echo === %DATE% %TIME% starting sweep >> "%REPO_DIR%\seat_check.log"
python seat_check.py --notify-issue >> "%REPO_DIR%\seat_check.log" 2>&1
set CODE=%ERRORLEVEL%
echo --- exit %CODE% --- >> "%REPO_DIR%\seat_check.log"

REM 0 = nothing new, 10 = centre seats found (issue opened),
REM 2 = every check failed, 3 = found seats but could not open the issue
if "%CODE%"=="2" echo ALL CHECKS FAILED - Fandango may be blocking this machine >> "%REPO_DIR%\seat_check.log"
if "%CODE%"=="3" echo FOUND SEATS BUT COULD NOT ALERT - check the token >> "%REPO_DIR%\seat_check.log"

endlocal
exit /b 0
