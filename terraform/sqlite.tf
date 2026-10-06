# holden:ignore:HLD_GCP_003 -- access logging not required; personal project bucket, not handling regulated data
resource "google_storage_bucket" "sqlite" {
  name                        = "${var.project_id}-sqlite"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.sqlite_data.id
  }

  lifecycle_rule {
    condition {
      age = 30
    }

    action {
      type = "Delete"
    }
  }

  soft_delete_policy {
    retention_duration_seconds = 604800
  }

  depends_on = [google_kms_crypto_key_iam_member.gcs_sqlite_encrypter]
}

resource "google_storage_bucket_iam_member" "sqlite_backend" {
  bucket = google_storage_bucket.sqlite.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.fuel_backend.email}"
}
