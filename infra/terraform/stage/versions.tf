# Stage «Соседей» (DEVELOPMENT_PLAN 0.25a–0.25b): VM в Hetzner и край Cloudflare одним стеком.
# Запуск — только через make tf ENV=stage ARGS='…' (образ hashicorp/terraform той же версии,
# токены — из infra/terraform/stage/.env). Порядок действий — infra/runbooks/stage-bootstrap.md.

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

  # Q14 не решён: state лежит локально (infra/terraform/stage/terraform.tfstate, в git не
  # попадает — .gitignore). В нём приватный ключ сертификата Origin CA, поэтому копия state —
  # в менеджер паролей (K10a). Удалённый state в R2 — блок ниже и ключ K14a:
  #   backend "s3" {
  #     bucket                      = "sosed-tfstate"
  #     key                         = "stage/terraform.tfstate"
  #     region                      = "auto"
  #     endpoints                   = { s3 = "https://<account_id>.eu.r2.cloudflarestorage.com" }
  #     skip_credentials_validation = true
  #     skip_region_validation      = true
  #     skip_requesting_account_id  = true
  #     skip_metadata_api_check     = true
  #     skip_s3_checksum            = true
  #     use_path_style              = true
  #     use_lockfile                = true
  #   }
}

# Токен — HCLOUD_TOKEN из .env (K14): make secret NAME=HCLOUD_TOKEN TARGET=tf-stage.
provider "hcloud" {}

# Токен — CLOUDFLARE_API_TOKEN из .env (K12, токен «terraform»). До 0.25b токена нет: ресурсов
# Cloudflare ноль (cloudflare_enabled = false), и провайдеру хватает заглушки — к API он не ходит.
provider "cloudflare" {
  api_token = var.cloudflare_enabled ? null : "placeholder-until-step-0-25b-00000000000"
}
