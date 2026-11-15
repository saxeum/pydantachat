# Google OAuth client secret

The standard Google OAuth **web client** used by pydantachat and zuchat is
created in the Google Cloud console. Google's Terraform provider has no
resource for console OAuth client IDs or the OAuth consent screen:

- `google_iam_oauth_client` is for Workforce Identity Federation.
- `google_identity_platform_oauth_idp_config` is for Identity Platform.
- There is no `google_oauth2_client` or consent-screen resource.

So the client itself cannot be imported. This module manages the part Terraform
can own: the Secret Manager secret that holds the downloaded client JSON. The
client stays console-managed.

## Prerequisites

- Terraform >= 1.9.
- Application Default Credentials that can manage Secret Manager:
  ```bash
  gcloud auth application-default login
  ```
- A downloaded OAuth client JSON, e.g. `~/.config/zuchat/google-oauth.json`.

Copy the example variables file and fill it in. `terraform.tfvars` is
git-ignored:

```bash
cp terraform.tfvars.example terraform.tfvars
```

```hcl
project         = "saxeum-b9b1f"
oauth_secret_id = "zuchat-google-oauth"
```

## First apply

```bash
cd terraform/gcloud
cp terraform.tfvars.example terraform.tfvars   # then edit project / secret id
terraform init
terraform apply
```

Secret Manager is already enabled in this project; the `google_project_service`
resource is idempotent and leaves the API on when the stack is destroyed. The
secret uses `deletion_policy = "PREVENT"`; change it to `"DELETE"` before
destroying.

If the secret already exists, adopt it instead of creating it:

```bash
terraform import google_secret_manager_secret.google_oauth \
  projects/saxeum-b9b1f/secrets/zuchat-google-oauth
```

## Upload the client JSON

Terraform does not write the secret version: `secret_data` would put
`client_secret` in state. Add the version with gcloud:

```bash
gcloud secrets versions add zuchat-google-oauth \
  --data-file="$HOME/.config/zuchat/google-oauth.json" \
  --project=saxeum-b9b1f
```

Check it without printing the value:

```bash
gcloud secrets versions list zuchat-google-oauth --project=saxeum-b9b1f
```

## Read it back

For local development, or on a machine that should not hold the client file:

```bash
gcloud secrets versions access latest \
  --secret=zuchat-google-oauth \
  --project=saxeum-b9b1f \
  > "$HOME/.config/zuchat/google-oauth.json"
chmod 600 "$HOME/.config/zuchat/google-oauth.json"
```

## Rotation

Create a new client secret in the console, download the JSON, and add it as a
new secret version. Keep the previous version until every deployment has picked
up the new one:

```bash
gcloud secrets versions add zuchat-google-oauth \
  --data-file="$HOME/Downloads/client_secret_*.json" \
  --project=saxeum-b9b1f
```

Never put the client JSON in this repository, `terraform.tfvars`, or a commit.
Terraform state is local and git-ignored.
