#!/bin/bash
# Run once after deploy.sh to set up the nudge scheduler.
# Requires the Cloud Run service URL from deploy.sh output.

set -e

PROJECT=pike-477416
REGION=europe-west1
SERVICE_URL=$(gcloud run services describe fuel-backend \
  --region $REGION --project $PROJECT --format="value(status.url)")

# Get or create a service account for the scheduler
SA=fuel-scheduler@$PROJECT.iam.gserviceaccount.com
gcloud iam service-accounts create fuel-scheduler \
  --display-name "Fuel Cloud Scheduler" \
  --project $PROJECT 2>/dev/null || true

# Allow it to invoke the Cloud Run service
gcloud run services add-iam-policy-binding fuel-backend \
  --region $REGION \
  --project $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/run.invoker"

# Generate a random internal secret and store it
INTERNAL_SECRET=$(python3 -c "import uuid; print(uuid.uuid4())")
echo "Internal secret: $INTERNAL_SECRET"
echo "→ Storing in Secret Manager..."
echo -n "$INTERNAL_SECRET" | gcloud secrets create fuel-internal-secret \
  --data-file=- --project $PROJECT 2>/dev/null || \
echo -n "$INTERNAL_SECRET" | gcloud secrets versions add fuel-internal-secret \
  --data-file=- --project $PROJECT

# Create nudge jobs at 08:00, 13:00, 15:00, 20:00 London time
for HOUR in 8 13 15 20; do
  JOB_NAME="fuel-nudge-${HOUR}h"
  gcloud scheduler jobs create http $JOB_NAME \
    --location $REGION \
    --schedule "0 $HOUR * * *" \
    --time-zone "Europe/London" \
    --uri "$SERVICE_URL/internal/nudge" \
    --http-method POST \
    --oidc-service-account-email $SA \
    --headers "X-Internal-Secret=$INTERNAL_SECRET" \
    --project $PROJECT 2>/dev/null || \
  gcloud scheduler jobs update http $JOB_NAME \
    --location $REGION \
    --uri "$SERVICE_URL/internal/nudge" \
    --headers "X-Internal-Secret=$INTERNAL_SECRET" \
    --project $PROJECT
  echo "→ Scheduled $JOB_NAME"
done

echo "Done. Nudges will fire at 08:00, 13:00, 15:00, 20:00 Europe/London."
