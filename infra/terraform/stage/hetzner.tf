# 0.25a: одна VM stage (ADR-0015 — всё на одной машине), firewall, SSH-ключи, бэкапы.

locals {
  # Края Cloudflare (https://www.cloudflare.com/ips/, сверено 2026-10) — тот же список, что
  # CLOUDFLARE_IPS в backend/src/app/platform/settings.py. 80 и 443 открыты только им: в обход
  # Cloudflare (WAF, rate limit) до kamal-proxy не достучаться. Список меняется редко; при
  # изменении — правка здесь и в settings.py (или APP_CLOUDFLARE_IPS без релиза).
  cloudflare_ips = [
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
  ]

  labels = {
    app = "sosed"
    env = "stage"
  }
}

resource "hcloud_ssh_key" "stage" {
  for_each = var.ssh_public_keys

  name       = "sosed-stage-${each.key}"
  public_key = each.value
  labels     = local.labels
}

resource "hcloud_firewall" "stage" {
  name   = "sosed-stage"
  labels = local.labels

  rule {
    description = "SSH только по ключу (Q13)"
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = var.ssh_allowed_cidrs
  }

  rule {
    description = "HTTPS только от Cloudflare (kamal-proxy, Full strict)"
    direction   = "in"
    protocol    = "tcp"
    port        = "443"
    source_ips  = local.cloudflare_ips
  }

  rule {
    description = "HTTP только от Cloudflare (kamal-proxy отвечает редиректом на HTTPS)"
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = local.cloudflare_ips
  }

  rule {
    description = "ping для диагностики"
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "stage" {
  name         = "sosed-stage-1"
  server_type  = var.stage_server_type
  image        = var.server_image
  location     = var.location
  ssh_keys     = [for key in hcloud_ssh_key.stage : key.id]
  firewall_ids = [hcloud_firewall.stage.id]
  backups      = true
  labels       = local.labels

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    docker_network_cidr = var.docker_network_cidr
  })

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  lifecycle {
    # cloud-init, образ и ключи действуют только при создании VM: их правка пересоздала бы stage
    # вместе с БД. Ключи на живой VM меняются по runbook (stage-bootstrap.md, «Ключи SSH»).
    ignore_changes = [user_data, image, ssh_keys]
  }
}
