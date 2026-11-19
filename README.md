# Munim AI

> *Bolo, aur hisaab ho gaya.* — A voice-first business manager for Indian kirana shops.

Munim AI is a responsive **web application** that lets small shopkeepers manage sales, inventory, customer credit (udhaar), expenses and supplier orders by **speaking naturally** in Hindi, Hinglish and Punjabi, instead of keeping handwritten notebooks.

## Project status

**Phase 2 — Foundation: complete and verified locally (2026-11-19).** See [docs/phase-2-implementation.md](docs/phase-2-implementation.md) for the full checklist, evidence and limitations.

| Phase | Scope | Status |
|---|---|---|
| 1 | Requirements, architecture, data design, risks | ✅ Approved |
| 2.1 | Repository foundation, health, logging, local PostgreSQL roles | ✅ Verified |
| 2.2 | Physical schema (40 tables), migrations, RLS, grants, immutability | ✅ Verified; applied to local `munim_ai` |
| 2.3 | Phone + password auth (Argon2id), server-side sessions, lockout | ✅ Verified |
| 2.4 | Shops, members, roles (owner/admin/staff), shop switching | ✅ Verified |
| 2.5 | Idempotency, business-transaction framework, audit log | ✅ Verified |
| 2.6 | Frontend foundation (auth pages, shell, shops, profile, settings, i18n) | ✅ Verified (build, lint, types, unit tests, E2E) |
| 2.7–2.8 | Integration, hardening, full test suite | ✅ Verified locally; CI not yet run |
| 3a | Catalogue API: units, categories, products, search, aliases, price history ([docs/api.md](docs/api.md#catalogue-catalog)) | ✅ Verified (backend) |
| 3A | Catalogue screens: `/catalog`, `/catalog/[productId]`, `/catalog/categories` | ✅ Verified (unit, scripted E2E, Playwright) |
| 3 | Inventory, customers, udhaar/payments, sales, approvals | ⏳ Next |
| 4 | Expenses, suppliers, purchase orders, business summary, reminders | ⏳ |
| 5 | Voice assistant | ⏳ |
| 6 | Pilot hardening, deployment | ⏳ |

## Repository layout

```
munim-ai/
├── backend/        FastAPI modular monolith (Python 3.13, SQLAlchemy 2.0, Alembic, psycopg 3)
│   ├── app/core/       settings, security, logging, errors, middleware, startup checks
│   ├── app/database/   engine, sessions + tenant (RLS) context, identity checks
│   ├── app/modules/    identity, shops, ledger, audit, platform + models for all modules
│   ├── alembic/        migrations 0001–0003
│   └── tests/          unit + PostgreSQL 18 integration tests (disposable cluster)
├── frontend/       Next.js 16 (App Router), React 19, TypeScript, Tailwind 4
├── infra/          local PostgreSQL setup + role verification scripts (Docker optional)
├── docs/           requirements, architecture, schema, security, API, Phase 2 record
└── backups/        local database backups (git-ignored)
```

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.12+ (3.13 tested) | Backend |
| Node.js / npm | 22.x / 10.x | Frontend |
| PostgreSQL (native Windows install) | 17+ (18.4 used) | Database and integration tests |

Docker isn't required.

## Run locally (Windows, PowerShell)

### 1. Database (one time)

Set up `munim_ai`, `munim_owner` and `munim_app` with [infra/postgres/local-setup.sql](infra/postgres/local-setup.sql). Full instructions, including the interactive password prompts and the terminal requirements, are in [infra/README.md](infra/README.md). Then apply the migrations:

```powershell
cd backend
.venv\Scripts\alembic upgrade head      # runs as munim_owner; refuses any other identity
.venv\Scripts\alembic current           # expect: 0003 (head)
```

Back up before migrating a database that holds data:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h 127.0.0.1 -U munim_owner -d munim_ai -Fc -f ..\backups\munim_ai_<date>.dump
```

### 2. Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
Copy-Item .env.example .env             # fill in both database passwords; optionally AUTH_SECRET_KEY
.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

At startup the API verifies that it's connected as `munim_app` to `munim_ai` without superuser, BYPASSRLS or INHERIT, and **refuses to start otherwise**.
- Health: <http://127.0.0.1:8000/api/v1/health>
- API docs (non-production): <http://127.0.0.1:8000/docs>

### 3. Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local       # BACKEND_INTERNAL_URL (server-side only)
npm run dev                             # http://localhost:3000
```

The browser talks only to `http://localhost:3000`; `/api/v1/*` is forwarded to the backend (same-origin, httpOnly session cookie).

### 4. Try it

1. Open <http://localhost:3000>, choose **Create account**, and register with a 10-digit mobile number.
2. Create your shop; you land on the dashboard.
3. **Settings**: edit shop details and add a staff member with a temporary password.
4. Log in as the staff member in another browser: you're asked to change the password first, then you see the shop as *Staff*.

## Tests and checks

| Area | Command (from the folder shown) | What it covers |
|---|---|---|
| backend | `.venv\Scripts\ruff check .` and `.venv\Scripts\ruff format --check .` | lint and format |
| backend | `.venv\Scripts\pytest` | 365 tests. Integration tests start a **disposable** PostgreSQL 18 cluster with `initdb` (never your database). Set `MUNIM_PG_BIN` if PostgreSQL isn't in `C:\Program Files\PostgreSQL\18\bin` |
| frontend | `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` | ESLint, TypeScript, Vitest (61 tests), production build |
| backend + frontend | 1. `backend`: `.venv\Scripts\python -m scripts.e2e_stack` 2. `frontend`: `npm run build` then `npx next start -p 3000 -H 127.0.0.1` 3. `frontend`: `npm run e2e` (and optionally `backend`: `.venv\Scripts\python -m scripts.e2e_catalog`) | Browser tests (Playwright, installed Edge) against a **disposable** database + API; nothing touches `munim_ai`. Stop the stack with Ctrl+C |

Verify the database roles any time with [infra/postgres/verify-roles.sql](infra/postgres/verify-roles.sql) (as `munim_app`) and `alembic check`.

## Configuration

Real values live in git-ignored files (`backend/.env`, `frontend/.env.local`). Variable names are documented in [backend/.env.example](backend/.env.example) and [frontend/.env.example](frontend/.env.example). In production the backend refuses to start without `DATABASE_URL`, a strong `AUTH_SECRET_KEY`, Secure cookies and https-only `FRONTEND_ORIGINS`.

## Documentation

| Document | Contents |
|---|---|
| [docs/SRS.md](docs/SRS.md) | Requirements, roles, business rules, open questions |
| [docs/architecture.md](docs/architecture.md) | Architecture, sessions, tenant isolation, ADRs |
| [docs/database-design.md](docs/database-design.md) | Logical data model and invariants |
| [docs/physical-schema.md](docs/physical-schema.md) | Tables, migrations, RLS policies, grants, triggers |
| [docs/api.md](docs/api.md) | REST endpoints, permissions, error codes |
| [docs/security-checklist.md](docs/security-checklist.md) | Security controls with test evidence |
| [docs/phase-2-implementation.md](docs/phase-2-implementation.md) | Phase 2 checklist, decisions, limitations |
| [docs/risk-analysis.md](docs/risk-analysis.md) | Risk register |

## Core engineering principles

1. The LLM never writes to the database; money is integer paise computed by backend code.
2. Every money or stock change is an append-only business transaction, corrected only by linked reversals.
3. Related changes commit in one PostgreSQL transaction; write APIs are idempotent.
4. Shop isolation in the application **and** in PostgreSQL (RLS with FORCE; the runtime role can't bypass it).
5. No secrets in Git, no PII in logs, no raw audio stored, no premature microservices.

## Platform

Web only: responsive for mobile, tablet and desktop browsers.
