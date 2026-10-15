#!/bin/bash
# Runs once, on the first start of the postgres volume.
# The app connects as relay_app (not a superuser), so Postgres row-level security applies to it.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE relay_app LOGIN PASSWORD '${APP_DB_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT ALL ON SCHEMA public TO relay_app;
CREATE DATABASE kestra OWNER $POSTGRES_USER;
CREATE DATABASE warehouse OWNER relay_app;
SQL
