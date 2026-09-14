#!/usr/bin/env bash
# Grants saw_readonly exactly SELECT and nothing else — the security model
# in CLAUDE.md requires every catalog query and every piece of arbitrary
# user SQL to run only as this role.
#
# museum_network is guarded with an existence check in bash (rather than a
# SQL DO block — psql's :"var" substitution does not reach inside $$ ... $$
# bodies): before Etap 1 lands, db/museum has no schema-creating SQL yet
# (see 40_init_museum.sh), so on a fresh Etap-0-only checkout the schema
# genuinely doesn't exist. Skipping with a message keeps `make reset` green
# at every stage instead of failing here until Etap 1 is done.
set -euo pipefail

schema_exists=$(psql -tAc \
  "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'museum_network')" \
  --username "$POSTGRES_USER" --dbname "$MUSEUM_DB")

if [ "$schema_exists" = "t" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$MUSEUM_DB" \
      -v readonly_user="$SAW_READONLY_USER" \
      -v admin_user="$SAW_ADMIN_USER" <<-'EOSQL'
        GRANT USAGE ON SCHEMA museum_network TO :"readonly_user";
        GRANT SELECT ON ALL TABLES IN SCHEMA museum_network TO :"readonly_user";
        GRANT SELECT ON ALL SEQUENCES IN SCHEMA museum_network TO :"readonly_user";
        ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_user" IN SCHEMA museum_network
            GRANT SELECT ON TABLES TO :"readonly_user";
EOSQL
else
    echo "museum_network schema not found yet - grants will apply once db/museum schema scripts exist (Etap 1)." >&2
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DVDRENTAL_DB" \
  -v readonly_user="$SAW_READONLY_USER" <<-'EOSQL'
    GRANT USAGE ON SCHEMA public TO :"readonly_user";
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"readonly_user";
    GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO :"readonly_user";
EOSQL
