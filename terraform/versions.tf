terraform {
  required_version = ">= 1.7" # compatible with OpenTofu 1.7+

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.34.0"
    }
  }

  backend "gcs" {
    bucket = "terraform-pike-bucket-tfstate"
    prefix = "fuel"
  }
}
