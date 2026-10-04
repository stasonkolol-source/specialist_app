# Внешние проверки доступности (DEVELOPMENT_PLAN 3.3, ARCHITECTURE §16.5): мониторы UptimeRobot на /up
# API и бота и на Mini App, stage и prod. Провайдер — официальный uptimerobot/uptimerobot (API v3).
# Healthchecks.io (heartbeat воркера, pgBackRest, restore-тест) здесь нет: его единственный провайдер
# kristofferahl/healthchecksio не выпускался с 2025-04 — три проверки заводятся руками по списку в
# infra/runbooks/prod-bootstrap.md («Наблюдаемость»).
# Запуск — make tf ENV=monitoring ARGS='init|plan|apply' (ключ API — infra/terraform/monitoring/.env).

terraform {
  required_version = "~> 1.16.0"

  required_providers {
    uptimerobot = {
      source  = "uptimerobot/uptimerobot"
      version = "~> 1.12.0"
    }
  }

  # State — локально, как у других стеков (Q14); секретов в нём нет (адрес e-mail — sensitive), копия —
  # в менеджер паролей (K10a).
}

# Ключ — UPTIMEROBOT_API_KEY из .env (K34, Main API Key): make secret NAME=UPTIMEROBOT_API_KEY TARGET=tf-monitoring.
provider "uptimerobot" {}

variable "domain" {
  description = "Домен (Q9): хосты api., bot., app. и stage-api., stage-bot., stage-app. (плоская схема, Q10)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]+(\\.[a-z0-9-]+)+$", var.domain))
    error_message = "Домен без схемы и точки в конце, например sosedi-test.com."
  }
}

variable "alert_email" {
  description = "E-mail для алертов (K35a) — контакт аккаунта UptimeRobot, он уже есть после регистрации."
  type        = string
  sensitive   = true
}

variable "stage_enabled" {
  description = "Мониторы stage. false — пока stage не поднят (0.25) или выключен."
  type        = bool
  default     = true
}

variable "prod_enabled" {
  description = "Мониторы prod. До первого релиза (3.1c) хостов нет — false, иначе алерты сразу."
  type        = bool
  default     = false
}

data "uptimerobot_alert_contact" "owner" {
  type  = "email"
  value = var.alert_email
}

locals {
  # /up отвечает и web, и bot (kamal-proxy healthcheck); Mini App — статика Workers, её корень
  checks = merge(
    var.prod_enabled ? {
      "prod-api"     = { name = "prod: API /up", url = "https://api.${var.domain}/up", tags = ["production", "api"] }
      "prod-bot"     = { name = "prod: бот /up", url = "https://bot.${var.domain}/up", tags = ["production", "bot"] }
      "prod-mini-app" = { name = "prod: Mini App", url = "https://app.${var.domain}/", tags = ["production", "mini-app"] }
    } : {},
    var.stage_enabled ? {
      "stage-api"     = { name = "stage: API /up", url = "https://stage-api.${var.domain}/up", tags = ["stage", "api"] }
      "stage-bot"     = { name = "stage: бот /up", url = "https://stage-bot.${var.domain}/up", tags = ["stage", "bot"] }
      "stage-mini-app" = { name = "stage: Mini App", url = "https://stage-app.${var.domain}/", tags = ["stage", "mini-app"] }
    } : {},
  )
}

# Free: интервал 5 минут, контакт — сразу и без повторов (threshold и recurrence 0 — требование Free)
resource "uptimerobot_monitor" "up" {
  for_each = local.checks

  name                        = each.value.name
  type                        = "HTTP"
  url                         = each.value.url
  interval                    = 300
  timeout                     = 30
  http_method_type            = "GET"
  success_http_response_codes = ["200"]
  follow_redirections         = false
  check_ssl_errors            = true
  ssl_expiration_reminder     = true
  tags                        = each.value.tags

  assigned_alert_contacts = [
    {
      alert_contact_id = data.uptimerobot_alert_contact.owner.id
      threshold        = 0
      recurrence       = 0
    }
  ]
}

output "monitors" {
  description = "Мониторы UptimeRobot: ключ → URL."
  value       = { for k, m in uptimerobot_monitor.up : k => m.url }
}
