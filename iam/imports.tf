# The role and its two bindings already exist in GCP (created by hand per
# the gcloud commands this module replaces) but were never tracked by any
# Terraform state.
import {
  id = "projects/pike-477416/roles/fuel_terraform"
  to = google_project_iam_custom_role.fuel_terraform
}

import {
  id = "pike-477416 projects/pike-477416/roles/fuel_terraform serviceAccount:github-actions-terraform@pike-477416.iam.gserviceaccount.com"
  to = google_project_iam_member.fuel_terraform_project
}

import {
  id = "terraform-pike-bucket-tfstate projects/pike-477416/roles/fuel_terraform serviceAccount:github-actions-terraform@pike-477416.iam.gserviceaccount.com"
  to = google_storage_bucket_iam_member.fuel_terraform_tfstate
}
