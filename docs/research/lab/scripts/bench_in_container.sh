#!/usr/bin/env bash
# Runs every sql/bench/*.sql N times with EXPLAIN (ANALYZE, BUFFERS) inside the postgres container
# (psql over the local Unix socket), keeps the plan of the last run in results/bench/<name>.txt
# and writes a summary TSV. Server-side "Execution Time" is used, so client/network overhead is excluded.
#
# Usage (from docs/research/lab):
#   docker compose -p specialist-lab exec -T postgres bash /lab/scripts/bench_in_container.sh           # all
#   docker compose -p specialist-lab exec -T -e N=11 postgres bash /lab/scripts/bench_in_container.sh a0 # subset
#   docker compose -p specialist-lab exec -T -e TAG=noparallel -e PGOPTIONS="-c max_parallel_workers_per_gather=0" postgres bash /lab/scripts/bench_in_container.sh
set -uo pipefail
N=${N:-7}
FILTER=${1:-}
cd /lab
PLANDIR=results/bench${TAG:+_$TAG}; mkdir -p "$PLANDIR"
summary=results/bench_summary${TAG:+_$TAG}${FILTER:+_$FILTER}.tsv
printf "query\twarm_runs\tcold_exec_ms\tcold_plan_ms\tmin_ms\tmedian_ms\tmax_ms\tplanning_median_ms\trows_top_node\tshared_hit_top\tshared_read_top\n" > "$summary"

median() { sort -n | awk '{a[NR]=$1} END {if (NR==0) {print "NA"} else if (NR%2) {print a[(NR+1)/2]} else {printf "%.3f\n", (a[NR/2]+a[NR/2+1])/2}}'; }

for f in sql/bench/*${FILTER}*.sql; do
  name=$(basename "$f" .sql)
  : > /tmp/ex.txt; : > /tmp/pl.txt
  # one session = one pooled connection: run 1 is "cold" (fresh backend, empty catalog caches),
  # runs 2..N+1 are "warm" and give the reported min/median/max
  : > /tmp/runner.psql
  for i in $(seq 0 "$N"); do echo "\\i $f" >> /tmp/runner.psql; done
  all=$(psql -U lab -d lab -X -q -v ON_ERROR_STOP=1 -f /tmp/runner.psql 2>&1)
  printf '%s\n' "$all" | sed -n 's/.*Execution Time: \([0-9.]*\) ms.*/\1/p' > /tmp/ex_all.txt
  printf '%s\n' "$all" | sed -n 's/.*Planning Time: \([0-9.]*\) ms.*/\1/p' > /tmp/pl_all.txt
  first=$(head -1 /tmp/ex_all.txt); first_pl=$(head -1 /tmp/pl_all.txt)
  tail -n +2 /tmp/ex_all.txt > /tmp/ex.txt; tail -n +2 /tmp/pl_all.txt > /tmp/pl.txt
  # keep the plan of the last run
  out=$(printf '%s\n' "$all" | awk '/QUERY PLAN/{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}')
  printf '%s\n' "$out" > "$PLANDIR/$name.txt"
  top=$(printf '%s\n' "$out" | grep -m1 -E 'actual time=')
  rows=$(printf '%s\n' "$top" | sed -n 's/.*rows=\([0-9.]*\) loops.*/\1/p')
  bufline=$(printf '%s\n' "$out" | grep -m1 -E '^\s*Buffers:')
  hit=$(printf '%s\n' "$bufline" | sed -n 's/.*shared hit=\([0-9]*\).*/\1/p')
  rd=$(printf '%s\n' "$bufline" | sed -n 's/.*read=\([0-9]*\).*/\1/p')
  mn=$(sort -n /tmp/ex.txt | head -1); mx=$(sort -n /tmp/ex.txt | tail -1)
  md=$(median < /tmp/ex.txt); pmd=$(median < /tmp/pl.txt)
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$name" "$(wc -l < /tmp/ex.txt | tr -d ' ')" "$first" "$first_pl" "$mn" "$md" "$mx" "$pmd" "${rows:-NA}" "${hit:-0}" "${rd:-0}" >> "$summary"
  printf "%-50s median %8s ms (min %s, max %s) plan %s ms | cold exec %s plan %s | rows=%s\n" "$name" "$md" "$mn" "$mx" "$pmd" "$first" "$first_pl" "${rows:-NA}"
done
