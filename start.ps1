# start.ps1 — starts Garmin sidecar and Cloudflare tunnel
# Place in E:\Code\garmin\
# Run manually or via Task Scheduler (see setup_task.ps1)

$env:API_SECRET = "REDACTED"
$env:PORT = "8080"

Write-Host "[fuel] Starting Garmin sidecar..."
Start-Process powershell -ArgumentList "-NoExit -Command `"cd E:\Code\garmin; `$env:API_SECRET='REDACTED'; `$env:PORT='8080'; python server.py`"" -WindowStyle Normal

Start-Sleep 3

Write-Host "[fuel] Starting Cloudflare tunnel..."
Start-Process powershell -ArgumentList "-NoExit -Command `"cloudflared tunnel run fuel`"" -WindowStyle Normal

Write-Host "[fuel] Both processes started."