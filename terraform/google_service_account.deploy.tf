resource "google_service_account" "deploy" {
  account_id   = "github-actions-deploy"
  display_name = "GitHub Actions Deploy"
}


resource "google_service_account_iam_member" "wif_deploy" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
