# iam/

This is a **separate Terraform root module with its own state** (`prefix = "iam"`
in the shared `terraform-pike-bucket-tfstate` bucket, distinct from the main
`terraform/` module's `prefix = "fuel"`). It defines the `fuel_terraform`
custom IAM role — the permissions granted to `github-actions-terraform`,
the service account that runs `tofu apply` for `terraform/` in CI.

## Why this isn't just part of `terraform/`

`terraform/google_service_account.terraform.tf` has always noted that this
role is "managed outside Terraform to avoid the executor managing its own
access" — previously meaning raw `gcloud` commands run by hand. This module
replaces those commands with reviewable, diffable code, but it **must never
be applied by the `github-actions-terraform` SA or wired into the `tofu` CI
job**. If the identity that runs `terraform/`'s `apply` could also grant
itself more permissions via the same pipeline:

1. Anyone who can land a push to `main` could add a permission to this role
   and have their own CI run pick it up — privilege escalation baked into
   the IaC itself.
2. It also only works after the fact anyway: the first-ever `apply` needs
   permissions that can't exist yet if that same `apply` is what grants them.

`fuel_terraform` includes genuinely escalation-class permissions
(`iam.serviceAccounts.setIamPolicy`, `resourcemanager.projects.setIamPolicy`)
that `terraform/` itself needs (e.g. the WIF service-account bindings) — so
this isn't avoidable by trimming the role down. The separation of *state*,
not just a comment, is what actually prevents the self-referential problem:
`terraform/`'s CI job has no reason to ever `init`/`apply` this directory,
and never should.

## How to apply changes here

By hand, with your own (human) credentials — not CI:

```bash
cd iam
tofu init
tofu plan
tofu apply
```

## Keeping the permission list current

This repo uses [pike](https://github.com/JamesWoolfenden/pike) (same author,
same family of tooling as `holden`) to compute the permissions `terraform/`
actually needs and diff them against what's live:

```bash
# from the repo root
pike compare --directory terraform --arn "projects/pike-477416/roles/fuel_terraform"
```

(Requires `GCP_PROJECT=pike-477416` in the environment.) This prints a
`needs`/`excess` diff. When `terraform/` grows a new resource type that
needs a new permission, add it to `main.tf`'s `permissions` list here, then
apply as above.

## Current `excess` permissions, not yet trimmed

As of the last `pike compare` run (2026-10-06), these are granted but unused
by `terraform/`'s current resources: `iam.roles.{create,delete,get,update}`,
`iam.serviceAccounts.actAs`, `secretmanager.versions.{access,list}`,
`storage.buckets.list`, `storage.objects.{create,delete,get,list}`,
`cloudkms.cryptoKeys.list`, `cloudkms.keyRings.list`. They were deliberately
left in place rather than trimmed, since some may be used by steps outside
`terraform/` that `pike` can't see (e.g. `backend/setup-terraform-sa.ps1`).
Trimming to true least-privilege is a follow-up, not bundled into adding the
missing permissions.
