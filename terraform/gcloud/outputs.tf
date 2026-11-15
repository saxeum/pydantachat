output "oauth_secret_id" {
  description = "Secret ID to pass to `gcloud secrets versions add`."
  value       = google_secret_manager_secret.google_oauth.secret_id
}

output "oauth_secret_name" {
  description = "Fully qualified Secret Manager resource name."
  value       = google_secret_manager_secret.google_oauth.name
}
