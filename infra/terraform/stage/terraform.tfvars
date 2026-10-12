# Stage: VM в Hetzner и Cloudflare (DNS, R2, сертификат). Секретов нет (токены — в .env).
# Шаг 1 (0.25a): только VM; шаг 2 (0.25b): cloudflare_enabled = true.

stage_server_type = "cx23"
location          = "nbg1" # Q12
ssh_public_keys = {
  owner  = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINtK2ed5nTWP7wZ9jkLnnR43LtukdDHvfObjkgl4Wj0t owner"
  deploy = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFxyZrGnGhUC53TdLD147b+VZHOpmNH93jSOvIO1D782 deploy-stage"
}

cloudflare_enabled    = true
domain                = "sosedirs.com"
cloudflare_account_id = "3a5c28947e30164b79eb78d773e941f9"
cloudflare_zone_id    = "74f5a67425552004d068a881454ca16d"

mini_app_worker_deployed = true
