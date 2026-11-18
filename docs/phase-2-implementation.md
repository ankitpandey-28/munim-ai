# Munim AI — Phase 2 Implementation Record

| Field | Value |
|---|---|
| Date | 2026-11-19 |
| Scope | Phase 2.1–2.8: foundation, database, authentication, shops, shared transaction infrastructure, frontend, integration and hardening, verification |
| Related | [physical-schema.md](physical-schema.md), [security-checklist.md](security-checklist.md), [api.md](api.md) |

Status legend: **COMPLETE AND VERIFIED** · **IMPLEMENTED BUT NOT VERIFIED** · **BLOCKED** · **DEFERRED TO PHASE 3**

## 1. Milestone checklist

| Milestone | Status | Evidence |
|---|---|---|
| 2.1 Repository foundation (Next.js, FastAPI, logging, errors, health, local PostgreSQL roles) | COMPLETE AND VERIFIED | earlier reports; health and identity checks |
| 2.2 Physical schema, migrations, RLS, grants, immutability | COMPLETE AND VERIFIED | 20 DB integration tests; `alembic check`; applied to real `munim_ai` after backup |
| 2.3 Authentication and user management | COMPLETE AND VERIFIED | 37 auth integration tests + unit tests |
| 2.4 Shop management and multi-shop | COMPLETE AND VERIFIED | 16 shop/tenant integration tests |
| 2.5 Idempotency, business transactions, audit | COMPLETE AND VERIFIED | 10 integration tests incl. concurrency |
| 2.6 Frontend foundation | COMPLETE AND VERIFIED | ESLint, `tsc`, 23 Vitest tests, production build, E2E page checks |
| 2.7 Integration and hardening | COMPLETE AND VERIFIED | 20/20 end-to-end checks through the Next.js proxy |
| 2.8 Testing and verification | COMPLETE AND VERIFIED (locally) | See §5; CI workflow updated but **not yet executed** |

## 2. Requirement checklist

### 2.2 Database
| Requirement | Status |
|---|---|
| SQLAlchemy 2.0 models for all 40 listed tables | COMPLETE AND VERIFIED |
| UUIDv7 PKs, BIGINT paise, NUMERIC(14,3), timestamptz | COMPLETE AND VERIFIED (column-type test) |
| FKs + composite tenant FKs, unique/check constraints, indexes | COMPLETE AND VERIFIED |
| Alembic migrations (3), reviewed before applying | COMPLETE AND VERIFIED |
| RLS ENABLE + FORCE, USING + WITH CHECK, fail-closed, transaction-local context | COMPLETE AND VERIFIED |
| Membership access policy using user context | COMPLETE AND VERIFIED |
| Append-only financial records, linked reversals, protected amounts | COMPLETE AND VERIFIED |
| Least-privilege grants, no DELETE on financial/audit, no CREATE | COMPLETE AND VERIFIED |
| Migration verification and shop-isolation tests | COMPLETE AND VERIFIED |

### 2.3 Authentication
| Requirement | Status |
|---|---|
| Registration, phone validation/normalisation, Argon2id | COMPLETE AND VERIFIED |
| Login, logout, logout-all, session list/revoke | COMPLETE AND VERIFIED |
| Session creation, revocation, absolute + idle expiration | COMPLETE AND VERIFIED |
| Password change (revokes sessions, rotates token) | COMPLETE AND VERIFIED |
| Login-attempt tracking, lockout, IP throttling | COMPLETE AND VERIFIED |
| Auth dependencies, current-user endpoint, secure errors | COMPLETE AND VERIFIED |
| Password recovery | DEFERRED (support-assisted process needs decision Q-18) |

### 2.4 Shops
| Requirement | Status |
|---|---|
| Create / get / update shop (optimistic concurrency) | COMPLETE AND VERIFIED |
| Add members (existing user or new account with temporary password) | COMPLETE AND VERIFIED |
| Owner/admin/staff roles, list (paginated), update role, deactivate | COMPLETE AND VERIFIED |
| Last-owner protection with safe ownership transfer | COMPLETE AND VERIFIED |
| Shop switching; verified shop context for every business request | COMPLETE AND VERIFIED |
| Unauthorized shop access / cross-tenant tests | COMPLETE AND VERIFIED |

### 2.5 Shared infrastructure
| Requirement | Status |
|---|---|
| Idempotency keys in the same transaction, replay, concurrency-safe | COMPLETE AND VERIFIED |
| Business transaction service (actor, shop, source, approval/override fields) | COMPLETE AND VERIFIED |
| Linked reversals with per-module handler registry | COMPLETE AND VERIFIED (framework; module handlers arrive in Phase 3) |
| Audit logging (actor, shop, action, entity, request id, masked before/after) | COMPLETE AND VERIFIED |
| Sales, stock, udhaar, expense workflows | DEFERRED TO PHASE 3 (as instructed) |

### 2.6 Frontend
| Requirement | Status |
|---|---|
| Responsive layout, login, registration, authenticated shell | COMPLETE AND VERIFIED (build + E2E page/redirect checks) |
| Protected routes (proxy + backend-verified session) | COMPLETE AND VERIFIED |
| Dashboard placeholder, shop selection/switching, profile/logout | COMPLETE (build/type/lint verified; manual browser check recommended) |
| Settings: shop details, members management | COMPLETE (build/type/lint verified; backend paths E2E-verified) |
| Form components, API client, central error handling, loading/empty states, validation | COMPLETE AND VERIFIED (unit tests) |
| Hindi, Hinglish, English UI | COMPLETE AND VERIFIED (dictionary completeness test); Punjabi UI deferred (Q-20) |
| Component/browser interaction tests | IMPLEMENTED BUT NOT VERIFIED (no component test harness; see §6) |

### 2.7 Integration and hardening
| Requirement | Status |
|---|---|
| CORS (deny by default; opt-in allow-list) + Origin check | COMPLETE AND VERIFIED |
| Central errors, request ids, structured redacted logs | COMPLETE AND VERIFIED |
| DB lifecycle, health, runtime identity, fail-closed startup | COMPLETE AND VERIFIED |
| Environment validation, safe defaults, production fail-closed | COMPLETE AND VERIFIED |
| Consistent responses, OpenAPI + docs/api.md, pagination, input validation, authorization | COMPLETE AND VERIFIED |

## 3. Decisions and deviations

| # | Topic | Decision | Why |
|---|---|---|---|
| X1 | Sessions | Opaque server-side session tokens (SHA-256 stored), not JWT access + refresh tokens (architecture §6 earlier draft) | The Phase 2 brief requires server-side sessions with hashed tokens and immediate revocation. Simpler, no JWT dependency, and revocation is instant. Architecture updated |
| X2 | Roles | `owner`, `admin`, `staff`. Admin edits shop details and manages staff only | Brief asked for admin; kept conservative. **Needs product confirmation (Q-23)** |
| X3 | Enum strategy | `text` + CHECK constraints | Easier evolution than PostgreSQL ENUM types |
| X4 | Audit `created_at` | Python-side default | Shop-less audit rows are write-only under RLS; PostgreSQL checks `RETURNING` against SELECT policies |
| X5 | Registration throttle | In-process sliding window | Single API instance in the pilot; login throttling is DB-backed |
| X6 | CI database job | Docker Compose job replaced by PostgreSQL 18 integration tests in the backend job | Same `local-setup.sql`, much broader coverage; Docker files kept as optional |
| X7 | Document numbers | `sale_number` / `po_number` columns exist; allocation mechanism designed in Phase 3 | Not needed until sales/purchasing workflows |

## 4. Files

**New backend modules:** `app/modules/{identity,shops,catalog,inventory,customers,ledger,sales,credit,approvals,expenses,suppliers,purchasing,voice,notifications,audit,platform}/models.py`; services and APIs for identity, shops, ledger, audit, platform (idempotency); `app/api/deps.py`, `app/api/idempotent.py`, `app/core/security.py`, `app/core/startup.py`, `app/shared/ids.py`, `app/models/registry.py`; migrations 0001–0003; `tests/support/pg_cluster.py`; integration tests.

**Frontend:** `src/lib/{api,session,types,validation,errors,redirects}.ts(x)`, `src/lib/i18n/*`, `src/components/{ui,language-select,dashboard-view,shops-view,profile-view}.tsx`, `src/components/{auth,shell,settings}/*`, `src/proxy.ts`, pages for login, register, dashboard, shops, profile, settings; `vitest.config.ts`, `src/lib/lib.test.ts`.

## 5. Verification results (2026-11-19)

| Check | Command | Result |
|---|---|---|
| Backend lint | `ruff check .` | All checks passed |
| Backend format | `ruff format --check .` | All files formatted |
| Backend tests (unit + PostgreSQL 18 integration) | `pytest` | 169 passed |
| Frontend lint | `npm run lint` | No problems |
| Frontend types | `npm run typecheck` | No errors |
| Frontend unit tests | `npm test` | 23 passed |
| Frontend build | `npm run build` | 16 routes + proxy built |
| End-to-end (disposable DB + API + Next.js) | scripted | 20/20 checks passed |
| Real `munim_ai` | backup → review → `alembic upgrade head` → checks | 0003 head, no drift, RLS 35/35, startup identity passed |

## 6. Known limitations

1. No component or browser-automation tests for React screens. Logic is unit-tested and flows are verified end-to-end through the API and proxy. A manual browser walkthrough of the new screens is recommended.
2. CI changes have not run yet (the project is not a Git repository).
3. Gaps G1–G6 in [security-checklist.md](security-checklist.md).
4. `AUTH_SECRET_KEY` is optional in development; set it in `backend/.env` for stable lockout history.

## 7. Decisions needed before or during Phase 3

| ID | Decision |
|---|---|
| Q-18 | Support-assisted password reset procedure |
| Q-21 | Staff credit limit semantics (per transaction / per day / per customer) |
| Q-22 | Products without stock tracking |
| Q-19 | Costing method (weighted average vs last cost) |
| Q-17 | Reversal date treatment in reports |
| Q-23 | Confirm the `admin` role's permissions (X2) |
| Q-24 | Per-shop document numbering format (`sale_number`, `po_number`) |
