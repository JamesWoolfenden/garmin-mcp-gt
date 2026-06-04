#!/bin/bash
set -e

PROJECT=pike-477416
REGION=europe-west1
SERVICE=fuel-backend
IMAGE=gcr.io/$PROJECT/$SERVICE

echo "→ Building image..."
gcloud builds submit --tag $IMAGE --project $PROJECT

echo "→ Deploying to Cloud Run..."
gcloud run deploy $SERVICE \
  --image $IMAGE \
  --platform managed \
  --region $REGION \
  --project $PROJECT \
  --no-allow-unauthenticated \
  --set-secrets="\
ANTHROPIC_API_KEY=anthropic-api-key:latest,\
VAPID_PRIVATE_KEY=vapid-private-key:latest,\
INTERNAL_SECRET=fuel-internal-secret:latest" \
  --set-env-vars="VAPID_EMAIL=james.woolfenden@gmail.com" \
  --min-instances=0 \
  --max-instances=2 \
  --memory=512Mi \
  --timeout=30

echo "→ Done. Service URL:"
gcloud run services describe $SERVICE --region $REGION --project $PROJECT \
  --format="value(status.url)"
