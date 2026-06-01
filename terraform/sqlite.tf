resource "google_storage_bucket" "sqlite" {
  name                        = "${var.project_id}-sqlite"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }
}

resource "google_storage_bucket_iam_member" "sqlite_compute" {
  bucket = google_storage_bucket.sqlite.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.compute_sa}"
}
