# holden:ignore:HLD_GCP_059 -- WIF grants the GitHub Actions runner a short-lived token scoped to the Terraform SA directly; impersonate_service_account is redundant and incompatible with this auth flow
provider "google" {
  project = var.project_id
  region  = var.region
  default_labels = {
    purpose = "fuel"
  }
}
