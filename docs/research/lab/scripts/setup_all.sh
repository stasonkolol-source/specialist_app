#!/usr/bin/env bash
# Rebuilds the whole lab database state from scratch inside the running container.
# Usage (from docs/research/lab):  ./scripts/setup_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PSQL=(docker compose -p specialist-lab exec -T postgres psql -U lab -d lab -X -v ON_ERROR_STOP=1)
run() { echo ">> $1"; "${PSQL[@]}" -f "/lab/sql/$1" > "results/$2" 2>&1 || { echo "FAILED: $1 (see results/$2)"; exit 1; }; }
run_noerr() { echo ">> $1"; docker compose -p specialist-lab exec -T postgres psql -U lab -d lab -X -f "/lab/sql/$1" > "results/$2" 2>&1; }
run 00_extensions.sql        00_extensions.txt
run 01_locale_providers.sql  01_locale_providers.txt
run_noerr 02_fts_ru_sr.sql   02_fts_ru_sr.txt   # contains intentional ERROR demos (IMMUTABLE)
run 03_search_functions.sql  03_search_functions.txt
run 10_schema.sql            10_schema.txt
run 11_seed_reference.sql    11_seed_reference.txt
run 12_seed_data.sql         12_seed_data.txt
run 13_indexes_base.sql      13_indexes_base.txt
run 14_readmodel.sql         14_readmodel.txt
run 15_indexes_search.sql    15_indexes_search.txt
for f in 04_trgm_typos_translit 05_geo_basics 06_i18n_collations 16_crosslang_demo; do run $f.sql $f.txt; done
echo "done"
