variable "project_id" {
  default     = "pike-477416"
  description = "The ID of the GCP project to deploy resources in. Must be a valid project ID with billing enabled."
  type        = string
  validation {
    condition     = length(var.project_id) > 0
    error_message = "project_id must be a non-empty string"
  }
}

variable "region" {
  default     = "europe-west1"
  description = "The region to deploy resources in. Must be a supported region for Cloud Run and Secret Manager."
  type        = string
  validation {
    condition     = length(var.region) > 0
    error_message = "region must be a non-empty string"
  }
}


variable "vapid_email" {
  description = "Email address to use for VAPID authentication when sending push notifications. Must be a valid email address."
  type        = string
  default     = "james.woolfenden@gmail.com"
  validation {
    condition     = length(var.vapid_email) > 0 && can(regex("^[^@]+@[^@]+\\.[^@]+$", var.vapid_email))
    error_message = "vapid_email must be a non-empty string in a valid email format"
  }
}

variable "garmin_sidecar_url" {
  description = "URL of the Garmin sidecar service to send push notifications to. Must be a valid URL."
  type        = string
  default     = "https://fuel.wlfdn.dev"
  validation {
    condition     = length(var.garmin_sidecar_url) > 0 && can(regex("^https?://", var.garmin_sidecar_url))
    error_message = "garmin_sidecar_url must be a non-empty string starting with http:// or https://"
  }
}

variable "github_repo" {
  description = "GitHub repository to use for storing Terraform state and configuration. Must be in the format 'owner/repo'."
  type        = string
  default     = "JamesWoolfenden/garmin-mcp-gt"
  validation {
    condition     = length(var.github_repo) > 0 && can(regex("^[^/]+/[^/]+$", var.github_repo))
    error_message = "github_repo must be a non-empty string in the format 'owner/repo'"
  }
}

variable "internal_secret" {
  description = "Value of the fuel-internal-secret Secret Manager secret"
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.internal_secret) > 0
    error_message = "internal_secret must be a non-empty string"
  }
}
