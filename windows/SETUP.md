# Running the seat checker on a Windows PC

The seat checker has to run on a machine with a residential IP —
`tickets.fandango.com` returns 403 to datacenter addresses, so GitHub Actions
can't do it. An always-on home PC is the right host.

The showtime watcher (new dates) already runs in the cloud and needs nothing here.

---

## 1. Install Python

Get it from <https://www.python.org/downloads/windows/>. During install, tick
**"Add python.exe to PATH"** — the scheduled task won't find it otherwise.

Verify in a new Command Prompt:

```cmd
python --version
```

No packages to install. The scripts use only the standard library.

## 2. Get the code

```cmd
cd %USERPROFILE%
git clone https://github.com/davidrmz1/odyssey-70mm-watch.git
```

No Git? Download the ZIP from the repo page and extract it to
`C:\Users\<you>\odyssey-70mm-watch`.

## 3. Create a scoped token

This is the credential that lets the PC open an alert issue. Make it
**fine-grained** and give it access to nothing else:

1. <https://github.com/settings/personal-access-tokens/new>
2. **Repository access** → *Only select repositories* → `odyssey-70mm-watch`
3. **Permissions** → *Repository permissions* → **Issues: Read and write**
4. Set an expiry past 2026-09-16
5. Generate, and copy the token

Save it beside the scripts as `gh_token.txt`:

```cmd
cd %USERPROFILE%\odyssey-70mm-watch
echo github_pat_YOUR_TOKEN_HERE> gh_token.txt
```

`gh_token.txt` is gitignored, so it will never be committed.

If it leaks, the worst anyone can do is open issues in this one repo. That's the
point — unlike a mail password, it grants no access to anything you care about.

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

Run it once immediately to confirm:

```powershell
Start-ScheduledTask -TaskName "OdysseySeatCheck"
Get-ScheduledTaskInfo -TaskName "OdysseySeatCheck"
```

`LastTaskResult` of `0` means success. Then read `seat_check.log`.

## 6. Turn off the Mac's copy

Two machines sweeping would fight over `seat_state.json` and could double-alert.
On the Mac:

```sh
launchctl unload ~/Library/LaunchAgents/com.davidramirez.odyssey-seats.plist
```

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
| `HTTP 401`/`404` opening the issue | token expired, or lacks Issues: write on this repo |
| Sweep runs, no issue ever | expected — there have been no centre pairs since 2026-08-06 |
