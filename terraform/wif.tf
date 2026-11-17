resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "garmin-mcp-gt"
  display_name              = "garmin-mcp-gt GitHub Actions"
  description               = "WIF pool for garmin-mcp-gt CI only. Deliberately separate from the shared github-actions pool used by the terraform-gcp-* modules"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "garmin-mcp-gt GitHub OIDC"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
  }

  attribute_condition = "assertion.repository == '${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

