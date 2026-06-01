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
