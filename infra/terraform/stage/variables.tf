# Значения — в terraform.tfvars (образец — stage.tfvars.example). Секретов здесь нет: токены
# приходят переменными окружения из .env, поэтому terraform.tfvars можно коммитить.

# --- Hetzner (0.25a) ---

variable "stage_server_type" {
  description = "Тип VM stage. CX23 по ADR-0015; на время нагрузочного прогона 8.3 — тип prod (CX33), потом обратно."
  type        = string
  default     = "cx23"
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
  description = "Образ ОС VM. Меняется только пересозданием VM (lifecycle.ignore_changes)."
  type        = string
  default     = "ubuntu-24.04"
}

variable "ssh_public_keys" {
  description = "Публичные SSH-ключи root: имя → «ssh-ed25519 …» (K15: ключ владельца и deploy-ключ stage для CI)."
  type        = map(string)

  validation {
    condition     = length(var.ssh_public_keys) > 0 && alltrue([for k in values(var.ssh_public_keys) : can(regex("^ssh-(ed25519|rsa) ", k))])
    error_message = "Нужен хотя бы один публичный ключ вида «ssh-ed25519 AAAA… comment»."
  }
}

variable "ssh_allowed_cidrs" {
  description = "Откуда открыт 22-й порт (Q13). По умолчанию — отовсюду, вход только по ключу: раннеры GitHub Actions ходят с меняющихся IP. Allowlist сломает деплой из CI."
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

variable "docker_network_cidr" {
  description = "Подсеть сети Docker «kamal»: её создаёт cloud-init, и она же — APP_TRUSTED_PROXIES в infra/kamal/deploy.yml."
  type        = string
  default     = "172.30.0.0/24"
}

# --- Cloudflare (0.25b) ---

variable "cloudflare_enabled" {
  description = "false — только Hetzner (0.25a, токена Cloudflare ещё нет); true — DNS, R2, WAF, SSL (0.25b)."
  type        = bool
  default     = false
}

variable "domain" {
  description = "Домен в Cloudflare (Q9; достаточно технического). Хосты stage — плоские (Q10): stage-app., stage-api., stage-cdn., stage-admin."
  type        = string
  default     = ""

  validation {
    condition     = var.domain == "" || can(regex("^[a-z0-9-]+(\\.[a-z0-9-]+)+$", var.domain))
    error_message = "Домен без схемы и точки в конце, например sosedi-test.com."
  }
}

variable "cloudflare_account_id" {
  description = "Account ID Cloudflare (K11, не секрет): Overview домена → блок API."
  type        = string
  default     = ""
}

variable "cloudflare_zone_id" {
  description = "Zone ID домена (K11, не секрет): там же, где Account ID."
  type        = string
  default     = ""
}

variable "mini_app_worker_deployed" {
  description = "true — Worker sosed-tma-stage уже задеплоен (первый wrangler deploy, 0.25d): тогда Terraform привязывает к нему stage-app.<domain>."
  type        = bool
  default     = false
}

variable "r2_bucket_prefix" {
  description = "Префикс бакетов R2 stage: <префикс>-incoming, -media, -private."
  type        = string
  default     = "sosed-stage"
}

variable "incoming_ttl_days" {
  description = "Сколько дней живут неподтверждённые загрузки в бакете incoming (ADR-0007): после проверки файл переезжает в media или private."
  type        = number
  default     = 2
}
