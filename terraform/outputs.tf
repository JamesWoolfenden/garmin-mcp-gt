output "backend_url" {
  value = google_cloud_run_v2_service.fuel_backend.uri
}

output "deploy_sa" {
  value = google_service_account.deploy.email
}
