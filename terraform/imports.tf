import {
  id = "projects/pike-477416/locations/europe-west1/services/fuel-backend"
  to = google_cloud_run_v2_service.fuel_backend
}

import {
  id = "projects/pike-477416/databases/fuel"
  to = google_firestore_database.fuel
}

import {
  id = "projects/pike-477416/serviceAccounts/github-actions-deploy@pike-477416.iam.gserviceaccount.com"
  to = google_service_account.deploy
}

import {
  id = "projects/pike-477416/serviceAccounts/fuel-scheduler@pike-477416.iam.gserviceaccount.com"
  to = google_service_account.scheduler
}

import {
  id = "projects/pike-477416/locations/global/workloadIdentityPools/github-actions"
  to = google_iam_workload_identity_pool.github
}

import {
  id = "projects/pike-477416/locations/global/workloadIdentityPools/github-actions/providers/github-oidc"
  to = google_iam_workload_identity_pool_provider.github
}

import {
  id = "projects/pike-477416/secrets/anthropic-api-key"
  to = google_secret_manager_secret.anthropic_api_key
}

import {
  id = "projects/pike-477416/secrets/garmin-api-secret"
  to = google_secret_manager_secret.garmin_api_secret
}

import {
  id = "projects/pike-477416/secrets/vapid-private-key"
  to = google_secret_manager_secret.vapid_private_key
}

import {
  id = "projects/pike-477416/secrets/fuel-internal-secret"
  to = google_secret_manager_secret.internal_secret
}

import {
  id = "projects/pike-477416/locations/europe-west1/jobs/fuel-nudge-8h"
  to = google_cloud_scheduler_job.nudge["8"]
}

import {
  id = "projects/pike-477416/locations/europe-west1/jobs/fuel-nudge-13h"
  to = google_cloud_scheduler_job.nudge["13"]
}

import {
  id = "projects/pike-477416/locations/europe-west1/jobs/fuel-nudge-15h"
  to = google_cloud_scheduler_job.nudge["15"]
}

import {
  id = "projects/pike-477416/locations/europe-west1/jobs/fuel-nudge-20h"
  to = google_cloud_scheduler_job.nudge["20"]
}

import {
  id = "projects/pike-477416/serviceAccounts/github-actions-terraform@pike-477416.iam.gserviceaccount.com"
  to = google_service_account.terraform
}

import {
  id = "terraform-pike-bucket-tfstate roles/storage.admin serviceAccount:github-actions-terraform@pike-477416.iam.gserviceaccount.com"
  to = google_storage_bucket_iam_member.terraform_state
}
