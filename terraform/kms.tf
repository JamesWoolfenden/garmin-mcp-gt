# Global key ring — used for Garmin token encryption (KMS operations in Cloud Run)
resource "google_kms_key_ring" "fuel" {
  name     = "fuel"
  location = "global"
}

resource "google_kms_crypto_key" "garmin_tokens" {
  name            = "garmin-tokens"
  key_ring        = google_kms_key_ring.fuel.id
  rotation_period = "7776000s" # 90 days

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "backend_encrypter" {
  crypto_key_id = google_kms_crypto_key.garmin_tokens.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.fuel_backend.email}"
}

# Regional key ring — GCS requires KMS key in same region as bucket
resource "google_kms_key_ring" "fuel_regional" {
  name     = "fuel"
  location = var.region
}

resource "google_kms_crypto_key" "sqlite_data" {
  name            = "sqlite-data"
  key_ring        = google_kms_key_ring.fuel_regional.id
  rotation_period = "7776000s" # 90 days

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "backend_sqlite_encrypter" {
  crypto_key_id = google_kms_crypto_key.sqlite_data.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.fuel_backend.email}"
}

# GCS also needs the SA to encrypt/decrypt for the bucket's service agent
resource "google_kms_crypto_key_iam_member" "gcs_sqlite_encrypter" {
  crypto_key_id = google_kms_crypto_key.sqlite_data.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gs-project-accounts.iam.gserviceaccount.com"
}
