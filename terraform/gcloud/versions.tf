terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.11"
    }
  }
}

# Uses Application Default Credentials:
#   gcloud auth application-default login
provider "google" {
  project = var.project
}
