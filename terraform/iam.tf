locals {
  deploy_sa    = "github-actions-deploy@${var.project_id}.iam.gserviceaccount.com"
  terraform_sa = "github-actions-terraform@${var.project_id}.iam.gserviceaccount.com"
  scheduler_sa = "fuel-scheduler@${var.project_id}.iam.gserviceaccount.com"
  compute_sa   = "${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_service_account" "deploy" {
  account_id   = "github-actions-deploy"
  display_name = "GitHub Actions Deploy"
}

resource "google_service_account" "scheduler" {
  account_id   = "fuel-scheduler"
  display_name = "Fuel Cloud Scheduler"
}

# Bootstrap note: this SA must exist and have roles/storage.objectAdmin on the
# state bucket BEFORE Terraform can run. Everything else is managed here.
resource "google_service_account" "terraform" {
  account_id   = "github-actions-terraform"
  display_name = "GitHub Actions Terraform"
}

resource "google_project_iam_member" "terraform_roles" {
  for_each = toset([
    "roles/serviceusage.serviceUsageAdmin",
    "roles/resourcemanager.projectIamAdmin",
    "roles/secretmanager.admin",
    "roles/run.admin",
    "roles/cloudscheduler.admin",
    "roles/iam.workloadIdentityPoolAdmin",
    "roles/datastore.owner",
    "roles/firebasehosting.admin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.serviceAccountUser",
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${local.terraform_sa}"
}

resource "google_storage_bucket_iam_member" "terraform_state" {
  bucket = "terraform-pike-bucket-tfstate"
  role   = "roles/storage.admin"
  member = "serviceAccount:${local.terraform_sa}"
}

resource "google_service_account_iam_member" "wif_terraform" {
  service_account_id = google_service_account.terraform.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

resource "google_project_iam_member" "deploy_roles" {
  for_each = toset([
    "roles/run.developer",
    "roles/artifactregistry.writer",
    "roles/secretmanager.secretAccessor",
    "roles/iam.serviceAccountUser",
    "roles/firebasehosting.admin",
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${local.deploy_sa}"
}

resource "google_project_iam_member" "compute_secret_access" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${local.compute_sa}"
}

resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.fuel_backend.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.scheduler_sa}"
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.fuel_backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_service_account_iam_member" "wif_deploy" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
