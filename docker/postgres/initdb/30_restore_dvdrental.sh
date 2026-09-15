#!/usr/bin/env bash
# Restores the dvdrental sample database from db/dvdrental/dvdrental.tar.
# The dump is not committed to the repo (size) — README.md tells the user
# to place it manually before `make up` / `make reset`. If it's missing,
# the stack still comes up; dvdrental is just empty, and we say so loudly
# instead of failing the whole init sequence.
#
# The public dvdrental.tar in circulation was pg_dump'd from PostgreSQL 9.2
# and its TOC includes SCHEMA public, EXTENSION plpgsql and their COMMENT/ACL
# entries — all owned by that original superuser. Every fresh database
# already has both (PostgreSQL creates them at CREATE DATABASE time), so
# restoring them is never necessary, and under --role "$SAW_ADMIN_USER"
# (a non-superuser) pg_restore can't take ownership of them anyway
# ("must be owner of extension plpgsql"). With --clean that error aborted
# pg_restore entirely under `set -euo pipefail`, taking 40_init_museum.sh
# and 50_grants.sh down with it even though every actual table restored
# fine. Filtering those five TOC entries out via --use-list avoids the
# error instead of working around its exit code.
set -euo pipefail

DUMP_PATH="/db/dvdrental/dvdrental.tar"

if [ ! -f "$DUMP_PATH" ]; then
    echo "WARNING: $DUMP_PATH not found - skipping dvdrental restore." >&2
    echo "Place the dump at db/dvdrental/dvdrental.tar and run 'make reset'." >&2
    exit 0
fi

# A common mistake: the tutorial page links a .zip that *contains*
# dvdrental.tar, and it's easy to drop the zip itself in place unextracted.
# Zip files start with the two bytes "PK" — a real pg_dump tar starts with
# a tar header (a filename), never that.
if head -c 2 "$DUMP_PATH" | grep -q '^PK'; then
    echo "ERROR: $DUMP_PATH looks like a .zip file, not a pg_dump tar archive." >&2
    echo "Unzip it first and place the .tar file it contains at this path." >&2
    exit 1
fi

FILTERED_LIST="/tmp/dvdrental_restore.list"
pg_restore --list "$DUMP_PATH" \
  | grep -vE '(SCHEMA|EXTENSION|ACL) - (public|plpgsql)( |$)|COMMENT - (SCHEMA public|EXTENSION plpgsql)' \
  > "$FILTERED_LIST"

# --no-owner + --role: connect as the postgres superuser but have pg_restore
# issue SET ROLE saw_admin before restoring, so every restored object ends
# up owned by saw_admin (consistent with how 20_databases.sh created the
# database) without needing saw_admin's own restore privileges.
# --exit-on-error is explicit (pg_restore's default under --single-transaction
# would be all-or-nothing; without it, non-fatal errors are only warned about
# and counted) — with the five problem entries filtered out, any error that
# does occur here is real and should stop the init sequence, per set -e.
pg_restore --username "$POSTGRES_USER" --dbname "$DVDRENTAL_DB" \
  --no-owner --role "$SAW_ADMIN_USER" --clean --if-exists \
  --exit-on-error --use-list="$FILTERED_LIST" \
  "$DUMP_PATH"

rm -f "$FILTERED_LIST"

# Fresh statistics before anything benchmarks against this data — same
# reasoning as db/museum/07_generate_data.sql's own closing ANALYZE.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DVDRENTAL_DB" -c "ANALYZE;"
