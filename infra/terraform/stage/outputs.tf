# Несекретные значения можно смотреть: make tf ENV=stage ARGS='output stage_ipv4'. Ключ и
# сертификат Origin CA — sensitive: только трубой в секреты stage (runbook, шаг 0.25c), не в терминал.

output "stage_ipv4" {
  description = "IPv4 VM stage — переменная STAGE_HOST (Kamal) и известный хост для ssh."
  value       = hcloud_server.stage.ipv4_address
}

output "stage_ipv6" {
  description = "IPv6 VM stage."
  value       = hcloud_server.stage.ipv6_address
}

output "r2_buckets" {
  description = "Бакеты R2 stage: S3_BUCKET_INCOMING, S3_BUCKET_MEDIA, S3_BUCKET_PRIVATE."
  value       = one(module.r2[*].names)
}

output "r2_s3_endpoint" {
  description = "S3 endpoint бакетов EU jurisdiction: S3_ENDPOINT_URL и TMA_STORAGE_ORIGINS."
  value       = var.cloudflare_account_id == "" ? null : "https://${var.cloudflare_account_id}.eu.r2.cloudflarestorage.com"
}

output "origin_certificate_pem" {
  description = "Сертификат Origin CA для kamal-proxy (секрет KAMAL_PROXY_SSL_CERT)."
  value       = one(cloudflare_origin_ca_certificate.origin[*].certificate)
  sensitive   = true
}

output "origin_private_key_pem" {
  description = "Ключ сертификата Origin CA (секрет KAMAL_PROXY_SSL_KEY)."
  value       = one(tls_private_key.origin[*].private_key_pem)
  sensitive   = true
}
