#!/bin/bash
# Creates the Logto database on first Postgres volume initialization.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE logto OWNER ' || quote_ident('$POSTGRES_USER')
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'logto')\gexec
EOSQL
