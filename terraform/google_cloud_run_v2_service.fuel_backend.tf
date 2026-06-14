# holden:ignore:HLD_GCP_167 -- public API endpoint; unauthenticated invocations are intentional (Firebase auth enforced in app)
# holden:ignore:HLD_GCP_127 -- ephemeral disk only; persistent data is CMEK-protected via sqlite_data key (GCS) and garmin_tokens key (app-level KMS)
resource "google_cloud_run_v2_service" "fuel_backend" {
  name     = "fuel-backend"
  location = var.region

  template {
    service_account = google_service_account.fuel_backend.email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.image_tag

      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "GARMIN_SIDECAR_URL"
        value = var.garmin_sidecar_url
      }

      env {
        name  = "VAPID_EMAIL"
        value = var.vapid_email
      }

      env {
        name  = "LITESTREAM_GCS_BUCKET"
        value = google_storage_bucket.sqlite.name
      }

      env {
        name = "ANTHROPIC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.anthropic_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "GARMIN_API_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.garmin_api_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "VAPID_PRIVATE_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.vapid_private_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "INTERNAL_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.internal_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "ALLOWED_EMAILS"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.allowed_emails.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "ADMIN_UID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.admin_uid.secret_id
            version = "latest"
          }
        }
      }

    }

    timeout = "30s"
  }

  lifecycle {
    ignore_changes = [
      client,         # set by gcloud, not Terraform
      client_version,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret.anthropic_api_key,
    google_secret_manager_secret.garmin_api_secret,
    google_secret_manager_secret.vapid_private_key,
    google_secret_manager_secret.internal_secret,
    time_sleep.iam_propagation,
  ]
}
