# start.ps1 — starts Garmin sidecar and Cloudflare tunnel
# Place in E:\Code\garmin\
# Run manually or via Task Scheduler (see setup_task.ps1)
# Put API_SECRET=<value> in .env.local (gitignored) in this directory

$envFile = Join-Path $PSScriptRoot "backend\.env.local"
if (-not (Test-Path $envFile)) {
    Write-Error ".env.local not found. Create it with API_SECRET=<your-secret>."
    exit 1
}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), "Process")
    }
}

$env:PORT = "8080"

Write-Host "[fuel] Starting Garmin sidecar..."
Start-Process powershell -ArgumentList "-NoExit -Command `"cd E:\Code\garmin; python server.py`"" -WindowStyle Normal

Start-Sleep 3

Write-Host "[fuel] Starting Cloudflare tunnel..."
Start-Process powershell -ArgumentList "-NoExit -Command `"cloudflared tunnel run fuel`"" -WindowStyle Normal

Write-Host "[fuel] Both processes started."
