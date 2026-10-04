# 3.1c: край prod — DNS app., api., bot., cdn., admin. (ADR-0015, доменная схема), бакеты R2 prod (K39),
# сертификат Origin CA для kamal-proxy, Cloudflare Access перед админкой (K31). Включается флагом
# cloudflare_enabled, Access — отдельно access_enabled: частичный apply работает на любом шаге.
# Общее для зоны (Full strict, HTTPS, skip-правило WAF для webhook и запрет /admin на api.) — в
# infra/terraform/zone: один экземпляр на зону, его не должны перетирать stage и prod.

locals {
  cf     = var.cloudflare_enabled ? 1 : 0
  access = var.cloudflare_enabled && var.access_enabled ? 1 : 0

  host_app   = "app.${var.domain}"
  host_api   = "api.${var.domain}"
  host_bot   = "bot.${var.domain}"
  host_cdn   = "cdn.${var.domain}"
  host_admin = "admin.${var.domain}"

  # kamal-proxy на app-1 обслуживает API, webhook бота (свой хост роли bot: Kamal не даёт двум ролям
  # один хост с TLS, 0.25e) и админку — все имена через прокси Cloudflare
  app1_hosts = {
    api   = { host = local.host_api, comment = "prod: API (kamal-proxy)" }
    bot   = { host = local.host_bot, comment = "prod: webhook бота (kamal-proxy, роль bot)" }
    admin = { host = local.host_admin, comment = "prod: SQLAdmin — только за Access (K31)" }
  }
}

check "cloudflare_inputs" {
  assert {
    condition     = !var.cloudflare_enabled || (var.domain != "" && var.cloudflare_account_id != "" && var.cloudflare_zone_id != "")
    error_message = "cloudflare_enabled = true: нужны domain, cloudflare_account_id и cloudflare_zone_id (K11)."
  }
}

check "access_inputs" {
  assert {
    condition     = !var.access_enabled || (var.cloudflare_enabled && length(var.access_emails) > 0)
    error_message = "access_enabled = true: нужны cloudflare_enabled = true и хотя бы один e-mail в access_emails (K30)."
  }
}

# --- DNS ---

resource "cloudflare_dns_record" "app1_a" {
  for_each = var.cloudflare_enabled ? local.app1_hosts : {}
  zone_id  = var.cloudflare_zone_id
  name     = each.value.host
  type     = "A"
  content  = hcloud_server.app.ipv4_address
  proxied  = true
  ttl      = 1
  comment  = each.value.comment
}

resource "cloudflare_dns_record" "app1_aaaa" {
  for_each = var.cloudflare_enabled ? local.app1_hosts : {}
  zone_id  = var.cloudflare_zone_id
  name     = each.value.host
  type     = "AAAA"
  content  = hcloud_server.app.ipv6_address
  proxied  = true
  ttl      = 1
  comment  = each.value.comment
}

# Mini App: Worker sosed-tma-production на своём домене. Привязать можно только существующий Worker,
# поэтому — после первого wrangler deploy (mini_app_worker_deployed = true, prod-bootstrap.md).
resource "cloudflare_workers_custom_domain" "app" {
  count      = var.cloudflare_enabled && var.mini_app_worker_deployed ? 1 : 0
  account_id = var.cloudflare_account_id
  zone_id    = var.cloudflare_zone_id
  hostname   = local.host_app
  service    = "sosed-tma-production"
}

# --- R2 (EU jurisdiction, ADR-0007): тот же модуль, что у stage ---

module "r2" {
  source = "../modules/r2-buckets"
  count  = local.cf

  account_id        = var.cloudflare_account_id
  zone_id           = var.cloudflare_zone_id
  bucket_prefix     = var.r2_bucket_prefix
  app_origin        = "https://${local.host_app}"
  cdn_host          = local.host_cdn
  incoming_ttl_days = var.incoming_ttl_days
}

# --- Сертификат Origin CA для kamal-proxy (Full strict) ---

# Ключ живёт в state (поэтому state prod — секрет) и уходит в секреты environment «production» как
# KAMAL_PROXY_SSL_KEY трубой из runbook, не через терминал.
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
    organization = "Sosedi"
  }
}

resource "cloudflare_origin_ca_certificate" "origin" {
  count              = local.cf
  csr                = tls_cert_request.origin[0].cert_request_pem
  hostnames          = [local.host_api, local.host_bot, local.host_admin]
  request_type       = "origin-ecc"
  requested_validity = 5475
}

# --- Cloudflare Access перед admin.<domain> (K31): вход одноразовым кодом на e-mail персонала (K30) ---
# Второй уровень — собственный вход персонала (argon2 + TOTP, ADR-0009). Метод входа One-time PIN
# заводит владелец при создании организации Zero Trust; приложение и политику — этот стек.

resource "cloudflare_zero_trust_access_policy" "staff" {
  count      = local.access
  account_id = var.cloudflare_account_id
  name       = "sosed prod: персонал"
  decision   = "allow"
  include    = [for email in var.access_emails : { email = { email = email } }]
}

resource "cloudflare_zero_trust_access_application" "admin" {
  count                = local.access
  account_id           = var.cloudflare_account_id
  name                 = "sosed prod: админка"
  type                 = "self_hosted"
  domain               = local.host_admin
  session_duration     = var.access_session_duration
  app_launcher_visible = false

  policies = [{
    id         = cloudflare_zero_trust_access_policy.staff[0].id
    precedence = 1
  }]
}
