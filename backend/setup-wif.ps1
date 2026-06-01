# Set up Workload Identity Federation for GitHub Actions — run once.
# After running, add these as GitHub Actions repository variables:
#   WIF_PROVIDER  — printed at the end
#   DEPLOY_SA     — printed at the end
#   VITE_API_URL  — https://fuel-backend-zbq7wtzkjq-ew.a.run.app
#   VITE_VAPID_PUBLIC_KEY — the URL-safe base64 application server key

$PROJECT    = "pike-477416"
$REPO       = "JamesWoolfenden/garmin-mcp-gt"
$POOL_ID    = "github-actions"
$PROVIDER_ID = "github"
$SA_NAME    = "github-actions-deploy"
$REGION     = "europe-west1"

$PROJECT_NUMBER = gcloud projects describe $PROJECT --format="value(projectNumber)"
$SA_EMAIL = "$SA_NAME@$PROJECT.iam.gserviceaccount.com"

Write-Host "-> Creating Workload Identity Pool..."
gcloud iam workload-identity-pools create $POOL_ID `
  --project $PROJECT `
  --location global `
  --display-name "GitHub Actions" 2>$null

Write-Host "-> Creating OIDC provider..."
gcloud iam workload-identity-pools providers create-oidc $PROVIDER_ID `
  --project $PROJECT `
  --location global `
  --workload-identity-pool $POOL_ID `
  --display-name "GitHub" `
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" `
  --issuer-uri "https://token.actions.githubusercontent.com" 2>$null

Write-Host "-> Creating service account..."
gcloud iam service-accounts create $SA_NAME `
  --project $PROJECT `
  --display-name "GitHub Actions Deploy" 2>$null

Write-Host "-> Granting permissions..."
foreach ($role in @(
    "roles/run.developer",
    "roles/cloudbuild.builds.editor",
    "roles/storage.admin",
    "roles/secretmanager.secretAccessor",
    "roles/iam.serviceAccountUser",
    "roles/firebasehosting.admin"
)) {
    gcloud projects add-iam-policy-binding $PROJECT `
      --member "serviceAccount:$SA_EMAIL" `
      --role $role | Out-Null
    Write-Host "   $role"
}

Write-Host "-> Binding WIF pool to service account for repo $REPO..."
gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL `
  --project $PROJECT `
  --role roles/iam.workloadIdentityUser `
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_ID/attribute.repository/$REPO"

$WIF_PROVIDER = "projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_ID/providers/$PROVIDER_ID"

Write-Host ""
Write-Host "Done. Add these as GitHub Actions repository variables (Settings -> Secrets and variables -> Variables):"
Write-Host ""
Write-Host "  WIF_PROVIDER  = $WIF_PROVIDER"
Write-Host "  DEPLOY_SA     = $SA_EMAIL"
Write-Host "  VITE_API_URL  = https://fuel-backend-zbq7wtzkjq-ew.a.run.app"
Write-Host "  VITE_VAPID_PUBLIC_KEY = BHpT6uAIFFM6p-8B8GgYUNAr_HoXGd_ITXXlYXYEnhr6rCRkKlE_m5R7fIgFDoY0-MYaQQNz7r_DZ2aCgb-pm5A"
