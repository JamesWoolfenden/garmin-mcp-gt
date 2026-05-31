# Deploy the React PWA to Firebase Hosting.
# Run from the frontend (fuel-pwa) directory.
# Prerequisites: npm, firebase-tools, VAPID public key

$PROJECT = "pike-477416"
$BACKEND_URL = "https://fuel-backend-zbq7wtzkjq-ew.a.run.app"

# Prompt for VAPID public key
$VAPID_PUBLIC_KEY = Read-Host "VAPID public key (from vapid --gen output)"

# Write .env.local
$envContent = @"
REACT_APP_API_URL=$BACKEND_URL
REACT_APP_VAPID_PUBLIC_KEY=$VAPID_PUBLIC_KEY
"@
Set-Content -Path ".env.local" -Value $envContent
Write-Host "-> Written .env.local"

# Install deps if needed
if (-not (Test-Path "node_modules")) {
    Write-Host "-> Installing npm dependencies..."
    npm install
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

# Build
Write-Host "-> Building PWA..."
npm run build
if ($LASTEXITCODE -ne 0) { exit 1 }

# Install firebase-tools if not present
if (-not (Get-Command firebase -ErrorAction SilentlyContinue)) {
    Write-Host "-> Installing firebase-tools..."
    npm install -g firebase-tools
}

# Login and deploy
Write-Host "-> Deploying to Firebase Hosting..."
firebase login
firebase use $PROJECT
firebase deploy --only hosting

Write-Host ""
Write-Host "Done. Your PWA is live."
firebase hosting:channel:list 2>$null
