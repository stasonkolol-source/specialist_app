# 0.25a: одна VM stage (ADR-0015 — всё на одной машине), firewall, SSH-ключи, бэкапы.

module "edge" {
  source = "../modules/edge-ips"
}

locals {
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
