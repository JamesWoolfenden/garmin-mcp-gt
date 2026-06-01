# Secret resources only — values are populated manually via setup_secrets.ps1.
# Never store secret values in Terraform state.

resource "google_secret_manager_secret" "anthropic_api_key" {
  secret_id = "anthropic-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "garmin_api_secret" {
  secret_id = "garmin-api-secret"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "vapid_private_key" {
  secret_id = "vapid-private-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "internal_secret" {
  secret_id = "fuel-internal-secret"
  replication {
    auto {}
  }
}

