# Repository as code

Configures this GitHub repository: visibility, description, topics, secret
scanning with push protection, Dependabot security updates, and branch
protection on `main`.

The repository and its `main` branch already exist (created by hand for the
first push), so every resource here is adopted with `terraform import` before
the first apply. Nothing is created from scratch.

## Prerequisites

- Terraform >= 1.9
- `GITHUB_TOKEN` exported in your shell, with permission to change repository
  settings. Never put it in CI: a workflow holding it could rewrite the
  protections this configuration sets.

## First apply

```bash
cd terraform/github
cp terraform.tfvars.example terraform.tfvars   # owner = "saxeum"
export GITHUB_TOKEN=...                        # admin on the repository
terraform init
terraform import github_repository.repo pydantachat
terraform import github_repository_dependabot_security_updates.repo pydantachat
terraform plan    # branch protection shows as a create, everything else as no-op
terraform apply
```

`terraform plan` before the imports offers to *create* `saxeum/pydantachat`,
which fails with `422 already exists`. That is the signal that an import is
missing, not a reason to remove the resource.

## What is checked

`contexts = ["check"]` refers to the job id in `.github/workflows/ci.yml`, not
to the workflow's `name:` (`ci`) and not to its file name. If you rename that
job, update `main.tf`, or the required check never reports and every merge is
blocked.

## State

State is local and git-ignored (`.terraform/`, `*.tfstate*`, `terraform.tfvars`).
The lock file `.terraform.lock.hcl` is committed, like `uv.lock`.
