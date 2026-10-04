# Бакеты R2 одного окружения (ADR-0007): incoming, media, private в EU jurisdiction, CORS для
# origin Mini App, lifecycle и публичный домен CDN для media. Один модуль для stage и prod: правила
# загрузки из WebView (спайк 0.24) одинаковы, расходятся только имена и хосты.

terraform {
  required_providers {
    cloudflare = {
      source = "cloudflare/cloudflare"
    }
  }
}

variable "account_id" {
  description = "Account ID Cloudflare (K11)."
  type        = string
}

variable "zone_id" {
  description = "Zone ID домена — для custom domain бакета media."
  type        = string
}

variable "bucket_prefix" {
  description = "Префикс имён: <префикс>-incoming, -media, -private."
  type        = string
}

variable "app_origin" {
  description = "Origin Mini App (https://…-app.<домен>): только он грузит файлы по presigned-ссылкам."
  type        = string
}

variable "cdn_host" {
  description = "Хост CDN для бакета media (кэш Cloudflare)."
  type        = string
}

variable "incoming_ttl_days" {
  description = "Сколько дней живут неподтверждённые загрузки в incoming (ADR-0007)."
  type        = number
}

locals {
  buckets = {
    incoming = "${var.bucket_prefix}-incoming"
    media    = "${var.bucket_prefix}-media"
    private  = "${var.bucket_prefix}-private"
  }
}

resource "cloudflare_r2_bucket" "this" {
  for_each     = local.buckets
  account_id   = var.account_id
  name         = each.value
  jurisdiction = "eu"
}

resource "cloudflare_r2_bucket_cors" "this" {
  for_each     = cloudflare_r2_bucket.this
  account_id   = var.account_id
  bucket_name  = each.value.name
  jurisdiction = "eu"

  rules = [{
    id = "mini-app"
    allowed = {
      origins = [var.app_origin]
      # private отдаётся только presigned GET; incoming и media принимают presigned PUT
      methods = each.key == "private" ? ["GET", "HEAD"] : ["GET", "PUT", "HEAD"]
      headers = ["*"]
    }
    # multipart: клиент собирает ETag частей (спайк 0.24)
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }]
}

resource "cloudflare_r2_bucket_lifecycle" "this" {
  for_each     = cloudflare_r2_bucket.this
  account_id   = var.account_id
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
    # incoming: сырые загрузки живут пару дней — обработанное уже лежит в media или private
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

# media — публично через CDN-хост (кэш Cloudflare), остальные бакеты наружу не смотрят
resource "cloudflare_r2_custom_domain" "cdn" {
  account_id   = var.account_id
  bucket_name  = cloudflare_r2_bucket.this["media"].name
  jurisdiction = "eu"
  domain       = var.cdn_host
  zone_id      = var.zone_id
  enabled      = true
  min_tls      = "1.2"
}

output "names" {
  description = "Имена бакетов: incoming, media, private (S3_BUCKET_*)."
  value       = { for key, bucket in cloudflare_r2_bucket.this : key => bucket.name }
}
