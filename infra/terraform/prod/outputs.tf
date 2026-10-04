# Несекретные значения можно смотреть: make tf ENV=prod ARGS='output app_ipv4'. Ключ и сертификат
# Origin CA — sensitive: только трубой в секреты production (prod-bootstrap.md), не в терминал.

output "app_ipv4" {
  description = "IPv4 app-1 — переменная PROD_HOST (Kamal, CI) и вход по SSH (через него же — на db-1)."
  value       = hcloud_server.app.ipv4_address
}

output "app_ipv6" {
  description = "IPv6 app-1."
  value       = hcloud_server.app.ipv6_address
}

output "db_private_ip" {
  description = "Адрес db-1 в приватной сети — переменная PROD_DB_IP: DB_DSN приложения, ProxyJump, pg-smoke."
  value       = var.db_private_ip
}

output "db_ipv4" {
  description = "Публичный IPv4 db-1 — только для проверки, что снаружи порт 5432 закрыт (nc -z → отказ)."
  value       = hcloud_server.db.ipv4_address
}

output "r2_buckets" {
  description = "Бакеты R2 prod: S3_BUCKET_INCOMING, S3_BUCKET_MEDIA, S3_BUCKET_PRIVATE."
  value       = one(module.r2[*].names)
}

output "r2_s3_endpoint" {
  description = "S3 endpoint бакетов EU jurisdiction: S3_ENDPOINT_URL и TMA_STORAGE_ORIGINS."
  value       = var.cloudflare_account_id == "" ? null : "https://${var.cloudflare_account_id}.eu.r2.cloudflarestorage.com"
}

output "origin_certificate_pem" {
  description = "Сертификат Origin CA для kamal-proxy (секрет KAMAL_PROXY_SSL_CERT, api. и admin.)."
  value       = one(cloudflare_origin_ca_certificate.origin[*].certificate)
  sensitive   = true
}

output "origin_private_key_pem" {
  description = "Ключ сертификата Origin CA (секрет KAMAL_PROXY_SSL_KEY)."
  value       = one(tls_private_key.origin[*].private_key_pem)
  sensitive   = true
}
