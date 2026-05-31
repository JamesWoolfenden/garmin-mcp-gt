# Run once to store secrets in GCP Secret Manager.
# Requires gcloud CLI installed and authenticated.

$PROJECT = "pike-477416"
$UTF8NoBOM = New-Object System.Text.UTF8Encoding $false

function Store-Secret {
    param($Name, $Prompt)
    $value = Read-Host -Prompt $Prompt
    $tmp = New-TemporaryFile
    [IO.File]::WriteAllText($tmp, $value, $UTF8NoBOM)
    gcloud secrets create $Name --data-file=$tmp --project $PROJECT 2>$null
    if ($LASTEXITCODE -ne 0) {
        gcloud secrets versions add $Name --data-file=$tmp --project $PROJECT
    }
    Remove-Item $tmp
    Write-Host "-> Stored $Name"
}

Store-Secret "anthropic-api-key" "Anthropic API key"
Store-Secret "garmin-api-secret" "Garmin sidecar API secret"
Store-Secret "vapid-private-key"  "VAPID private key (from vapid --gen)"

# Generate and store internal secret
$internal = [guid]::NewGuid().ToString()
$tmp = New-TemporaryFile
[IO.File]::WriteAllText($tmp, $internal, $UTF8NoBOM)
gcloud secrets create fuel-internal-secret --data-file=$tmp --project $PROJECT 2>$null
if ($LASTEXITCODE -ne 0) {
    gcloud secrets versions add fuel-internal-secret --data-file=$tmp --project $PROJECT
}
Remove-Item $tmp
Write-Host "-> Stored fuel-internal-secret"
Write-Host ""
Write-Host "All secrets stored. Run deploy.ps1 next."