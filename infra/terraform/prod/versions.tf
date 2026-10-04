# Prod «Соседей» (DEVELOPMENT_PLAN 3.1a, ADR-0015): app-1 и db-1 в приватной сети Hetzner и край
# Cloudflare одним стеком. Общее для зоны (режим SSL, WAF custom rules) — в infra/terraform/zone.
# Запуск — только через make tf ENV=prod ARGS='…' (образ hashicorp/terraform той же версии, токены —
# из infra/terraform/prod/.env). Порядок действий — infra/runbooks/prod-bootstrap.md.

terraform {
  required_version = "~> 1.16.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.69"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.26"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.4"
    }
  }

  # Q14 не решён: state лежит локально (infra/terraform/prod/terraform.tfstate, в git не попадает —
  # .gitignore). В нём приватный ключ сертификата Origin CA prod, поэтому state — prod-секрет: копия
  # в менеджер паролей (K10a) после каждого apply. Удалённый state — как в stage (блок backend "s3"
  # в infra/terraform/stage/versions.tf) с key = "prod/terraform.tfstate" и ключом K14a.
}

# Токен — HCLOUD_TOKEN из .env (K38): make secret NAME=HCLOUD_TOKEN TARGET=tf-prod.
provider "hcloud" {}

# Токен — CLOUDFLARE_API_TOKEN из .env (K12, токен «terraform»). Пока cloudflare_enabled = false,
# ресурсов Cloudflare ноль и провайдеру хватает заглушки — к API он не ходит.
provider "cloudflare" {
  api_token = var.cloudflare_enabled ? null : "placeholder-until-step-3-1c-000000000000"
}
