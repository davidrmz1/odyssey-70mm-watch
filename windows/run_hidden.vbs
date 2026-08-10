' Launch a command with no visible console window, wait for it, and pass its
' exit code back to Task Scheduler.
'
' The runners are .bat files, so they execute via cmd.exe -- a console app. The
' tasks use LogonType=Interactive (they run in the desktop session), and a
' console app in an interactive session always gets a visible window. At the
' 15-minute cadence that meant a window popping up four times an hour.
'
' The usual fix -- "run whether user is logged on or not" -- would put the task
' in session 0 with no window, but that needs a stored password or S4U logon,
' and S4U cannot unlock DPAPI. The gh token and the git credential helper both
' live in Windows Credential Manager behind DPAPI, so that would silently break
' alerting and pushing. Hiding the window is the cheaper trade.
'
' Anything the batch file spawns (python, git, gh) inherits this hidden console,
' so no child flashes a window either.
'
' Usage: wscript.exe run_hidden.vbs "C:\path\to\thing.bat" [args...]

Option Explicit

Dim shell, cmd, i
Set shell = CreateObject("WScript.Shell")

If WScript.Arguments.Count < 1 Then
  WScript.Quit 1
End If

cmd = """" & WScript.Arguments(0) & """"
For i = 1 To WScript.Arguments.Count - 1
  cmd = cmd & " " & WScript.Arguments(i)
Next

' 0 = hidden window, True = wait so the task's duration and result are real
' (and so MultipleInstances=IgnoreNew can actually prevent overlap).
WScript.Quit shell.Run(cmd, 0, True)
