locals {
  deploy_sa    = google_service_account.deploy.email
  terraform_sa = google_service_account.terraform.email
  scheduler_sa = google_service_account.scheduler.email
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
