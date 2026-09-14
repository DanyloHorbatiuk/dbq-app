#!/usr/bin/env bash
# Restores the dvdrental sample database from db/dvdrental/dvdrental.tar.
# The dump is not committed to the repo (size) — README.md tells the user
# to place it manually before `make up` / `make reset`. If it's missing,
# the stack still comes up; dvdrental is just empty, and we say so loudly
# instead of failing the whole init sequence.
#
# --no-owner + --role: connect as the postgres superuser but have pg_restore
# issue SET ROLE saw_admin before restoring, so every restored object ends
# up owned by saw_admin (consistent with how 20_databases.sh created the
# database) without needing saw_admin's own restore privileges.
set -euo pipefail

DUMP_PATH="/db/dvdrental/dvdrental.tar"

if [ ! -f "$DUMP_PATH" ]; then
    echo "WARNING: $DUMP_PATH not found - skipping dvdrental restore." >&2
    echo "Place the dump at db/dvdrental/dvdrental.tar and run 'make reset'." >&2
    exit 0
fi

pg_restore --username "$POSTGRES_USER" --dbname "$DVDRENTAL_DB" \
  --no-owner --role "$SAW_ADMIN_USER" --clean --if-exists "$DUMP_PATH"
