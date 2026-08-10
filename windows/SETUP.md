# Running the seat checker on a Windows PC

The seat checker has to run on a machine with a residential IP —
`tickets.fandango.com` returns 403 to datacenter addresses, so GitHub Actions
can't do it. An always-on home PC is the right host.

The showtime watcher (new dates) already runs in the cloud and needs nothing here.

---

## 1. Install Python

Get it from <https://www.python.org/downloads/windows/>. During install, tick
**"Add python.exe to PATH"** — the scheduled task won't find it otherwise.

Verify in a **new** Command Prompt (a terminal opened before installing won't
have the updated PATH):

```cmd
python --version
```

If that prints nothing, opens the Microsoft Store, or says *not recognized*, try
the Python Launcher instead:

```cmd
py --version
```

Either one is fine — the runner script auto-detects `py`, `python` or `python3`.
If neither works, Python isn't installed or isn't on PATH: reinstall from
python.org and make sure **"Add python.exe to PATH"** is ticked.

To see what Windows is actually resolving:

```cmd
where python
where py
```

A `python` that resolves to `...\WindowsApps\python.exe` is Microsoft's stub,
not a real install.

No packages to install. The scripts use only the standard library.

## 2. Get the code

```cmd
cd %USERPROFILE%
git clone https://github.com/davidrmz1/odyssey-70mm-watch.git
```

No Git? Download the ZIP from the repo page and extract it to
`C:\Users\<you>\odyssey-70mm-watch`.

## 3. Create a scoped token

This is the credential that lets the PC fire an alert.

The PC does **not** open the issue itself. GitHub sends no notification for your
own activity, so an issue created with your own token assigns you, @mentions
you, and notifies nobody — it just sits in the repo unread. Verified 2026-08-10:
bot-authored issues #3/#4 each produced a `mention` notification; self-authored
#5 produced none. Instead the PC dispatches `.github/workflows/alert.yml` and
`github-actions[bot]` opens the issue, which does notify.

So the permission needed is **Actions: write** (to dispatch), *not* Issues:
write — the bot supplies the issue permission on the runner side.

**If the `gh` CLI is installed and logged in, you can skip this whole step** —
`notify_issue.py` falls back to it, and gh's token already carries `workflow`
scope. That is how this PC is currently set up.

Otherwise, make it **fine-grained** and give it access to nothing else:

1. <https://github.com/settings/personal-access-tokens/new>
2. **Repository access** → *Only select repositories* → `odyssey-70mm-watch`
3. **Permissions** → *Repository permissions* → **Actions: Read and write**
4. Set an expiry past 2026-09-16
5. Generate, and copy the token

Save it beside the scripts as `gh_token.txt`:

```cmd
cd %USERPROFILE%\odyssey-70mm-watch
echo github_pat_YOUR_TOKEN_HERE> gh_token.txt
```

`gh_token.txt` is gitignored, so it will never be committed.

If it leaks, the worst anyone can do is trigger workflows in this one repo.
That's the point — unlike a mail password, it grants no access to anything you
care about. (Note this is a slightly wider blast radius than the Issues-only
token this step used to ask for: dispatching a workflow runs code. Still
confined to this repo.)

Check it's found:

```cmd
python notify_issue.py
```

Should print `token: found via gh_token.txt`.

## 4. Test a sweep

```cmd
python seat_check.py --date 2026-09-14
```

Takes a few seconds per showtime. If it prints seat counts, the PC's IP is
accepted and everything works. If you get `ERROR HTTPError: HTTP Error 403`,
this machine is being blocked too — tell Claude.

## 5. Schedule it every 2 hours

Run **PowerShell as Administrator** and paste:

```powershell
$bat = "$env:USERPROFILE\odyssey-70mm-watch\windows\run_seat_check.bat"
$action  = New-ScheduledTaskAction -Execute $bat
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
           -RepetitionInterval (New-TimeSpan -Hours 2)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
            -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
            -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "OdysseySeatCheck" -Action $action `
  -Trigger $trigger -Settings $settings -Description "Odyssey 70mm centre-seat watch"
```

`-StartWhenAvailable` catches up a missed run after downtime, and `-WakeToRun`
lets the PC wake from sleep for it.

Each sweep then runs `publish_seat_state.py`, which commits and pushes
`seat_state.json` so the results land in the repo rather than staying on this
PC. It no-ops when nothing changed, and a push failure is logged but never
fails the sweep. This needs git to be able to push without a prompt — it uses
the credential manager already set up by `git clone`, and sets
`GIT_TERMINAL_PROMPT=0` so a headless run fails fast instead of hanging on a
credential dialog.

### The two date-scan tasks

The showtime scan runs here too. It needs no residential IP — it moved off
Actions purely for reliability, after GitHub delivered ~17% of its schedule (40
runs in 55h against ~239 expected, worst gap 5.9h). `watch.yml`'s cron is
commented out so the two never double-alert or fight over `state.json`.

```powershell
$bat = "$env:USERPROFILE\odyssey-70mm-watch\windows\run_watch_dates.bat"
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
     -AllowStartIfOnBatteries -WakeToRun -MultipleInstances IgnoreNew `
     -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName "OdysseyDateWatch" `
  -Action (New-ScheduledTaskAction -Execute $bat -Argument "frontier") `
  -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 15)) `
  -Settings $s -Description "Odyssey 70mm new-showtime scan (frontier, 15 min)"

Register-ScheduledTask -TaskName "OdysseyDateWatchFull" `
  -Action (New-ScheduledTaskAction -Execute $bat -Argument "full") `
  -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(7) `
            -RepetitionInterval (New-TimeSpan -Hours 2)) `
  -Settings $s -Description "Odyssey 70mm new-showtime scan (full 60d, 2h)"
```

`-MultipleInstances IgnoreNew` matters on the 15-minute task: a slow run must
never stack on itself. The full scan starts 7 minutes off the quarter-hour so it
rarely collides with a frontier run.

### No console window

Register the actions through `run_hidden.vbs`, not the `.bat` directly:

```powershell
$vbs = "$env:USERPROFILE\odyssey-70mm-watch\windows\run_hidden.vbs"
New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" `
  -Argument ('"{0}" "{1}" frontier' -f $vbs, $bat)
```

The runners are `.bat` files, so they run via `cmd.exe`, and these tasks use
`LogonType=Interactive` — a console app in the desktop session always gets a
visible window. At 15-minute cadence that is four popups an hour, including on
wake-from-sleep. Task Scheduler's `-Hidden` does *not* fix this; it hides the
task from the Task Scheduler list, not the window.

Do **not** "solve" it by switching to *run whether user is logged on or not*.
That needs a stored password or an S4U logon, and S4U cannot unlock DPAPI — the
gh token and the git credential helper both live in Windows Credential Manager
behind DPAPI, so alerting and pushing would silently break.

Run it once immediately to confirm:

```powershell
Start-ScheduledTask -TaskName "OdysseySeatCheck"
Get-ScheduledTaskInfo -TaskName "OdysseySeatCheck"
```

`LastTaskResult` of `0` means success. Then read `seat_check.log`.

## 6. The Mac's copy — retired 2026-08-10

Done; nothing to do here. The Mac's checkout and its launchd agent were deleted,
so this PC is the only machine running anything. Two machines sweeping would
have fought over `seat_state.json` and double-alerted.

Its runner (`run_seat_check.sh`) was removed with it. That script opened alert
issues directly via `gh issue create`, which is the self-authored path that
notifies nobody — see step 3. Anything reviving a second machine must dispatch
`alert.yml` the way `notify_issue.py` does, not post the issue itself.

With one machine doing everything, `deadman.yml` is what tells you if it stops.

---

## Alerts

When a showtime gains a centred pair, the PC opens a GitHub issue that is
**assigned to you and @mentions you**. Both are required: the GitHub mobile app
has no push category for "issue in a repo you watch", so an unassigned issue
never reaches your phone.

Make sure **Direct Mentions** and **Assigned** are enabled in the app under
Settings → Notifications.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Task result `0x1` | `python` not on PATH — reinstall with the PATH box ticked |
| `no token: set GITHUB_TOKEN...` | `gh_token.txt` missing, empty, or has a trailing newline |
| `HTTP 403` from Fandango | this PC's IP is blocked too |
| `HTTP 401`/`404` dispatching the alert | token expired, or lacks Actions: write on this repo |
| `HTTP 422` dispatching the alert | `alert.yml` isn't on `main` yet — workflow_dispatch only resolves workflows on the default branch |
| Log says `dispatched`, but no issue | the alert run failed on the runner; check the Actions tab. A failed run also pushes its own "Workflow Runs" notification |
| Issue appears but no phone push | check it was authored by `github-actions`, not you — a self-authored issue never notifies |
| Sweep runs, no issue ever | expected — there have been no centre pairs since 2026-08-06 |
