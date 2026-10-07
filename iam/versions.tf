terraform {
  required_version = ">= 1.7" # compatible with OpenTofu 1.7+

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.34.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.14.0"
    }
  }

  # Deliberately a separate state from terraform/ (prefix "iam" vs "fuel"),
  # in the same bucket. See README.md in this directory for why.
  backend "gcs" {
    bucket = "terraform-pike-bucket-tfstate"
    prefix = "iam"
  }
}
