

# Bootstrap note: the terraform SA and its permissions are managed outside
# Terraform to avoid the executor managing its own access.
# See backend/setup-terraform-sa.ps1 for the bootstrap script.
resource "google_service_account" "terraform" {
  account_id   = "github-actions-terraform"
  display_name = "GitHub Actions Terraform"
  description  = "Service account used by GitHub Actions via Workload Identity Federation"
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

