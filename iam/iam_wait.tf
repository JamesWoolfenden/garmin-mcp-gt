# A brand-new custom role isn't always immediately visible to the IAM
# policy API on a different resource (here, the bucket) right after
# creation — unlike fuel_terraform, which was imported and already existed
# in GCP. Without this, binding the bucket IAM member in the same apply can
# fail with "Role ... does not exist in the resource's hierarchy." Same
# pattern as terraform/iam_wait.tf.
resource "time_sleep" "fuel_terraform_build_propagation" {
  create_duration = "30s"

  depends_on = [google_project_iam_custom_role.fuel_terraform_build]
}
