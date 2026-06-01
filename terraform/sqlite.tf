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

  depends_on = [google_kms_crypto_key_iam_member.gcs_sqlite_encrypter]

  #checkov:skip=CKV_GCP_62: Access logging not required for personal project state bucket
}

resource "google_storage_bucket_iam_member" "sqlite_backend" {
  bucket = google_storage_bucket.sqlite.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.fuel_backend.email}"
}
