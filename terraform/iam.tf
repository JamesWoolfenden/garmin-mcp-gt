resource "google_service_account" "fuel_backend" {
  account_id   = "fuel-backend"
  display_name = "Fuel Backend — Cloud Run runtime SA"
}

resource "google_service_account" "scheduler" {
  account_id   = "fuel-scheduler"
  display_name = "Fuel Cloud Scheduler"
}


resource "google_project_iam_member" "deploy_roles" {
  for_each = toset([
    "roles/run.developer",
    "roles/artifactregistry.writer",
    "roles/secretmanager.secretAccessor",
    "roles/firebasehosting.admin",
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${local.deploy_sa}"
}

# Scope serviceAccountUser to the specific SA used by Cloud Run (not project-wide)
resource "google_service_account_iam_member" "deploy_actas_backend" {
  service_account_id = google_service_account.fuel_backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.deploy_sa}"
}

resource "google_project_iam_member" "backend_secret_access" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.fuel_backend.email}"
}

# Retained during SA transition — compute SA may still serve traffic on old
# revisions while Cloud Run migrates to fuel-backend SA. Remove once confirmed.
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

resource "google_service_account_iam_member" "terraform_actas_backend" {
  service_account_id = google_service_account.fuel_backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.terraform_sa}"
}

resource "google_service_account_iam_member" "terraform_actas_scheduler" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.scheduler_sa}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.terraform_sa}"
}

