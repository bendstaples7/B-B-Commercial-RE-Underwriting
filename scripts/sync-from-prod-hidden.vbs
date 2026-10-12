' Run sync-from-prod.ps1 with no console window.
' Window style 0 stays hidden even when the sync fails.
' The third argument waits so Task Scheduler sees the real exit code.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
script = fso.GetParentFolderName(WScript.ScriptFullName) & "\sync-from-prod.ps1"
ps = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
cmd = """" & ps & """ -NonInteractive -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & script & """"
code = sh.Run(cmd, 0, True)
WScript.Quit code
