variable "project" {
  description = "Project that owns the shared Google OAuth client. Set in terraform.tfvars (git-ignored)."
  type        = string
}

variable "oauth_secret_id" {
  description = "Secret Manager secret that holds the downloaded OAuth client JSON. Set in terraform.tfvars (git-ignored)."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]{1,255}$", var.oauth_secret_id))
    error_message = "Secret IDs are 1-255 letters, digits, hyphens or underscores."
  }
}
