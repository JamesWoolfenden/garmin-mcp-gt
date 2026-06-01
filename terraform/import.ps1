# Import existing GCP resources into Terraform state.
# Run once after `terraform init` to adopt resources created by setup scripts.

$PROJECT = "pike-477416"
$REGION  = "europe-west1"

terraform import google_cloud_run_v2_service.fuel_backend         "projects/$PROJECT/locations/$REGION/services/fuel-backend"
terraform import google_firestore_database.fuel                    "projects/$PROJECT/databases/fuel"
terraform import google_service_account.deploy                     "projects/$PROJECT/serviceAccounts/github-actions-deploy@$PROJECT.iam.gserviceaccount.com"
terraform import google_service_account.scheduler                  "projects/$PROJECT/serviceAccounts/fuel-scheduler@$PROJECT.iam.gserviceaccount.com"
terraform import google_iam_workload_identity_pool.github          "projects/$PROJECT/locations/global/workloadIdentityPools/github-actions"
terraform import google_iam_workload_identity_pool_provider.github "projects/$PROJECT/locations/global/workloadIdentityPools/github-actions/providers/github-oidc"
terraform import google_secret_manager_secret.anthropic_api_key   "projects/$PROJECT/secrets/anthropic-api-key"
terraform import google_secret_manager_secret.garmin_api_secret   "projects/$PROJECT/secrets/garmin-api-secret"
terraform import google_secret_manager_secret.vapid_private_key   "projects/$PROJECT/secrets/vapid-private-key"
terraform import google_secret_manager_secret.internal_secret     "projects/$PROJECT/secrets/fuel-internal-secret"

foreach ($hour in @(8, 13, 15, 20)) {
    terraform import "google_cloud_scheduler_job.nudge[`"$hour`"]" "projects/$PROJECT/locations/$REGION/jobs/fuel-nudge-${hour}h"
}
