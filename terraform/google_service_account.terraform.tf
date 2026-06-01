

# Bootstrap note: the terraform SA and its permissions are managed outside
# Terraform to avoid the executor managing its own access.
# See backend/setup-terraform-sa.ps1 for the bootstrap script.
resource "google_service_account" "terraform" {
  account_id   = "github-actions-terraform"
  display_name = "GitHub Actions Terraform"
}

# Bootstrap: bind fuel_terraform role to the terraform SA manually —
# Terraform cannot manage its own executor's permissions.
#
#   gcloud projects add-iam-policy-binding pike-477416 \
#     --member="serviceAccount:github-actions-terraform@pike-477416.iam.gserviceaccount.com" \
#     --role="projects/pike-477416/roles/fuel_terraform"
#
#   gcloud storage buckets add-iam-policy-binding gs://terraform-pike-bucket-tfstate \
#     --member="serviceAccount:github-actions-terraform@pike-477416.iam.gserviceaccount.com" \
#     --role="projects/pike-477416/roles/fuel_terraform"

resource "google_service_account_iam_member" "wif_terraform" {
  service_account_id = google_service_account.terraform.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

