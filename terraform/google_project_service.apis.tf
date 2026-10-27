resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "artifactregistry.googleapis.com",
    # deploy-frontend: firebase-tools checks this API is enabled via Service Usage
    "firebasehosting.googleapis.com",
    "serviceusage.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}
