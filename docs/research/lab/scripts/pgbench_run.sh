#!/usr/bin/env bash
# Mixed read/write workload with pgbench from a separate container (service "bench", 2 CPUs),
# prepared statements (like asyncpg), per-script latency percentiles from per-transaction logs.
# Usage: docker compose -p specialist-lab --profile bench run --rm bench /lab/scripts/pgbench_run.sh
#   env: DUR (s, default 30), CLIENTS (default "1 8 16 32"), TAG (default "noparallel"),
#        PGOPTIONS (default "-c max_parallel_workers_per_gather=0")
set -euo pipefail
cd /lab
DUR=${DUR:-30}
CLIENTS=${CLIENTS:-"1 8 16 32"}
TAG=${TAG:-noparallel}
export PGOPTIONS=${PGOPTIONS-"-c max_parallel_workers_per_gather=0"}
OUT=results/pgbench; mkdir -p "$OUT"
psql -X -q -v ON_ERROR_STOP=1 -f sql/pgbench/00_prepare.sql
S=sql/pgbench
SCRIPTS=(a_search_cat_city.sql@25 b_search_radius.sql@15 c_search_fts.sql@20 d_board_city_cats.sql@15
         e_board_radius.sql@5 f_match_new_request.sql@5 g_autocomplete.sql@10 w_update_specialist.sql@4 w_insert_request.sql@1)
ARGS=(); for s in "${SCRIPTS[@]}"; do ARGS+=(-f "$S/$s"); done
summary="$OUT/summary_${TAG}.tsv"
printf "clients\ttps\tscript\ttx\tp50_ms\tp95_ms\tp99_ms\tmax_ms\n" > "$summary"
for c in $CLIENTS; do
  j=$(( c < 2 ? 1 : 2 ))
  rm -f /tmp/pgb_log*
  pgbench -n -M prepared -c "$c" -j "$j" -T "$DUR" -P 10 -r --log --log-prefix=/tmp/pgb_log "${ARGS[@]}" > "$OUT/mixed_${TAG}_c${c}.txt" 2>&1
  tps=$(sed -n 's/^tps = \([0-9.]*\).*/\1/p' "$OUT/mixed_${TAG}_c${c}.txt" | head -1)
  # log line: client_id transaction_no time_us script_no epoch us   (mawk-compatible percentile calc)
  cat /tmp/pgb_log* > /tmp/all.log
  pstats() { sort -n | awk '{a[NR]=$1} END {if (NR==0) exit; i50=int(NR*0.50+0.999999); i95=int(NR*0.95+0.999999); i99=int(NR*0.99+0.999999);
             printf "%d\t%.2f\t%.2f\t%.2f\t%.2f", NR, a[i50], a[i95], a[i99], a[NR]}'; }
  for sn in $(awk '{print $4}' /tmp/all.log | sort -un); do
    st=$(awk -v s="$sn" '$4==s {print $3/1000.0}' /tmp/all.log | pstats)
    printf "%s\t%s\t%s\t%s\n" "$c" "$tps" "$sn" "$st" >> "$summary"
  done
  st=$(awk '{print $3/1000.0}' /tmp/all.log | pstats)
  printf "%s\t%s\tALL\t%s\n" "$c" "$tps" "$st" >> "$summary"
  echo "clients=$c tps=$tps"
done
psql -X -q -c "DELETE FROM mp.request WHERE title = 'Bench request: popravka'" -c "DROP TABLE mp.bench_spec_ids"
echo "script index -> file:"; i=0; for s in "${SCRIPTS[@]}"; do echo "  $i ${s%@*}"; i=$((i+1)); done | tee "$OUT/script_index.txt"
cat "$summary"
