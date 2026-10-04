# Общий стек зоны Cloudflare (DEVELOPMENT_PLAN 3.1a): то, что у зоны одно на все окружения. Режим
# SSL и входной ruleset фазы custom rules существуют в зоне в одном экземпляре — если их ведут два
# стека (stage и prod), каждый apply перетирает правила другого. Поэтому они живут здесь, а стеки
# окружений заводят только своё: DNS, R2, сертификат Origin CA, Access.
# Запуск — make tf ENV=zone ARGS='…' (токен «terraform», K12, в infra/terraform/zone/.env).
# Порядок — infra/runbooks/stage-bootstrap.md (шаг 2) и prod-bootstrap.md.

terraform {
  required_version = "~> 1.16.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.26"
    }
  }

  # State — локально, как у stage (Q14); секретов в нём нет, копия — в менеджер паролей (K10a).
}

# Токен — CLOUDFLARE_API_TOKEN из .env (K12): make secret NAME=CLOUDFLARE_API_TOKEN TARGET=tf-zone.
provider "cloudflare" {}

variable "domain" {
  description = "Домен в Cloudflare (Q9). Хосты окружений: api., bot., stage-api., stage-bot. (плоская схема, Q10)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]+(\\.[a-z0-9-]+)+$", var.domain))
    error_message = "Домен без схемы и точки в конце, например sosedi-test.com."
  }
}

variable "cloudflare_zone_id" {
  description = "Zone ID домена (K11, не секрет)."
  type        = string
}

module "edge" {
  source = "../modules/edge-ips"
}

locals {
  # хосты API окружений: на них нельзя открывать /admin
  api_hosts = ["stage-api.${var.domain}", "api.${var.domain}"]
  # хосты процесса bot (0.25e): webhook Telegram приходит только сюда — у роли bot свой хост в
  # kamal-proxy, Kamal не даёт двум ролям один хост с TLS
  bot_hosts = ["stage-bot.${var.domain}", "bot.${var.domain}"]
}

# --- WAF: custom rules зоны (на плане Free — до 5 правил) ---

resource "cloudflare_ruleset" "zone_custom" {
  zone_id     = var.cloudflare_zone_id
  name        = "sosed: custom rules"
  description = "Входной ruleset фазы custom rules зоны: общий для stage и prod (infra/terraform/zone)"
  kind        = "zone"
  phase       = "http_request_firewall_custom"

  rules = [
    {
      ref         = "telegram_webhook_skip"
      description = "webhook Telegram с адресов Bot API — без BIC, security level и managed rules"
      expression  = "(http.host in {${join(" ", formatlist("\"%s\"", local.bot_hosts))}} and starts_with(http.request.uri.path, \"/integrations/telegram/\") and ip.src in {${join(" ", module.edge.telegram_ips)}})"
      action      = "skip"
      action_parameters = {
        phases   = ["http_ratelimit", "http_request_firewall_managed"]
        products = ["bic", "hot", "securityLevel", "uaBlock", "zoneLockdown"]
      }
      logging = { enabled = true }
    },
    {
      # SQLAdmin живёт в том же процессе web, что и API: без этого правила /admin открывался бы
      # на api.<домен> мимо Cloudflare Access, который стоит только на admin.<домен> (K31)
      ref         = "admin_only_via_access"
      description = "/admin — только на admin.-хостах за Access, не на API"
      expression  = "(http.host in {${join(" ", formatlist("\"%s\"", local.api_hosts))}} and starts_with(http.request.uri.path, \"/admin\"))"
      action      = "block"
    },
  ]
}

# --- SSL: Full (strict) — Cloudflare проверяет сертификат Origin CA на kamal-proxy ---

resource "cloudflare_zone_setting" "ssl" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_zone_setting" "always_use_https" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}

resource "cloudflare_zone_setting" "min_tls_version" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "min_tls_version"
  value      = "1.2"
}
