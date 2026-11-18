# Munim AI — Infrastructure

## Local development: native PostgreSQL (current)

| File | Purpose |
|---|---|
| `postgres/local-setup.sql` | One-time setup on a local PostgreSQL 17+ (18 recommended): creates the `munim_ai` database and the `munim_owner` / `munim_app` roles with conservative privileges. Run as `postgres`. |
| `postgres/verify-roles.sql` | Run as `munim_app` to prove the runtime role cannot bypass RLS, owns nothing and cannot create objects. |

See the root [README](../README.md#1-database-native-postgresql) for the exact commands.

- **Terminal:** run `local-setup.sql` in a real interactive console (PowerShell, Windows Terminal, VS Code terminal). `\password` reads from the console, so it hangs under a chat `!` command, PowerShell ISE or piped input. Use Ctrl+C and re-run if that happens.
- **Passwords are entered interactively.** The script never contains passwords. For each role, psql's `\password` asks you to type the new password twice at a hidden prompt, hashes it locally (SCRAM-SHA-256) and sends only the hash. The `-v owner_password/app_password` mode sends plaintext and is for throwaway CI databases only.
- **Windows code-page warning** (`Console code page (437) differs from Windows code page (1252)`): harmless here.
- **Verified** on PostgreSQL 18.4 (Windows) in a throwaway instance: fresh run, re-runs, partial-failure recovery and every refusal path. All safety checks run in a read-only preflight block before any change.
- **Existing roles are verified, not repaired.** If `munim_owner` or `munim_app` already exists, preflight checks its attributes, its role memberships (both directions) and the objects it owns across all databases. Any deviation stops the script with a list of problems and no changes. Roles are only ever created with their full attribute set in one `CREATE ROLE` statement.

### Role model (docs/database-design.md §8.1)

| Role | Attributes | Used by |
|---|---|---|
| `munim_owner` | LOGIN, no superuser / createdb / createrole / replication / bypassrls; owns `munim_ai` and schema `public` | Alembic only (`MIGRATION_DATABASE_URL`) |
| `munim_app` | LOGIN, no superuser / createdb / createrole / replication / bypassrls, **NOINHERIT**, no role memberships; CONNECT + schema USAGE only | API and worker (`DATABASE_URL`) |

Table and column privileges for `munim_app` are granted per table by migrations (Phase 2.2). There are deliberately no default privileges.

### Undo (only if you want to remove the project database completely)

Run as `postgres`. This deletes all Munim AI data and nothing else:

```sql
DROP DATABASE IF EXISTS munim_ai;
DROP ROLE IF EXISTS munim_app;
DROP ROLE IF EXISTS munim_owner;
```

## Optional / currently unused: Docker

`docker-compose.yml`, `.env.example` and `postgres/init/01-roles.sh` describe the same role model in a container. They are **not used** for local development or CI. CI now installs PostgreSQL 18 and the backend integration tests create disposable clusters provisioned with the same `local-setup.sql`.
