#!/usr/bin/env bash
# Временная VM restore-теста в проекте Hetzner specialist-backup (DEVELOPMENT_PLAN 3.2, K36): создать,
# удалить, подмести забытые. Только curl и jq к API Hetzner Cloud: нечего ставить и закреплять. Трогает
# лишь VM и SSH-ключи с меткой purpose=restore-test. Токен — HCLOUD_TOKEN проекта specialist-backup
# (K36, K19), не prod (K38). Вызывает .github/workflows/restore-test.yml:
#   restore-vm.sh create <run> <имя> <публичный ключ>  — в stdout vm_id=… и vm_ip=…
#   restore-vm.sh delete <run>                         — VM и ключи этого запуска
#   restore-vm.sh sweep                                — VM и ключи restore-теста старше 3 часов
set -euo pipefail

API=https://api.hetzner.cloud/v1
STALE_SECONDS=$((3 * 3600)) # дольше job не живёт (timeout-minutes 150)
# как db-1 (infra/terraform/prod: CX33, Ubuntu 24.04), в регионе бакета Hetzner
SERVER_TYPE=${SERVER_TYPE:-cx33}
SERVER_IMAGE=${SERVER_IMAGE:-ubuntu-24.04}
LOCATION=${LOCATION:-nbg1}
: "${HCLOUD_TOKEN:?HCLOUD_TOKEN — токен проекта specialist-backup (K36, K19)}"

say() { echo "restore-vm: $*" >&2; }
api() { # ответ — в stdout; ошибку API (тип сервера, лимит проекта…) — в лог, а не в переменную
  local body rc
  if body=$(curl -sS --fail-with-body -m 30 -H "Authorization: Bearer $HCLOUD_TOKEN" "$@"); then
    printf '%s\n' "$body"
  else
    rc=$?
    say "API Hetzner: ${body:0:500}"
    return "$rc"
  fi
}

list() { # list <servers|ssh_keys> <label_selector> <старше, с> — строки «id имя»
  api -G "$API/$1" --data-urlencode "label_selector=$2" --data-urlencode per_page=50 |
    jq -r --arg kind "$1" --argjson age "$3" --argjson now "$(date +%s)" '
      .[$kind][]
      | select($now - (.created | sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601) >= $age)
      | "\(.id) \(.name)"'
}

remove() { # remove <label_selector> <старше, с>: сначала VM, потом ключи
  local kind id name
  for kind in servers ssh_keys; do
    list "$kind" "$1" "$2" | while read -r id name; do
      say "удаляю $kind/$name"
      api -X DELETE -o /dev/null "$API/$kind/$id"
    done
  done
}

create() { # create <run> <имя> <публичный ключ>
  local run=$1 name=$2 key_id server id ip status
  key_id=$(api -X POST "$API/ssh_keys" -H 'Content-Type: application/json' -d "$(
    jq -n --arg name "$name" --arg key "$(< "$3")" --arg run "$run" \
      '{name: $name, public_key: $key, labels: {purpose: "restore-test", run: $run}}'
  )" | jq -r '.ssh_key.id')
  server=$(api -X POST "$API/servers" -H 'Content-Type: application/json' -d "$(
    jq -n --arg name "$name" --arg type "$SERVER_TYPE" --arg image "$SERVER_IMAGE" \
      --arg location "$LOCATION" --argjson key "$key_id" --arg run "$run" \
      '{name: $name, server_type: $type, image: $image, location: $location, ssh_keys: [$key],
        start_after_create: true, public_net: {enable_ipv4: true, enable_ipv6: false},
        labels: {purpose: "restore-test", run: $run}}'
  )")
  id=$(jq -r '.server.id' <<< "$server")
  ip=$(jq -r '.server.public_net.ipv4.ip' <<< "$server")
  say "VM $name ($id, $ip): $SERVER_TYPE, $LOCATION"
  for _ in $(seq 60); do
    status=$(api "$API/servers/$id" | jq -r '.server.status')
    [[ "$status" == running ]] && break
    sleep 5
  done
  [[ "$status" == running ]] || {
    say "VM не запустилась за 5 минут: $status"
    exit 1
  }
  echo "vm_id=$id"
  echo "vm_ip=$ip"
}

case "${1:-}" in
  create) create "$2" "$3" "$4" ;;
  delete) remove "purpose=restore-test,run=$2" 0 ;;
  sweep) remove "purpose=restore-test" "$STALE_SECONDS" ;;
  *)
    echo "usage: $0 create <run> <имя> <ключ.pub> | delete <run> | sweep" >&2
    exit 2
    ;;
esac
