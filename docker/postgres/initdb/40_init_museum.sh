#!/usr/bin/env bash
# Applies db/museum/NN_*.sql files in numeric filename order, as saw_admin,
# so every created object is owned by the role the app's admin pool connects
# as. This script itself never changes — ROADMAP.md stages add files
# (01_schema.sql, 02_constraints.sql, ...) and they get picked up
# automatically on the next `make reset`.
#
# Right now (Etap 0) db/museum only has legacy_schema.sql, which is a
# reference snapshot, not meant to be executed — so with no NN_*.sql files
# present yet this script is a deliberate no-op.
set -euo pipefail

SQL_DIR="/db/museum"

shopt -s nullglob
files=("$SQL_DIR"/[0-9][0-9]_*.sql)
shopt -u nullglob

if [ ${#files[@]} -eq 0 ]; then
    echo "No db/museum/NN_*.sql files yet - skipping museum schema init (expected before Etap 1)." >&2
    exit 0
fi

for f in $(printf '%s\n' "${files[@]}" | sort); do
    echo "Applying $f ..."
    psql -v ON_ERROR_STOP=1 --username "$SAW_ADMIN_USER" --dbname "$MUSEUM_DB" -f "$f"
done
