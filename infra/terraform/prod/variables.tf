# Значения — в terraform.tfvars (образец — prod.tfvars.example). Секретов здесь нет: токены
# приходят переменными окружения из .env, поэтому terraform.tfvars можно коммитить.

# --- Hetzner (3.1a) ---

variable "app_server_type" {
  description = "Тип VM app-1 (web, bot, worker, worker-media, Valkey). CX33 по ADR-0015; итог 0.26 может поменять."
  type        = string
  default     = "cx33"
}

variable "db_server_type" {
  description = "Тип VM db-1 (PostgreSQL 18 + PostGIS, pgBackRest). CX33 по ADR-0015; рост — CX43 (§18)."
  type        = string
  default     = "cx33"
}

variable "location" {
  description = "Регион Hetzner (Q12): nbg1 или fsn1, задержка из Белграда ≈ 32–33 мс."
  type        = string
  default     = "nbg1"

  validation {
    condition     = contains(["nbg1", "fsn1"], var.location)
    error_message = "Только Германия (ADR-0015, ZZPL): nbg1 или fsn1."
  }
}

variable "server_image" {
  description = "Образ ОС обеих VM. Меняется только пересозданием VM (lifecycle.ignore_changes)."
  type        = string
  default     = "ubuntu-24.04"
}

variable "ssh_public_keys" {
  description = "Публичные SSH-ключи root на обеих VM: имя → «ssh-ed25519 …» (K15: ключ владельца и deploy-ключ prod — не тот, что у stage)."
  type        = map(string)

  validation {
    condition     = length(var.ssh_public_keys) > 0 && alltrue([for k in values(var.ssh_public_keys) : can(regex("^ssh-(ed25519|rsa) ", k))])
    error_message = "Нужен хотя бы один публичный ключ вида «ssh-ed25519 AAAA… comment»."
  }
}

variable "ssh_allowed_cidrs" {
  description = "Откуда открыт 22-й порт app-1 (Q13). По умолчанию — отовсюду, вход только по ключу: раннеры GitHub Actions ходят с меняющихся IP. db-1 снаружи SSH не слушает — только через app-1 (ProxyJump)."
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

variable "network_ip_range" {
  description = "Приватная сеть Hetzner prod. Firewall Hetzner её не фильтрует — на db-1 доступ режут ufw и pg_hba."
  type        = string
  default     = "10.20.0.0/16"
}

variable "subnet_ip_range" {
  description = "Подсеть VM prod (eu-central — nbg1 и fsn1). Из неё db-1 принимает PostgreSQL (pg_hba, ufw)."
  type        = string
  default     = "10.20.1.0/24"
}

variable "app_private_ip" {
  description = "Адрес app-1 в приватной сети."
  type        = string
  default     = "10.20.1.10"
}

variable "db_private_ip" {
  description = "Адрес db-1 в приватной сети: DB_DSN приложения и listen_addresses PostgreSQL."
  type        = string
  default     = "10.20.1.20"
}

variable "docker_network_cidr" {
  description = "Подсеть сети Docker «kamal» на app-1: её создаёт cloud-init, и она же — APP_TRUSTED_PROXIES в infra/kamal/deploy.production.yml."
  type        = string
  default     = "172.30.0.0/24"
}

# --- Cloudflare (3.1c) ---

variable "cloudflare_enabled" {
  description = "false — только Hetzner (3.1a–3.1b); true — DNS, R2, Origin CA (3.1c). Зона (SSL, WAF) — стек infra/terraform/zone."
  type        = bool
  default     = false
}

variable "domain" {
  description = "Домен в Cloudflare (Q9, Q8). Хосты prod: app., api., cdn., admin."
  type        = string
  default     = ""

  validation {
    condition     = var.domain == "" || can(regex("^[a-z0-9-]+(\\.[a-z0-9-]+)+$", var.domain))
    error_message = "Домен без схемы и точки в конце, например sosedi.rs."
  }
}

variable "cloudflare_account_id" {
  description = "Account ID Cloudflare (K11, не секрет)."
  type        = string
  default     = ""
}

variable "cloudflare_zone_id" {
  description = "Zone ID домена (K11, не секрет)."
  type        = string
  default     = ""
}

variable "mini_app_worker_deployed" {
  description = "true — Worker sosed-tma-production уже задеплоен (первый wrangler deploy, 3.1c): тогда Terraform привязывает к нему app.<domain>."
  type        = bool
  default     = false
}

variable "r2_bucket_prefix" {
  description = "Префикс бакетов R2 prod: <префикс>-incoming, -media, -private (K39)."
  type        = string
  default     = "sosed-prod"
}

variable "incoming_ttl_days" {
  description = "Сколько дней живут неподтверждённые загрузки в бакете incoming (ADR-0007)."
  type        = number
  default     = 2
}

# --- Cloudflare Access перед admin.<domain> (K30, K31) ---

variable "access_enabled" {
  description = "true — приложение Access на admin.<domain> (нужна организация Zero Trust, K31). Пока false, kamal-proxy admin.<domain> не обслуживает (ADMIN_PUBLISHED в деплое)."
  type        = bool
  default     = false
}

variable "access_emails" {
  description = "E-mail персонала, которых Access пускает в админку одноразовым кодом (K30)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.access_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", e))])
    error_message = "Список e-mail вида name@example.com."
  }
}

variable "access_session_duration" {
  description = "Сколько живёт вход Access в админку до повторного кода."
  type        = string
  default     = "12h"
}
