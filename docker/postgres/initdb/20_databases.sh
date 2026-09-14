#!/usr/bin/env bash
# Creates the two application databases, owned by saw_admin from the start
# so that every object created by later init scripts (museum schema,
# dvdrental restore) already has the right owner — no ALTER ... OWNER TO
# passes needed afterwards.
#
# Extensions required by ROADMAP.md Etap 0 / SPEC.md §2.2.4 are enabled here:
#   pg_stat_statements — query stats (ФВ-08), needs shared_preload_libraries
#                        (set in docker-compose.yml) plus CREATE EXTENSION
#                        per database it's queried from.
#   btree_gist          — needed by the EXCLUDE USING gist constraints on
#                        exhibitions and ticket_prices (Etap 1).
#   pg_trgm              — needed by the GIN index on visitor_feedback.comment
#                        (Etap 9).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    SELECT 'CREATE DATABASE "$MUSEUM_DB" OWNER "$SAW_ADMIN_USER"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$MUSEUM_DB')\gexec

    SELECT 'CREATE DATABASE "$DVDRENTAL_DB" OWNER "$SAW_ADMIN_USER"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DVDRENTAL_DB')\gexec
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$MUSEUM_DB" <<-'EOSQL'
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
    CREATE EXTENSION IF NOT EXISTS btree_gist;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DVDRENTAL_DB" <<-'EOSQL'
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
EOSQL
