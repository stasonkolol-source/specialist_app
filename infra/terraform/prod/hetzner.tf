# 3.1a: две VM prod (ADR-0015) — app-1 (процессы backend, Valkey, kamal-proxy) и db-1 (PostgreSQL
# 18 + PostGIS, pgBackRest) — в приватной сети, firewall, SSH-ключи, бэкапы Hetzner.

module "edge" {
  source = "../modules/edge-ips"
}

locals {
  labels = {
    app = "sosed"
    env = "prod"
  }
}

resource "hcloud_ssh_key" "prod" {
  for_each = var.ssh_public_keys

  name       = "sosed-prod-${each.key}"
  public_key = each.value
  labels     = local.labels
}

# --- Приватная сеть: приложение ходит в БД только по ней ---

resource "hcloud_network" "prod" {
  name              = "sosed-prod"
  ip_range          = var.network_ip_range
  delete_protection = true
  labels            = local.labels
}

resource "hcloud_network_subnet" "prod" {
  network_id   = hcloud_network.prod.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = var.subnet_ip_range
}

# app-1 и db-1 — на разных физических хостах: отказ одного железа не уносит обе VM
resource "hcloud_placement_group" "prod" {
  name   = "sosed-prod"
  type   = "spread"
  labels = local.labels
}

# --- Firewall (фильтрует только публичный интерфейс; приватную сеть на db-1 режут ufw и pg_hba) ---

resource "hcloud_firewall" "app" {
  name   = "sosed-prod-app"
  labels = local.labels

  rule {
    description = "SSH только по ключу (Q13); через app-1 же — вход на db-1"
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
    source_ips  = module.edge.cloudflare_ips
  }

  rule {
    description = "HTTP только от Cloudflare (kamal-proxy отвечает редиректом на HTTPS)"
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = module.edge.cloudflare_ips
  }

  rule {
    description = "ping для диагностики"
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
}

# db-1 снаружи не принимает ничего, кроме ping: входящих правил на 22 и 5432 нет, значит Hetzner их
# отбрасывает. Публичный адрес у db-1 остаётся ради исходящих: apt и pgBackRest → Object Storage и B2.
resource "hcloud_firewall" "db" {
  name   = "sosed-prod-db"
  labels = local.labels

  rule {
    description = "ping для диагностики"
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
}

# --- VM ---

resource "hcloud_server" "app" {
  name               = "sosed-prod-app-1"
  server_type        = var.app_server_type
  image              = var.server_image
  location           = var.location
  ssh_keys           = [for key in hcloud_ssh_key.prod : key.id]
  firewall_ids       = [hcloud_firewall.app.id]
  placement_group_id = hcloud_placement_group.prod.id
  backups            = true
  # destroy и rebuild — только после явного снятия защиты в tfvars-коммите, не случайным apply
  delete_protection  = true
  rebuild_protection = true
  labels             = merge(local.labels, { role = "app" })

  user_data = templatefile("${path.module}/cloud-init-app.yaml.tftpl", {
    docker_network_cidr = var.docker_network_cidr
  })

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  network {
    network_id = hcloud_network.prod.id
    ip         = var.app_private_ip
  }

  # VM подключается к сети только после того, как в ней есть подсеть
  depends_on = [hcloud_network_subnet.prod]

  lifecycle {
    # cloud-init, образ и ключи действуют только при создании VM: их правка пересоздала бы app-1.
    # Ключи на живой VM меняются по runbook (prod-bootstrap.md, «Ключи SSH»).
    ignore_changes = [user_data, image, ssh_keys]
  }
}

resource "hcloud_server" "db" {
  name               = "sosed-prod-db-1"
  server_type        = var.db_server_type
  image              = var.server_image
  location           = var.location
  ssh_keys           = [for key in hcloud_ssh_key.prod : key.id]
  firewall_ids       = [hcloud_firewall.db.id]
  placement_group_id = hcloud_placement_group.prod.id
  backups            = true
  delete_protection  = true
  rebuild_protection = true
  labels             = merge(local.labels, { role = "db" })

  user_data = templatefile("${path.module}/cloud-init-db.yaml.tftpl", {
    subnet_ip_range = var.subnet_ip_range
  })

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  network {
    network_id = hcloud_network.prod.id
    ip         = var.db_private_ip
  }

  depends_on = [hcloud_network_subnet.prod]

  lifecycle {
    # Пересоздание db-1 — это потеря данных (восстановление — только restore.md): Terraform
    # откажется строить такой план, а не выполнит его.
    prevent_destroy = true
    ignore_changes  = [user_data, image, ssh_keys]
  }
}
