#!/bin/bash
# Run once to store secrets in GCP Secret Manager.
# You'll be prompted for each value.

set -e
PROJECT=pike-477416

store_secret() {
  local name=$1
  local prompt=$2
  echo -n "$prompt: "
  read -s value
  echo
  echo -n "$value" | gcloud secrets create $name \
    --data-file=- --project $PROJECT 2>/dev/null || \
  echo -n "$value" | gcloud secrets versions add $name \
    --data-file=- --project $PROJECT
  echo "→ Stored $name"
}

store_secret "anthropic-api-key"  "Anthropic API key"
store_secret "garmin-api-secret"  "Garmin sidecar API secret (from start.bat)"
store_secret "vapid-private-key"  "VAPID private key (from vapid --gen)"

echo ""
echo "All secrets stored. Run deploy.sh next."
