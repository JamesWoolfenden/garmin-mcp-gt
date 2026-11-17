

# Bootstrap note: on a fresh project this SA (and the WIF pool it is bound to)
# is created by a project owner running `tofu apply` locally, before CI can
# authenticate. Its permissions are granted separately by ../iam, never by CI.
resource "google_service_account" "terraform" {
  account_id   = "garmin-terraform"
  display_name = "garmin-mcp-gt Terraform"
  description  = "Runs tofu for garmin-mcp-gt in CI via its own WIF pool. Not shared with any other repo"
}

# The fuel_terraform role and its bindings to this SA are defined in ../iam
# (a separate Terraform state, applied by hand — never by this SA, never by
# CI). See iam/README.md for why. Previously this was raw, undocumented
# gcloud commands; that module replaces them with reviewable code.

resource "google_service_account_iam_member" "wif_terraform" {
  service_account_id = google_service_account.terraform.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

