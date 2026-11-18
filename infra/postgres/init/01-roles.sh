#!/usr/bin/env bash
# OPTIONAL / DOCKER ONLY: not used for local development. For native PostgreSQL use
# infra/postgres/local-setup.sql instead (same role model).
#
# Runs once, on first initialization of an empty data volume (docker-entrypoint-initdb.d).
# Creates the role model from docs/database-design.md §8.1:
#   - owner/migration role: owns the database and the public schema; used only by Alembic
#   - application role:     NOSUPERUSER NOBYPASSRLS, not an owner; used by the API/worker
# Table-level grants are added per table by migrations (Phase 2.2), so the application role
# gets no blanket table privileges here.
#
# Passwords are passed as psql variables (:'var') so they are quoted safely and never
# interpolated into SQL by the shell.
set -euo pipefail

: "${MUNIM_OWNER_ROLE:?}" "${MUNIM_OWNER_PASSWORD:?}" "${MUNIM_APP_ROLE:?}" "${MUNIM_APP_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v db="$POSTGRES_DB" \
  -v owner_role="$MUNIM_OWNER_ROLE" \
  -v owner_pw="$MUNIM_OWNER_PASSWORD" \
  -v app_role="$MUNIM_APP_ROLE" \
  -v app_pw="$MUNIM_APP_PASSWORD" <<'SQL'
-- Roles
CREATE ROLE :"owner_role" LOGIN PASSWORD :'owner_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE :"app_role" LOGIN PASSWORD :'app_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

-- Database: owned by the migration role; nobody else may connect by default
ALTER DATABASE :"db" OWNER TO :"owner_role";
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO :"owner_role";
GRANT CONNECT ON DATABASE :"db" TO :"app_role";

-- Schema: owner creates objects; app may only use what it is explicitly granted
ALTER SCHEMA public OWNER TO :"owner_role";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app_role";

-- Sensible session defaults for the app role
ALTER ROLE :"app_role" SET statement_timeout = '15s';
ALTER ROLE :"app_role" SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE :"app_role" SET timezone = 'UTC';
ALTER ROLE :"owner_role" SET timezone = 'UTC';
SQL

echo "munim: created roles '${MUNIM_OWNER_ROLE}' (owner) and '${MUNIM_APP_ROLE}' (application)"
