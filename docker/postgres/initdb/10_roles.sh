#!/usr/bin/env bash
# Creates the two application roles the rest of the system relies on:
#   saw_admin    — owns the museum schema; used only for schema bootstrap
#                  and index experiments (never for user-submitted SQL).
#   saw_readonly — SELECT-only; the role every catalog query and every
#                  piece of arbitrary user SQL runs as (CLAUDE.md security
#                  rule — not negotiable).
# Values come from the environment (ultimately .env), never hardcoded, so
# this script stays safe to commit.
#
# CREATE ROLE has no IF NOT EXISTS, so existence is checked with a WHERE
# clause and the statement is only generated (and run, via \gexec) when the
# role is missing — this is what makes the script rerunnable.
#
# Note: psql's :'var' / :"var" substitution is skipped inside dollar-quoted
# ($$ ... $$) bodies, so this deliberately avoids DO blocks and uses
# \gexec instead.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v admin_user="$SAW_ADMIN_USER" \
  -v admin_password="$SAW_ADMIN_PASSWORD" \
  -v readonly_user="$SAW_READONLY_USER" \
  -v readonly_password="$SAW_READONLY_PASSWORD" <<-'EOSQL'
    SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L CREATEDB', :'admin_user', :'admin_password')
    WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'admin_user')
    \gexec

    SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'readonly_user', :'readonly_password')
    WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'readonly_user')
    \gexec
EOSQL
