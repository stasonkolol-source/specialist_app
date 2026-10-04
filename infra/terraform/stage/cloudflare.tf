# 0.25b: DNS stage по плоской схеме (Q10), бакеты R2 с CORS и lifecycle (ADR-0007), сертификат
# Origin CA для kamal-proxy (K12). Всё включается флагом cloudflare_enabled: до токена «terraform»
# (K12) ресурсов Cloudflare нет.
#
# Общее для зоны — режим SSL Full (strict), HTTPS, skip-правило WAF для webhook Telegram и запрет
# /admin на хостах API — живёт в infra/terraform/zone (3.1a): в зоне это один экземпляр на stage и
# prod, два стека перетирали бы друг друга.

locals {
  cf = var.cloudflare_enabled ? 1 : 0

  host_app   = "stage-app.${var.domain}"
  host_api   = "stage-api.${var.domain}"
  host_bot   = "stage-bot.${var.domain}"
  host_cdn   = "stage-cdn.${var.domain}"
  host_admin = "stage-admin.${var.domain}"

  # Mini App грузит файлы в R2 по presigned-ссылкам прямо со своего origin
  app_origin = "https://${local.host_app}"
}

check "cloudflare_inputs" {
  assert {
    condition     = !var.cloudflare_enabled || (var.domain != "" && var.cloudflare_account_id != "" && var.cloudflare_zone_id != "")
    error_message = "cloudflare_enabled = true: нужны domain, cloudflare_account_id и cloudflare_zone_id (K11)."
  }
}

# --- DNS ---

# API: через прокси Cloudflare на VM (kamal-proxy, сертификат Origin CA)
resource "cloudflare_dns_record" "api_a" {
  count   = local.cf
  zone_id = var.cloudflare_zone_id
  name    = local.host_api
  type    = "A"
  content = hcloud_server.stage.ipv4_address
  proxied = true
  ttl     = 1
  comment = "stage: API (kamal-proxy)"
}

resource "cloudflare_dns_record" "api_aaaa" {
  count   = local.cf
  zone_id = var.cloudflare_zone_id
  name    = local.host_api
  type    = "AAAA"
  content = hcloud_server.stage.ipv6_address
  proxied = true
  ttl     = 1
  comment = "stage: API (kamal-proxy)"
}

# Webhook бота (0.25e): свой хост роли bot в kamal-proxy — Kamal не даёт двум ролям один хост с
# TLS. Skip-правило WAF для /integrations/telegram/ с адресов Bot API — в infra/terraform/zone.
resource "cloudflare_dns_record" "bot_a" {
  count   = local.cf
  zone_id = var.cloudflare_zone_id
  name    = local.host_bot
  type    = "A"
  content = hcloud_server.stage.ipv4_address
  proxied = true
  ttl     = 1
  comment = "stage: webhook бота (kamal-proxy, роль bot)"
}

resource "cloudflare_dns_record" "bot_aaaa" {
  count   = local.cf
  zone_id = var.cloudflare_zone_id
  name    = local.host_bot
  type    = "AAAA"
  content = hcloud_server.stage.ipv6_address
  proxied = true
  ttl     = 1
  comment = "stage: webhook бота (kamal-proxy, роль bot)"
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

# --- R2 (EU jurisdiction, ADR-0007): тот же модуль, что у prod ---

module "r2" {
  source = "../modules/r2-buckets"
  count  = local.cf

  account_id        = var.cloudflare_account_id
  zone_id           = var.cloudflare_zone_id
  bucket_prefix     = var.r2_bucket_prefix
  app_origin        = local.app_origin
  cdn_host          = local.host_cdn
  incoming_ttl_days = var.incoming_ttl_days
}

# --- Сертификат Origin CA для kamal-proxy (Full strict — в стеке зоны) ---

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
  hostnames          = [local.host_api, local.host_bot, local.host_admin]
  request_type       = "origin-ecc"
  requested_validity = 5475
}
