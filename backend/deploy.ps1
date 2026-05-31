# Build and deploy fuel-backend to Cloud Run.
$PROJECT = "pike-477416"
$REGION  = "europe-west1"
$SERVICE = "fuel-backend"
$IMAGE   = "gcr.io/$PROJECT/$SERVICE"
$SA      = "430943803039-compute@developer.gserviceaccount.com"

# Enable required GCP APIs
Write-Host "-> Enabling required APIs..."
$apis = @(
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com"
)
foreach ($api in $apis) {
    gcloud services enable $api --project $PROJECT | Out-Null
    Write-Host "   $api"
}


# Grant Secret Manager access to Cloud Run service account
Write-Host "-> Granting Secret Manager access..."
gcloud projects add-iam-policy-binding $PROJECT `
  --member="serviceAccount:$SA" `
  --role="roles/secretmanager.secretAccessor" | Out-Null

Write-Host "-> Building image..."
gcloud builds submit --tag $IMAGE --project $PROJECT
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "-> Deploying to Cloud Run..."
gcloud run deploy $SERVICE `
  --image $IMAGE `
  --platform managed `
  --region $REGION `
  --project $PROJECT `
  --allow-unauthenticated `
  --set-secrets="ANTHROPIC_API_KEY=anthropic-api-key:latest,GARMIN_API_SECRET=garmin-api-secret:latest,VAPID_PRIVATE_KEY=vapid-private-key:latest,INTERNAL_SECRET=fuel-internal-secret:latest" `
  --set-env-vars="GARMIN_SIDECAR_URL=https://fuel.wlfdn.dev,VAPID_EMAIL=james.woolfenden@gmail.com" `
  --min-instances=0 `
  --max-instances=2 `
  --memory=512Mi `
  --timeout=30

if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "-> Allowing unauthenticated access..."
gcloud run services add-iam-policy-binding $SERVICE `
  --region $REGION `
  --project $PROJECT `
  --member="allUsers" `
  --role="roles/run.invoker" | Out-Null

Write-Host "-> Done. Service URL:"
gcloud run services describe $SERVICE --region $REGION --project $PROJECT `
  --format="value(status.url)"
