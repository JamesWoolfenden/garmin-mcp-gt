# Run once after deploy.ps1 to set up Cloud Scheduler nudge jobs.
# Uses OIDC auth - no shared secret header needed.
$PROJECT = "pike-477416"
$REGION  = "europe-west1"
$SA      = "fuel-scheduler@$PROJECT.iam.gserviceaccount.com"

# Get Cloud Run service URL
$SERVICE_URL = gcloud run services describe fuel-backend `
  --region $REGION --project $PROJECT --format="value(status.url)"
Write-Host "-> Service URL: $SERVICE_URL"

# Create scheduler service account (ignore if exists)
gcloud iam service-accounts create fuel-scheduler `
  --display-name "Fuel Cloud Scheduler" `
  --project $PROJECT 2>$null

# Allow it to invoke Cloud Run
gcloud run services add-iam-policy-binding fuel-backend `
  --region $REGION `
  --project $PROJECT `
  --member="serviceAccount:$SA" `
  --role="roles/run.invoker"

# Create nudge jobs using OIDC auth
foreach ($HOUR in @(8, 13, 15, 20)) {
    $JOB_NAME = "fuel-nudge-${HOUR}h"
    Write-Host "-> Scheduling $JOB_NAME..."

    gcloud scheduler jobs create http $JOB_NAME `
      --location $REGION `
      --schedule "0 $HOUR * * *" `
      --time-zone "Europe/London" `
      --uri "$SERVICE_URL/internal/nudge" `
      --http-method POST `
      --oidc-service-account-email $SA `
      --oidc-token-audience $SERVICE_URL `
      --project $PROJECT 2>$null

    if ($LASTEXITCODE -ne 0) {
        Write-Host "   (already exists, updating...)"
        gcloud scheduler jobs update http $JOB_NAME `
          --location $REGION `
          --schedule "0 $HOUR * * *" `
          --time-zone "Europe/London" `
          --uri "$SERVICE_URL/internal/nudge" `
          --http-method POST `
          --oidc-service-account-email $SA `
          --oidc-token-audience $SERVICE_URL `
          --project $PROJECT
    }
}

Write-Host ""
Write-Host "Done. Nudges scheduled at 08:00, 13:00, 15:00, 20:00 Europe/London."
