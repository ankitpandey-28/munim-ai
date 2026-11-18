# Munim AI — Backend

FastAPI modular monolith (Python 3.12+, SQLAlchemy 2.0, Alembic, psycopg 3, Argon2id). See the root [README](../README.md), [docs/architecture.md](../docs/architecture.md), [docs/physical-schema.md](../docs/physical-schema.md) and [docs/api.md](../docs/api.md).

## Run

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
Copy-Item .env.example .env          # database passwords; see comments for all variables
.venv\Scripts\alembic upgrade head   # as munim_owner (identity verified before migrating)
.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API refuses to start if its database session isn't `munim_app` on `munim_ai` with safe attributes.

## Quality

```powershell
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\pytest                 # unit + PostgreSQL integration tests
```

Integration tests (`tests/integration/`) create a **disposable** PostgreSQL cluster with `initdb` in a temp directory on a free port, provision it with `infra/postgres/local-setup.sql`, run the real migrations, and delete it afterwards. They never touch your database. Binaries are found via `MUNIM_PG_BIN`, `PATH` or the default install path. With `MUNIM_REQUIRE_PG=1` (CI) missing binaries fail the run instead of skipping it.

## Structure

```
app/
├── main.py              app factory: middleware (request id, origin check, optional CORS), routers, startup checks
├── core/                config (validated), security (Argon2id, tokens, HMAC, phone), logging + redaction, errors, startup
├── database/            engine, Session + transaction-local tenant context (RLS), identity verification, health check
├── api/                 deps (auth, verified shop context, permissions), idempotent-endpoint helper, v1 router
├── models/              declarative Base, column/constraint helpers, registry of all models
├── shared/              UUIDv7 generator
└── modules/
    ├── identity/        users, sessions, login attempts — models, service, API
    ├── shops/           shops, members, settings, permissions — models, service, API
    ├── ledger/          business_transactions + transaction/reversal service
    ├── audit/           audit_logs + writer
    ├── platform/        idempotency keys (+ service), jobs
    └── catalog, inventory, customers, sales, credit, approvals, expenses,
        suppliers, purchasing, voice, notifications   (models only; services in Phase 3+)
alembic/versions/        0001 schema · 0002 RLS/grants/triggers · 0003 units seed
tests/                   unit tests; integration/ (PostgreSQL); support/pg_cluster.py
```
