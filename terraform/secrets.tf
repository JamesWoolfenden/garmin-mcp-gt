# Secret resources only — values are populated manually via setup_secrets.ps1.
# Never store secret values in Terraform state.
#
# Per-secret IAM: intentionally NOT using a project-level secretmanager.secretAccessor
# so new secrets added to the project are not automatically accessible to the backend SA.

resource "google_secret_manager_secret_iam_member" "backend_access" {
  for_each = local.backend_secrets

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.fuel_backend.email}"
}

# holden:ignore:HLD_GCP_123 -- auto replication does not support CMEK; user_managed replication would require pinning regions
resource "google_secret_manager_secret" "anthropic_api_key" {
  secret_id = "anthropic-api-key"
  replication {
    auto {}
  }
}

# holden:ignore:HLD_GCP_123 -- auto replication does not support CMEK; user_managed replication would require pinning regions
resource "google_secret_manager_secret" "garmin_api_secret" {
  secret_id = "garmin-api-secret"
  replication {
    auto {}
  }
}

# holden:ignore:HLD_GCP_123 -- auto replication does not support CMEK; user_managed replication would require pinning regions
resource "google_secret_manager_secret" "vapid_private_key" {
  secret_id = "vapid-private-key"
  replication {
    auto {}
  }
}

# holden:ignore:HLD_GCP_123 -- auto replication does not support CMEK; user_managed replication would require pinning regions
resource "google_secret_manager_secret" "internal_secret" {
  secret_id = "fuel-internal-secret"
  replication {
    auto {}
  }
}

# holden:ignore:HLD_GCP_123 -- auto replication does not support CMEK; user_managed replication would require pinning regions
resource "google_secret_manager_secret" "allowed_emails" {
  secret_id = "fuel-allowed-emails"
  replication {
    auto {}
  }
}

# holden:ignore:HLD_GCP_123 -- auto replication does not support CMEK; user_managed replication would require pinning regions
resource "google_secret_manager_secret" "admin_uid" {
  secret_id = "fuel-admin-uid"
  replication {
    auto {}
  }
}

