variable "project_id" {
  default     = "pike-477416"
  description = "The GCP project the fuel_terraform bootstrap role lives in."
  type        = string
  validation {
    condition     = length(var.project_id) > 0
    error_message = "project_id must be a non-empty string"
  }
}

variable "terraform_sa_email" {
  default     = "github-actions-terraform@pike-477416.iam.gserviceaccount.com"
  description = "The CI service account this role is bound to."
  type        = string
  validation {
    condition     = length(trimspace(var.terraform_sa_email)) > 0
    error_message = "terraform_sa_email must be a non-empty string"
  }
}

variable "tfstate_bucket" {
  default     = "terraform-pike-bucket-tfstate"
  description = "The GCS bucket holding Terraform state, which the CI SA needs object access to."
  type        = string
  validation {
    condition     = length(trimspace(var.tfstate_bucket)) > 0
    error_message = "tfstate_bucket must be a non-empty string"
  }
}
