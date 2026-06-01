# garmin-upload-tokens.ps1
# Uploads your local Garmin tokens to the Fuel backend.
#
# Usage:
#   1. In the Fuel app, tap "Connect Garmin" to generate an upload token
#   2. Run: .\garmin-upload-tokens.ps1 -UploadToken "your-token-here"

param(
    [Parameter(Mandatory)][string]$UploadToken,
    [string]$BackendUrl = "https://fuel-backend-430943803039.europe-west1.run.app",
    [string]$TokenDir   = "$env:USERPROFILE\.garmin_tokens"
)

if (-not (Test-Path $TokenDir)) {
    Write-Error "Token directory not found: $TokenDir. Run garmin-setup first."
    exit 1
}

$tokenFiles = Get-ChildItem $TokenDir -File
if ($tokenFiles.Count -eq 0) {
    Write-Error "No token files found in $TokenDir. Run garmin-setup first."
    exit 1
}

$tokens = @{}
foreach ($file in $tokenFiles) {
    $content = Get-Content $file.FullName -Raw
    try { $tokens[$file.Name] = $content | ConvertFrom-Json -AsHashtable }
    catch { $tokens[$file.Name] = $content }
}
$tokensJson = $tokens | ConvertTo-Json -Depth 10 -Compress

Write-Host "Uploading Garmin tokens..."
try {
    Invoke-RestMethod `
        -Uri "$BackendUrl/garmin/tokens/upload" `
        -Method PUT `
        -Headers @{ "X-Upload-Token" = $UploadToken } `
        -Body $tokensJson `
        -ContentType "application/json"
    Write-Host "Done. Your Garmin data is now available in the Fuel app."
} catch {
    Write-Error "Upload failed: $_"
    exit 1
}
