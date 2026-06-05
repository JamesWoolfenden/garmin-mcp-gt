locals {
  deploy_sa    = "github-actions-deploy@${var.project_id}.iam.gserviceaccount.com"
  terraform_sa = "github-actions-terraform@${var.project_id}.iam.gserviceaccount.com"
  scheduler_sa = "fuel-scheduler@${var.project_id}.iam.gserviceaccount.com"
  nudge_hours  = [8, 13, 15, 20]

  backend_secrets = {
    anthropic_api_key = google_secret_manager_secret.anthropic_api_key.id
    garmin_api_secret = google_secret_manager_secret.garmin_api_secret.id
    vapid_private_key = google_secret_manager_secret.vapid_private_key.id
    internal_secret   = google_secret_manager_secret.internal_secret.id
    allowed_emails    = google_secret_manager_secret.allowed_emails.id
    admin_uid         = google_secret_manager_secret.admin_uid.id
  }
}
