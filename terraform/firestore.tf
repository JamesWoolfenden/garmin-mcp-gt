resource "google_firestore_database" "fuel" {
  name        = "fuel"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  lifecycle {
    prevent_destroy = true
  }
}
