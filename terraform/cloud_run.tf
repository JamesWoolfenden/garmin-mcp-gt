resource "google_cloud_run_v2_service" "fuel_backend" {
  name     = "fuel-backend"
  location = var.region

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = "gcr.io/${var.project_id}/fuel-backend:latest"

      resources {
        limits = { memory = "512Mi" }
      }

      env {
        name  = "GARMIN_SIDECAR_URL"
        value = var.garmin_sidecar_url
      }

      env {
        name  = "VAPID_EMAIL"
        value = var.vapid_email
      }

      dynamic "env" {
        for_each = {
          ANTHROPIC_API_KEY = google_secret_manager_secret.anthropic_api_key.secret_id
          GARMIN_API_SECRET = google_secret_manager_secret.garmin_api_secret.secret_id
          VAPID_PRIVATE_KEY = google_secret_manager_secret.vapid_private_key.secret_id
          INTERNAL_SECRET   = google_secret_manager_secret.internal_secret.secret_id
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
    }

    timeout = "30s"
  }

  lifecycle {
    # Image tag is managed by CI — prevent Terraform from reverting deploys
    ignore_changes = [template[0].containers[0].image]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret.anthropic_api_key,
    google_secret_manager_secret.garmin_api_secret,
    google_secret_manager_secret.vapid_private_key,
    google_secret_manager_secret.internal_secret,
  ]
}
