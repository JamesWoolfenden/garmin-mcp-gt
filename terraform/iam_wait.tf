# IAM changes take 60-120s to propagate globally. Without this sleep,
# Terraform updates Cloud Run immediately after binding permissions to the
# new SA, and the container fails to start because the bindings haven't
# propagated yet.
resource "time_sleep" "iam_propagation" {
  create_duration = "90s"

  depends_on = [
    google_project_iam_member.backend_secret_access,
    google_kms_crypto_key_iam_member.backend_encrypter,
    google_kms_crypto_key_iam_member.backend_sqlite_encrypter,
    google_storage_bucket_iam_member.sqlite_backend,
  ]
}
