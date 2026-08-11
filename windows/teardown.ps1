<#
.SYNOPSIS
    Shut the Odyssey watcher down cleanly once the tickets are booked.

.DESCRIPTION
    Order matters. The deadman runs in GitHub Actions, independent of this PC,
    and opens an assigned issue when heartbeats go stale for 12 hours. Removing
    the scheduled tasks first would therefore alert you about a system you
    deliberately switched off, so the workflow is disabled before anything else.

    Stops:
      - the three scheduled tasks (all checking, and the wake-from-sleep timers)
      - the deadman workflow

    Leaves alone, because they either predate this project or may be wanted
    elsewhere: the gh CLI login, Python, the local checkout, the GitHub repo.
    Commands for those are printed at the end.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File windows\teardown.ps1
#>

[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Continue'
$tasks = 'OdysseyDateWatch', 'OdysseyDateWatchFull', 'OdysseySeatCheck'

Write-Host "Odyssey watcher teardown" -ForegroundColor Cyan
Write-Host "  will disable : deadman.yml (GitHub Actions)"
Write-Host "  will remove  : $($tasks -join ', ')"
Write-Host ""

if (-not $Force) {
    $answer = Read-Host "Proceed? (y/N)"
    if ($answer -notmatch '^[Yy]') { Write-Host "Aborted; nothing changed."; exit 0 }
}

# 1. Deadman first, or it will alert on the shutdown we are about to perform.
Write-Host "`n[1/3] Disabling the deadman workflow..." -ForegroundColor Cyan
if (Get-Command gh -ErrorAction SilentlyContinue) {
    gh workflow disable deadman.yml --repo davidrmz1/odyssey-70mm-watch
    if ($?) { Write-Host "  disabled." } else { Write-Host "  FAILED - disable it by hand in the Actions tab, or you will get stale-watcher issues." -ForegroundColor Yellow }
} else {
    Write-Host "  gh CLI not found. Disable deadman.yml by hand in the Actions tab." -ForegroundColor Yellow
}

# 2. The tasks. This also removes their wake timers, so the PC stops waking up.
Write-Host "`n[2/3] Removing scheduled tasks..." -ForegroundColor Cyan
foreach ($t in $tasks) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Host "  removed $t"
    } else {
        Write-Host "  $t not present (already gone)"
    }
}

# 3. Prove it.
Write-Host "`n[3/3] Verifying..." -ForegroundColor Cyan
$left = Get-ScheduledTask -TaskName 'Odyssey*' -ErrorAction SilentlyContinue
if ($left) {
    Write-Host "  STILL PRESENT: $($left.TaskName -join ', ')" -ForegroundColor Red
} else {
    Write-Host "  no Odyssey tasks remain."
}
Write-Host "  wake timers (needs an elevated prompt to list):"
Write-Host "    powercfg /waketimers"

Write-Host @"

Done. Nothing is checking any more and the PC will stop waking itself.

Optional, none of it required:

  Delete the local checkout (cannot run from inside itself):
    Remove-Item -Recurse -Force "`$env:USERPROFILE\odyssey-70mm-watch"

  Remove the Python installed for this project (skip if you use it elsewhere):
    winget uninstall Python.Python.3.13

  Archive the repo on GitHub, keeping the history:
    gh repo archive davidrmz1/odyssey-70mm-watch

Deliberately untouched: your gh CLI login and git credentials. They predate
this project and other things depend on them.

To start everything again, re-run the steps in windows/SETUP.md and
  gh workflow enable deadman.yml --repo davidrmz1/odyssey-70mm-watch
"@
