# holden:ignore:HLD_GCP_394: -- Firestore is used for caching Garmin data; no sensitive data is stored in Firestore, so delete protection is enabled to prevent accidental deletion of the database
resource "google_firestore_database" "fuel" {
  name                    = "fuel"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  deletion_policy         = "PREVENT"

  lifecycle {
    prevent_destroy = true
  }
}
