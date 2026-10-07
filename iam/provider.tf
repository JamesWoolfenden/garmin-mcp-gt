# holden:ignore:HLD_GCP_059: design to be applied outside of WIF.
provider "google" {
  project = var.project_id
  default_labels = {
    purpose = "fuel"
  }
}
