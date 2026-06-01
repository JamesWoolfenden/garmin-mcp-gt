locals {
  deploy_sa    = "github-actions-deploy@${var.project_id}.iam.gserviceaccount.com"
  terraform_sa = "github-actions-terraform@${var.project_id}.iam.gserviceaccount.com"
  scheduler_sa = "fuel-scheduler@${var.project_id}.iam.gserviceaccount.com"
  compute_sa   = "${data.google_project.this.number}-compute@developer.gserviceaccount.com"
  nudge_hours = [8, 13, 15, 20]
}
