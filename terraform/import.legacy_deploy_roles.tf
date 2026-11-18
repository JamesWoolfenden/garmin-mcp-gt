# One-shot adoption of two hand-made grants on the deploy SA so the next
# change can revoke them through IaC. Remove this file in that change.
import {
  to = google_project_iam_member.deploy_roles["roles/cloudbuild.builds.editor"]
  id = "pike-477416 roles/cloudbuild.builds.editor serviceAccount:github-actions-deploy@pike-477416.iam.gserviceaccount.com"
}

import {
  to = google_project_iam_member.deploy_roles["roles/storage.admin"]
  id = "pike-477416 roles/storage.admin serviceAccount:github-actions-deploy@pike-477416.iam.gserviceaccount.com"
}
