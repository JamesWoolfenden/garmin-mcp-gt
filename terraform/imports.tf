import {
  id = "projects/pike-477416/secrets/fuel-allowed-emails"
  to = google_secret_manager_secret.allowed_emails
}

import {
  id = "projects/pike-477416/secrets/fuel-admin-uid"
  to = google_secret_manager_secret.admin_uid
}

# These exist in GCP already (CI authenticates with them today) but were
# never brought into state, so Terraform planned to "create" them — which
# made google_service_account_iam_member.wif_deploy's member (interpolated
# from the pool's .name) unknown and forced it to be replaced.
import {
  id = "projects/pike-477416/locations/global/workloadIdentityPools/github-actions"
  to = google_iam_workload_identity_pool.github
}

import {
  id = "projects/pike-477416/locations/global/workloadIdentityPools/github-actions/providers/github-oidc"
  to = google_iam_workload_identity_pool_provider.github
}

import {
  id = "projects/pike-477416/serviceAccounts/github-actions-terraform@pike-477416.iam.gserviceaccount.com"
  to = google_service_account.terraform
}

# google_service_account_iam_member.wif_terraform has no existing binding to
# import (confirmed: GCP returned "Cannot find binding" for it) — it's a
# genuinely new, additive IAM grant, safe to let Terraform create normally.
