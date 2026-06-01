output "backend_url" {
  value = google_cloud_run_v2_service.fuel_backend.uri
  description = "URL of the deployed Cloud Run service"
}

output "deploy_sa" {
  value = google_service_account.deploy.email
  description = "Email of the service account used for deployment"
}

output "wif_provider" {
  value = "projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/providers/${google_iam_workload_identity_pool_provider.github.workload_identity_pool_provider_id}"
 description = "Full resource name of the Workload Identity Pool Provider for GitHub Actions"
}
