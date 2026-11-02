# Runs LenBot at logon through Task Scheduler; stop asks the launcher, which stops the host before exiting.
param([Parameter(Mandatory)][ValidateSet('install', 'uninstall', 'start', 'stop', 'status')][string]$Action)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Name = 'LenBot'
switch ($Action) {
  'install' {
    $run = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $Root 'run.ps1') + '"')
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $Name -Action $run -Trigger $logon -Settings $settings -Force | Out-Null
  }
  'uninstall' { Unregister-ScheduledTask -TaskName $Name -Confirm:$false }
  'start' { Start-ScheduledTask -TaskName $Name }
  'stop' {
    New-Item -ItemType Directory -Force (Join-Path $Root 'updates') | Out-Null
    Set-Content -Encoding UTF8 (Join-Path $Root 'updates/stop') ''
  }
  'status' { Get-ScheduledTask -TaskName $Name | Get-ScheduledTaskInfo }
}
