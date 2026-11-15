# The standard Google OAuth web client used by pydantachat and zuchat is created
# in the console (APIs & Services -> Credentials). Google's Terraform provider
# has no resource for those client IDs or for the OAuth consent screen:
# `google_iam_oauth_client` is Workforce Identity Federation, and
# `google_identity_platform_oauth_idp_config` is Identity Platform. There is
# nothing here to `terraform import`.
#
# This module manages the credential container instead: a Secret Manager secret
# that holds the downloaded client JSON.

resource "google_project_service" "secretmanager" {
  project            = var.project
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_secret_manager_secret" "google_oauth" {
  project         = var.project
  secret_id       = var.oauth_secret_id
  deletion_policy = "PREVENT"

  replication {
    auto {}
  }

  labels = {
    managed-by = "terraform"
    purpose    = "google-oauth"
  }

  depends_on = [google_project_service.secretmanager]
}

# No google_secret_manager_secret_version on purpose: writing `secret_data`
# would put client_secret in Terraform state. Add the version out-of-band:
#
#   gcloud secrets versions add zuchat-google-oauth \
#     --data-file="$HOME/.config/zuchat/google-oauth.json" \
#     --project=saxeum-b9b1f
