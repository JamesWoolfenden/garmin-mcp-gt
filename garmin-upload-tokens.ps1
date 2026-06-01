# garmin-upload-tokens.ps1
# Uploads your local Garmin tokens to the Fuel backend.
# Run after `garmin-setup` to enable Garmin features in the cloud.

param(
    [string]$BackendUrl = "https://fuel-backend-430943803039.europe-west1.run.app",
    [string]$TokenDir   = "$env:USERPROFILE\.garmin_tokens"
)

# Read Firebase API key from ui/.env.local
$envFile = Join-Path $PSScriptRoot "ui\.env.local"
if (-not (Test-Path $envFile)) {
    Write-Error "ui\.env.local not found. Cannot read VITE_FIREBASE_API_KEY."
    exit 1
}
$FirebaseApiKey = (Get-Content $envFile | Select-String "VITE_FIREBASE_API_KEY=(.+)").Matches[0].Groups[1].Value
if (-not $FirebaseApiKey) {
    Write-Error "VITE_FIREBASE_API_KEY not found in ui\.env.local."
    exit 1
}

# ── Validate token directory ──────────────────────────────────────────────────
if (-not (Test-Path $TokenDir)) {
    Write-Error "Token directory not found: $TokenDir. Run garmin-setup first."
    exit 1
}

$tokenFiles = Get-ChildItem $TokenDir -File
if ($tokenFiles.Count -eq 0) {
    Write-Error "No token files found in $TokenDir. Run garmin-setup first."
    exit 1
}

# ── Build token JSON ──────────────────────────────────────────────────────────
$tokens = @{}
foreach ($file in $tokenFiles) {
    $content = Get-Content $file.FullName -Raw
    try {
        $tokens[$file.Name] = $content | ConvertFrom-Json -AsHashtable
    } catch {
        $tokens[$file.Name] = $content
    }
}
$tokensJson = $tokens | ConvertTo-Json -Depth 10 -Compress

# ── Sign in to Firebase ───────────────────────────────────────────────────────
Write-Host "Sign in to your Fuel account to upload tokens."
$email = Read-Host "Email"
$password = Read-Host -AsSecureString "Password"
$passwordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
)

$authBody = @{
    email             = $email
    password          = $passwordPlain
    returnSecureToken = $true
} | ConvertTo-Json

try {
    $authResp = Invoke-RestMethod `
        -Uri "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=$FirebaseApiKey" `
        -Method POST -Body $authBody -ContentType "application/json"
    $idToken = $authResp.idToken
} catch {
    Write-Error "Sign-in failed: $_"
    exit 1
}

# ── Upload tokens ─────────────────────────────────────────────────────────────
Write-Host "Uploading tokens..."
try {
    Invoke-RestMethod `
        -Uri "$BackendUrl/garmin/tokens" `
        -Method PUT `
        -Headers @{ Authorization = "Bearer $idToken" } `
        -Body $tokensJson `
        -ContentType "application/json"
    Write-Host "Tokens uploaded successfully."
} catch {
    Write-Error "Upload failed: $_"
    exit 1
}

# ── Generate MCP API key ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "Generating MCP API key for Claude config..."
try {
    $keyResp = Invoke-RestMethod `
        -Uri "$BackendUrl/garmin/mcp-key" `
        -Method POST `
        -Headers @{ Authorization = "Bearer $idToken" } `
        -ContentType "application/json"

    $mcpKey = $keyResp.key
    Write-Host ""
    Write-Host "Add this to your Claude config (~/.claude/claude_desktop_config.json):"
    Write-Host ""
    Write-Host (@{
        mcpServers = @{
            garmin = @{
                url     = "$BackendUrl/mcp"
                headers = @{ "X-MCP-Key" = $mcpKey }
            }
        }
    } | ConvertTo-Json -Depth 5)
} catch {
    Write-Warning "Could not generate MCP key: $_"
}
