-- Verifies the runtime role model (architecture §9.2, SV-2). Run it AS THE APPLICATION
-- ROLE, connected to the project database. Native PostgreSQL on Windows (PowerShell):
--
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -U munim_app -d munim_ai -v ON_ERROR_STOP=1 -f infra/postgres/verify-roles.sql
--
-- Exits non-zero (with an error naming the problem) if the connected role:
--   - is a superuser, can bypass RLS, can create roles or databases
--   - inherits privileges or is a member of any other role
--   - owns the database or the public schema
--   - can create objects in the database or the public schema, or create temp tables
--   - owns any table, view, sequence or function in the database
-- Prints only role attributes; no secrets.

DO $$
DECLARE
  r record;
BEGIN
  SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolinherit
    INTO r FROM pg_catalog.pg_roles WHERE rolname = current_user;

  IF r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb THEN
    RAISE EXCEPTION 'role % has unsafe attributes (superuser/bypassrls/createrole/createdb)', current_user;
  END IF;
  IF r.rolinherit THEN
    RAISE EXCEPTION 'role % must be NOINHERIT', current_user;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m
             JOIN pg_catalog.pg_roles u ON u.oid = m.member
             WHERE u.rolname = current_user) THEN
    RAISE EXCEPTION 'role % is a member of another role', current_user;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_database
             WHERE datname = current_database()
               AND pg_catalog.pg_get_userbyid(datdba) = current_user) THEN
    RAISE EXCEPTION 'role % owns the database', current_user;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_namespace
             WHERE nspname = 'public'
               AND pg_catalog.pg_get_userbyid(nspowner) = current_user) THEN
    RAISE EXCEPTION 'role % owns the public schema', current_user;
  END IF;
  IF pg_catalog.has_database_privilege(current_user, current_database(), 'CREATE') THEN
    RAISE EXCEPTION 'role % can create schemas in the database', current_user;
  END IF;
  IF pg_catalog.has_database_privilege(current_user, current_database(), 'TEMPORARY') THEN
    RAISE EXCEPTION 'role % can create temporary tables', current_user;
  END IF;
  IF pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE') THEN
    RAISE EXCEPTION 'role % can create objects in public', current_user;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_class c
             WHERE pg_catalog.pg_get_userbyid(c.relowner) = current_user)
     OR EXISTS (SELECT 1 FROM pg_catalog.pg_proc p
                WHERE pg_catalog.pg_get_userbyid(p.proowner) = current_user) THEN
    RAISE EXCEPTION 'role % owns database objects', current_user;
  END IF;

  RAISE NOTICE 'role % OK: no superuser/BYPASSRLS, NOINHERIT, no memberships, owns nothing, cannot CREATE or use TEMP', current_user;
END
$$;

SELECT current_user AS connected_as,
       current_database() AS database,
       current_setting('TimeZone') AS timezone,
       current_setting('statement_timeout') AS statement_timeout,
       current_setting('idle_in_transaction_session_timeout') AS idle_in_tx_timeout;
