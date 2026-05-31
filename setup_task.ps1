# setup_task.ps1 — registers FuelSidecar as a Task Scheduler job
# Run once in an elevated PowerShell (right-click -> Run as Administrator)

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File E:\Code\garmin\start.ps1"

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
  -TaskName "FuelSidecar" `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Starts Garmin sidecar and Cloudflare tunnel for Fuel PWA" `
  -RunLevel Highest `
  -Force

Write-Host "Task registered. FuelSidecar will start automatically at login."