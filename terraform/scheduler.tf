locals {
  nudge_hours = [8, 13, 15, 20]
}

resource "google_cloud_scheduler_job" "nudge" {
  for_each = toset([for h in local.nudge_hours : tostring(h)])

  name      = "fuel-nudge-${each.key}h"
  region    = var.region
  schedule  = "0 ${each.key} * * *"
  time_zone = "Europe/London"

  http_target {
    uri         = "${google_cloud_run_v2_service.fuel_backend.uri}/internal/nudge"
    http_method = "POST"

    headers = {
      X-Internal-Secret = "managed-by-scheduler-sa-oidc"
    }

    oidc_token {
      service_account_email = local.scheduler_sa
      audience              = google_cloud_run_v2_service.fuel_backend.uri
    }
  }

  depends_on = [google_cloud_run_v2_service_iam_member.scheduler_invoker]
}
