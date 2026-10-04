# 0.25b: DNS stage по плоской схеме (Q10), бакеты R2 с CORS и lifecycle (ADR-0007), WAF-исключение
# для webhook Telegram, SSL Full (strict) с сертификатом Origin CA для kamal-proxy (K12).
# Всё включается флагом cloudflare_enabled: до токена «terraform» (K12) ресурсов Cloudflare нет.
#
# Настройки зоны (режим SSL, HTTPS) и входной ruleset фазы WAF — общие для всей зоны. Пока зону
# ведёт только stage, они живут здесь; в 3.1a (prod в той же зоне) — переезд в общий стек зоны.

locals {
  cf = var.cloudflare_enabled ? 1 : 0

  host_app   = "stage-app.${var.domain}"
  host_api   = "stage-api.${var.domain}"
  host_cdn   = "stage-cdn.${var.domain}"
  host_admin = "stage-admin.${var.domain}"

  # Mini App грузит файлы в R2 по presigned-ссылкам прямо со своего origin
  app_origin = "https://${local.host_app}"

  buckets = {
    incoming = "${var.r2_bucket_prefix}-incoming"
    media    = "${var.r2_bucket_prefix}-media"
    private  = "${var.r2_bucket_prefix}-private"
  }

  # Адреса Bot API, с которых приходит webhook (core.telegram.org/bots/webhooks)
  telegram_ips = ["149.154.160.0/20", "91.108.4.0/22"]
}

check "cloudflare_inputs" {
  assert {
    condition     = !var.cloudflare_enabled || (var.domain != "" && var.cloudflare_account_id != "" && var.cloudflare_zone_id != "")
    error_message = "cloudflare_enabled = true: нужны domain, cloudflare_account_id и cloudflare_zone_id (K11)."
  }
}

# --- DNS ---

# API и webhook: через прокси Cloudflare на VM (kamal-proxy, сертификат Origin CA)
resource "cloudflare_dns_record" "api_a" {
  count   = local.cf
  zone_id = var.cloudflare_zone_id
  name    = local.host_api
  type    = "A"
  content = hcloud_server.stage.ipv4_address
  proxied = true
  ttl     = 1
  comment = "stage: API и webhook бота (kamal-proxy)"
}

resource "cloudflare_dns_record" "api_aaaa" {
  count   = local.cf
  zone_id = var.cloudflare_zone_id
  name    = local.host_api
  type    = "AAAA"
  content = hcloud_server.stage.ipv6_address
  proxied = true
  ttl     = 1
  comment = "stage: API и webhook бота (kamal-proxy)"
}

# Админка: запись есть, но kamal-proxy этот хост не обслуживает, а web без APP_ADMIN_SESSION_KEY
# /admin не монтирует. Публикация — в 2.7b, вместе с Cloudflare Access (K31).
resource "cloudflare_dns_record" "admin_a" {
  count   = local.cf
  zone_id = var.cloudflare_zone_id
  name    = local.host_admin
  type    = "A"
  content = hcloud_server.stage.ipv4_address
  proxied = true
  ttl     = 1
  comment = "stage: SQLAdmin — только за Access (K31, 2.7b)"
}

# Mini App: Worker sosed-tma-stage на своём домене. Привязать можно только существующий Worker,
# поэтому — после первого wrangler deploy (mini_app_worker_deployed = true, runbook 0.25d).
resource "cloudflare_workers_custom_domain" "app" {
  count      = var.cloudflare_enabled && var.mini_app_worker_deployed ? 1 : 0
  account_id = var.cloudflare_account_id
  zone_id    = var.cloudflare_zone_id
  hostname   = local.host_app
  service    = "sosed-tma-stage"
}

# --- R2 (EU jurisdiction, ADR-0007) ---

resource "cloudflare_r2_bucket" "stage" {
  for_each     = var.cloudflare_enabled ? local.buckets : {}
  account_id   = var.cloudflare_account_id
  name         = each.value
  jurisdiction = "eu"
}

resource "cloudflare_r2_bucket_cors" "stage" {
  for_each     = cloudflare_r2_bucket.stage
  account_id   = var.cloudflare_account_id
  bucket_name  = each.value.name
  jurisdiction = "eu"

  rules = [{
    id = "mini-app"
    allowed = {
      origins = [local.app_origin]
      # private отдаётся только presigned GET; incoming и media принимают presigned PUT
      methods = each.key == "private" ? ["GET", "HEAD"] : ["GET", "PUT", "HEAD"]
      headers = ["*"]
    }
    # multipart: клиент собирает ETag частей (спайк 0.24)
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }]
}

resource "cloudflare_r2_bucket_lifecycle" "stage" {
  for_each     = cloudflare_r2_bucket.stage
  account_id   = var.cloudflare_account_id
  bucket_name  = each.value.name
  jurisdiction = "eu"

  rules = concat(
    [{
      id         = "abort-multipart"
      enabled    = true
      conditions = { prefix = "" }
      abort_multipart_uploads_transition = {
        condition = { type = "Age", max_age = 86400 }
      }
    }],
    # incoming: сырые загрузки живут 2 дня — обработанное уже лежит в media или private
    each.key == "incoming" ? [{
      id         = "incoming-ttl"
      enabled    = true
      conditions = { prefix = "" }
      delete_objects_transition = {
        condition = { type = "Age", max_age = var.incoming_ttl_days * 86400 }
      }
    }] : [],
  )
}

# media — публично через stage-cdn.<domain> (кэш Cloudflare), остальные бакеты наружу не смотрят
resource "cloudflare_r2_custom_domain" "cdn" {
  count        = local.cf
  account_id   = var.cloudflare_account_id
  bucket_name  = cloudflare_r2_bucket.stage["media"].name
  jurisdiction = "eu"
  domain       = local.host_cdn
  zone_id      = var.cloudflare_zone_id
  enabled      = true
  min_tls      = "1.2"
}

# --- WAF: webhook Telegram не должен упираться в проверки браузера и security level ---

resource "cloudflare_ruleset" "zone_custom" {
  count       = local.cf
  zone_id     = var.cloudflare_zone_id
  name        = "sosed: custom rules"
  description = "Входной ruleset фазы custom rules зоны (общий для stage и prod — см. шапку файла)"
  kind        = "zone"
  phase       = "http_request_firewall_custom"

  rules = [{
    ref         = "stage_telegram_webhook_skip"
    description = "stage: webhook Telegram с адресов Bot API — без BIC, security level и managed rules"
    expression  = "(http.host eq \"${local.host_api}\" and starts_with(http.request.uri.path, \"/integrations/telegram/\") and ip.src in {${join(" ", local.telegram_ips)}})"
    action      = "skip"
    action_parameters = {
      phases   = ["http_ratelimit", "http_request_firewall_managed"]
      products = ["bic", "hot", "securityLevel", "uaBlock", "zoneLockdown"]
    }
    logging = { enabled = true }
  }]
}

# --- SSL: Full (strict) и сертификат Origin CA для kamal-proxy ---

resource "cloudflare_zone_setting" "ssl" {
  count      = local.cf
  zone_id    = var.cloudflare_zone_id
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_zone_setting" "always_use_https" {
  count      = local.cf
  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}

resource "cloudflare_zone_setting" "min_tls_version" {
  count      = local.cf
  zone_id    = var.cloudflare_zone_id
  setting_id = "min_tls_version"
  value      = "1.2"
}

# Ключ сертификата живёт в state (поэтому state — секрет, K14a) и уходит в секреты stage как
# KAMAL_PROXY_SSL_KEY командой из runbook, не через терминал.
resource "tls_private_key" "origin" {
  count       = local.cf
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "tls_cert_request" "origin" {
  count           = local.cf
  private_key_pem = tls_private_key.origin[0].private_key_pem

  subject {
    common_name  = local.host_api
    organization = "Sosedi stage"
  }
}

resource "cloudflare_origin_ca_certificate" "origin" {
  count              = local.cf
  csr                = tls_cert_request.origin[0].cert_request_pem
  hostnames          = [local.host_api, local.host_admin]
  request_type       = "origin-ecc"
  requested_validity = 5475
}
