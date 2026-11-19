-- =============================================================================
-- Munim AI: local PostgreSQL setup (native install, no Docker)
-- =============================================================================
-- Creates, for this project only:
--   role     munim_owner : owns the munim_ai database and its public schema;
--                          used ONLY by Alembic migrations (MIGRATION_DATABASE_URL)
--   role     munim_app   : runtime role for the API/worker (DATABASE_URL);
--                          NOSUPERUSER, NOBYPASSRLS, NOINHERIT, owns nothing,
--                          cannot create objects; table grants come from migrations
--   database munim_ai    : owned by munim_owner; nobody else may connect
--
-- Follows docs/database-design.md §8.1 (roles) and §8.2 (RLS prerequisites).
--
-- Requirements: PostgreSQL 17+, run as a superuser (e.g. postgres) from the repository
-- root. Verified on PostgreSQL 18.4 (Windows) in a throwaway test instance: fresh run,
-- re-runs, partial-failure recovery and every refusal path.
--
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -U postgres -d postgres -f infra/postgres/local-setup.sql
--
-- Terminal requirement (interactive mode):
--   Run it in a real interactive console: Windows PowerShell, Windows Terminal or the
--   VS Code integrated terminal. On Windows, \password reads the password directly from
--   the console window, not from the script or standard input. Do NOT run it through an
--   assistant/chat "!" command, PowerShell ISE, or with piped/redirected input: there is
--   no console there, so psql waits forever at the password prompt. If it seems stuck,
--   press Ctrl+C and re-run in a proper terminal; nothing is left half-configured (see
--   "Safety" below).
--
-- Password handling:
--   * Interactive mode (default, for real databases): psql prompts for each role's new
--     password with \password (input hidden, asked twice). psql hashes the password
--     locally (SCRAM-SHA-256) and sends only the hash to the server, so the plaintext
--     password never appears in this file, on the command line, in shell history, or in
--     server logs.
--   * CI mode (throwaway CI databases ONLY): pass -v owner_password=... -v app_password=...
--     The script then runs ALTER ROLE ... PASSWORD '<plaintext>': the plaintext travels to
--     the server inside the SQL statement and can appear in server logs (e.g. if
--     log_statement is enabled or the statement errors), and the values may remain in the
--     shell history or CI logs of whoever launched psql. Never use CI mode on a developer
--     or production database.
--       psql ... -v owner_password="$OWNER_PW" -v app_password="$APP_PW" -f infra/postgres/local-setup.sql
--
-- Windows note: psql may print "WARNING: Console code page (437) differs from Windows
-- code page (1252)". It is harmless for this script (all identifiers are ASCII).
--
-- Safety:
--   * All safety checks run in the read-only PREFLIGHT block below, before any CREATE,
--     ALTER, GRANT or REVOKE. Every problem found is reported together; if there is any,
--     the script stops and nothing has been created or altered.
--   * Never drops, renames or alters any database or role other than munim_ai,
--     munim_owner and munim_app.
--   * Roles are created only if missing, with their complete attribute set in a single
--     CREATE ROLE statement. Existing munim_owner / munim_app roles are VERIFIED, never
--     repaired: their attributes are not altered. Only their passwords are (re)set, which
--     is how passwords are rotated.
--   * Refuses to continue if any of these is true:
--       - munim_ai exists but is not owned by munim_owner
--       - an existing munim_owner/munim_app has unexpected attributes: SUPERUSER,
--         CREATEDB, CREATEROLE, REPLICATION, BYPASSRLS, NOLOGIN, or (munim_app only) INHERIT
--       - munim_owner or munim_app is a member of any role, or any role is a member of
--         munim_owner or munim_app (both directions of pg_auth_members)
--       - an existing munim_app owns any object in any database, or an existing
--         munim_owner owns objects in a database other than munim_ai
--   * Re-runnable after a partial failure: completed steps are skipped or re-applied
--     idempotently to munim_ai only.
-- =============================================================================

\set ON_ERROR_STOP on
\set VERBOSITY default

\echo
\echo '== Munim AI local setup: preflight checks (read-only)'

-- PREFLIGHT: every safety check runs here, before any CREATE/ALTER/GRANT/REVOKE.
-- This block only reads catalogs. All problems are collected and reported together;
-- if there is at least one, the script stops and nothing has been changed.
DO $$
DECLARE
  me        record;
  r         record;
  problems  text[] := '{}';
BEGIN
  -- 1. Server version (builtin C.UTF-8 locale needs PostgreSQL 17+)
  IF current_setting('server_version_num')::int < 170000 THEN
    problems := problems || format('PostgreSQL 17 or newer is required (found %s)',
                                   current_setting('server_version'));
  END IF;

  -- 2. Caller must be a superuser (creates roles/database, sets per-database role settings)
  SELECT rolsuper INTO me FROM pg_catalog.pg_roles WHERE rolname = current_user;
  IF NOT me.rolsuper THEN
    problems := problems || format('run this script as a superuser (e.g. postgres), not as %s',
                                   current_user);
  END IF;

  -- 3. Never take over a foreign database that happens to be named munim_ai
  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_database
    WHERE datname = 'munim_ai'
      AND pg_catalog.pg_get_userbyid(datdba) <> 'munim_owner'
  ) THEN
    problems := problems || 'database munim_ai already exists and is not owned by munim_owner'::text;
  END IF;

  -- 4. Existing roles: attributes must match the approved design exactly in every
  --    security-relevant respect (database-design.md §8.1). Never auto-repaired.
  FOR r IN
    SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls,
           rolcanlogin, rolinherit
    FROM pg_catalog.pg_roles
    WHERE rolname IN ('munim_owner', 'munim_app')
    ORDER BY rolname
  LOOP
    IF r.rolsuper       THEN problems := problems || format('existing role %s has SUPERUSER', r.rolname); END IF;
    IF r.rolcreatedb    THEN problems := problems || format('existing role %s has CREATEDB', r.rolname); END IF;
    IF r.rolcreaterole  THEN problems := problems || format('existing role %s has CREATEROLE', r.rolname); END IF;
    IF r.rolreplication THEN problems := problems || format('existing role %s has REPLICATION', r.rolname); END IF;
    IF r.rolbypassrls   THEN problems := problems || format('existing role %s has BYPASSRLS', r.rolname); END IF;
    IF NOT r.rolcanlogin THEN problems := problems || format('existing role %s is NOLOGIN (expected LOGIN)', r.rolname); END IF;
    IF r.rolname = 'munim_app' AND r.rolinherit THEN
      problems := problems || 'existing role munim_app has INHERIT (expected NOINHERIT)'::text;
    END IF;
  END LOOP;

  -- 5. Role membership, both directions (pg_auth_members.member = the member,
  --    .roleid = the role it belongs to). Neither project role may belong to any role,
  --    and no role may belong to either project role.
  FOR r IN
    SELECT mem.rolname AS member_name, grp.rolname AS group_name
    FROM pg_catalog.pg_auth_members m
    JOIN pg_catalog.pg_roles mem ON mem.oid = m.member
    JOIN pg_catalog.pg_roles grp ON grp.oid = m.roleid
    WHERE mem.rolname IN ('munim_owner', 'munim_app')
       OR grp.rolname IN ('munim_owner', 'munim_app')
    ORDER BY 1, 2
  LOOP
    problems := problems || format('role membership not allowed: %s is a member of %s',
                                   r.member_name, r.group_name);
  END LOOP;

  -- 6. Object ownership across ALL databases (pg_shdepend is cluster-wide):
  --    an existing munim_app must own nothing anywhere; an existing munim_owner must own
  --    nothing outside munim_ai. Catches pre-existing roles that belong to something else.
  FOR r IN
    SELECT a.rolname, coalesce(d.datname, '(shared object)') AS datname, count(*) AS n
    FROM pg_catalog.pg_shdepend s
    JOIN pg_catalog.pg_roles a ON a.oid = s.refobjid
    LEFT JOIN pg_catalog.pg_database d ON d.oid = s.dbid
    WHERE s.refclassid = 'pg_catalog.pg_authid'::regclass
      AND s.deptype = 'o'
      AND (a.rolname = 'munim_app'
           OR (a.rolname = 'munim_owner'
               AND coalesce(d.datname, '') <> 'munim_ai'
               -- ownership of the munim_ai database itself is recorded as a shared
               -- object (dbid = 0) and is expected. IS NOT DISTINCT FROM keeps this
               -- exclusion NULL-safe when munim_ai does not exist yet (a plain "=" would
               -- yield NULL and silently hide munim_owner owning some other database).
               AND NOT (s.classid = 'pg_catalog.pg_database'::regclass
                        AND s.objid IS NOT DISTINCT FROM
                            (SELECT oid FROM pg_catalog.pg_database
                             WHERE datname = 'munim_ai'))))
    GROUP BY 1, 2
    ORDER BY 1, 2
  LOOP
    problems := problems || format('existing role %s owns %s object(s) in %s',
                                   r.rolname, r.n, r.datname);
  END LOOP;

  IF cardinality(problems) > 0 THEN
    RAISE EXCEPTION E'Preflight failed; NO changes were made. Problems:\n  - %',
      array_to_string(problems, E'\n  - ');
  END IF;

  RAISE NOTICE 'Preflight passed (existing munim roles: %)',
    coalesce((SELECT string_agg(rolname, ', ' ORDER BY rolname) FROM pg_catalog.pg_roles
              WHERE rolname IN ('munim_owner', 'munim_app')), 'none');
END
$$;

-- -----------------------------------------------------------------------------
-- 1. Roles: created only if missing, complete attributes in ONE statement each.
--    Existing roles were verified in PREFLIGHT and are deliberately left unchanged.
--    This script never grants any role membership.
-- -----------------------------------------------------------------------------
\echo '== 1/5 roles'

-- Migration/owner role: may log in, owns schema objects, has no cluster-wide powers.
SELECT 'CREATE ROLE munim_owner WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
       'NOREPLICATION NOBYPASSRLS INHERIT CONNECTION LIMIT 10'
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'munim_owner')
\gexec

-- Runtime role: may log in and nothing else. NOINHERIT: never gains privileges through
-- role membership.
SELECT 'CREATE ROLE munim_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
       'NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 50'
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'munim_app')
\gexec

-- -----------------------------------------------------------------------------
-- 2. Passwords (SCRAM-SHA-256; interactive by default)
-- -----------------------------------------------------------------------------
\echo '== 2/5 passwords'

SET password_encryption = 'scram-sha-256';

\if :{?owner_password}
  ALTER ROLE munim_owner WITH PASSWORD :'owner_password';
\else
  \echo 'Enter a NEW password for munim_owner (input is hidden):'
  \password munim_owner
\endif

\if :{?app_password}
  ALTER ROLE munim_app WITH PASSWORD :'app_password';
\else
  \echo 'Enter a NEW password for munim_app (input is hidden):'
  \password munim_app
\endif

-- -----------------------------------------------------------------------------
-- 3. Database
-- -----------------------------------------------------------------------------
\echo '== 3/5 database munim_ai'

-- builtin C.UTF-8 locale: identical sorting and character handling on Windows (local)
-- and Linux (CI/production), independent of the OS locale. Requires PostgreSQL 17+.
SELECT 'CREATE DATABASE munim_ai WITH OWNER = munim_owner TEMPLATE = template0 '
       'ENCODING = ''UTF8'' LOCALE_PROVIDER = builtin BUILTIN_LOCALE = ''C.UTF-8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_database WHERE datname = 'munim_ai')
\gexec

-- Nobody connects unless explicitly granted.
REVOKE ALL ON DATABASE munim_ai FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE munim_ai TO munim_owner;
GRANT CONNECT ON DATABASE munim_ai TO munim_app;

-- Database-wide default time zone.
ALTER DATABASE munim_ai SET timezone = 'UTC';

-- Per-role settings scoped to this database only (other databases are unaffected).
ALTER ROLE munim_app IN DATABASE munim_ai SET timezone = 'UTC';
ALTER ROLE munim_app IN DATABASE munim_ai SET statement_timeout = '15s';
ALTER ROLE munim_app IN DATABASE munim_ai SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE munim_owner IN DATABASE munim_ai SET timezone = 'UTC';

-- -----------------------------------------------------------------------------
-- 4. Schema privileges (inside munim_ai)
-- -----------------------------------------------------------------------------
\echo '== 4/5 schema privileges'

\connect munim_ai

ALTER SCHEMA public OWNER TO munim_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO munim_app;

-- Deliberately NO default privileges and NO table grants here: each migration grants
-- munim_app exactly what it needs per table/column (database-design.md §8.3).

-- -----------------------------------------------------------------------------
-- 5. Summary (no secrets)
-- -----------------------------------------------------------------------------
\echo '== 5/5 summary'

SELECT rolname,
       rolcanlogin  AS can_login,
       rolsuper     AS superuser,
       rolbypassrls AS bypass_rls,
       rolinherit   AS inherit,
       rolcreatedb  AS create_db,
       rolcreaterole AS create_role,
       rolconnlimit AS conn_limit,
       (rolpassword IS NOT NULL) AS has_password
FROM pg_catalog.pg_authid
WHERE rolname IN ('munim_owner', 'munim_app')
ORDER BY rolname;

SELECT d.datname AS database,
       pg_catalog.pg_get_userbyid(d.datdba) AS owner,
       pg_catalog.pg_encoding_to_char(d.encoding) AS encoding,
       d.datlocprovider AS locale_provider,
       d.datlocale AS builtin_locale
FROM pg_catalog.pg_database d
WHERE d.datname = 'munim_ai';

SELECT n.nspname AS schema,
       pg_catalog.pg_get_userbyid(n.nspowner) AS owner,
       pg_catalog.has_schema_privilege('munim_app', 'public', 'USAGE')  AS app_usage,
       pg_catalog.has_schema_privilege('munim_app', 'public', 'CREATE') AS app_create
FROM pg_catalog.pg_namespace n
WHERE n.nspname = 'public';

\echo
\echo 'Munim AI local setup complete. Next: verify munim_app with infra/postgres/verify-roles.sql'
