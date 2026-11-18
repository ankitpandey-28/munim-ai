# Munim AI — Physical Schema (PostgreSQL 18)

| Field | Value |
|---|---|
| Version | 1.0 (Phase 2.2) |
| Date | 2026-11-19 |
| Source of truth | SQLAlchemy models in `backend/app/modules/*/models.py` + Alembic migrations in `backend/alembic/versions/` |
| Logical design | [database-design.md](database-design.md) |

`alembic check` is part of the test suite: the migrations and the models must describe exactly the same schema.

## 1. Migrations

| Revision | File | Effect |
|---|---|---|
| `0001` | `20261118_1856_0001_initial_schema.py` | `CREATE EXTENSION pg_trgm`; 40 tables, 74 indexes, all constraints; 5 circular foreign keys added after table creation |
| `0002` | `20261119_0002_0002_security_rls_grants.py` | Tenant-context functions, `ENABLE` + `FORCE ROW LEVEL SECURITY` on 35 tables, 40 policies, least-privilege grants for `munim_app`, immutability triggers |
| `0003` | `20261119_0003_0003_seed_units.py` | Seeds 8 units of measure (global reference data) |

All three run in one transaction. None drops or rewrites data. `downgrade()` exists for development and test databases only.

Applied to the local `munim_ai` database on 2026-11-19 after a `pg_dump` backup (`backups/munim_ai_pre_phase2_*.dump`, git-ignored). The rendered SQL was reviewed beforehand (`backups/phase2_migration_0001_0003.sql`).

## 2. Conventions

| Topic | Rule |
|---|---|
| Primary keys | `uuid`, UUIDv7. Generated in Python (`app/shared/ids.py`) so ids are known before INSERT. `DEFAULT uuidv7()` (PostgreSQL 18) is the fallback |
| Money | `bigint`, integer **paise**, column names end in `_paise` (test-enforced) |
| Quantities | `numeric(14,3)` in the product's base unit (test-enforced) |
| Time | `timestamptz` for instants; `date` for business dates (shop timezone) |
| Enum-like values | `text`/`varchar` + named `CHECK (col IN (...))`. No PostgreSQL ENUM types, so values can evolve in a single migration |
| Tenant column | `shop_id uuid NOT NULL REFERENCES shops(id)` on every tenant table, indexed |
| Same-shop links | Every tenant table has `UNIQUE (shop_id, id)`; children reference `(shop_id, parent_id) → parent(shop_id, id)`. Cross-shop links are impossible even for buggy code |
| Constraint names | Deterministic naming convention (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`); names over 63 characters are shortened explicitly |
| Text search | `pg_trgm` GIN indexes on product/customer alias and name columns (voice resolution, Phase 3+) |

## 3. Tables (40)

| Group | Table | Tenant | Notes |
|---|---|:-:|---|
| Identity | `users` | global | E.164 phone (`CHECK ^\+91[6-9]\d{9}$`, unique), Argon2id hash, lockout fields |
| | `auth_sessions` | global | Server-side sessions; `token_hash` = SHA-256 (32 bytes, unique); `active_shop_id`; absolute expiry |
| | `login_attempts` | global | `phone_hash`/`ip_hash` = HMAC-SHA256; outcome + reason |
| Shops | `shops` | special RLS | `version` for optimistic concurrency |
| | `shop_members` | special RLS | role `owner/admin/staff`; `UNIQUE (shop_id, user_id)`; `removed_at` ⇔ status |
| | `shop_settings` | ✓ | one row per shop, JSONB |
| Catalog | `units` | global | seeded, read-only for the app |
| | `product_categories`, `products`, `product_aliases`, `product_prices` | ✓ | unique active names per shop (`lower(name)`); trigram on aliases |
| Inventory | `inventory_levels` | ✓ | PK `(shop_id, product_id)`; cached projection + `avg_cost_paise` |
| | `stock_movements` | ✓ | append-only; `quantity_delta <> 0` |
| | `stock_counts`, `stock_count_items` | ✓ | `difference = counted − system` (CHECK) |
| Customers | `customers`, `customer_aliases` | ✓ | unique phone per shop; cached `balance_paise` |
| Ledger | `business_transactions` | ✓ | header of every money/stock operation; reversal rules (§5) |
| Sales | `sales`, `sale_items` | ✓ | `total = subtotal − discount = paid_now + credit` (CHECK); credit ⇒ customer |
| Credit | `credit_entries`, `payments`, `payment_allocations` | ✓ | append-only; allocation balance CHECKs |
| Approvals | `approval_requests` | ✓ | decider ≠ requester; one open request per pending action |
| Expenses | `expense_categories`, `expenses` | ✓ | category kind business / personal_withdrawal |
| Suppliers | `suppliers`, `supplier_products` | ✓ | |
| Purchasing | `purchase_orders`, `purchase_order_items`, `goods_receipts`, `goods_receipt_items` | ✓ | per-shop `po_number` |
| Voice | `voice_sessions`, `voice_commands`, `pending_actions` | ✓ | **no audio column of any kind**; one awaiting action per session |
| Notifications | `reminders`, `notifications` | ✓ | wa.me URL never stored |
| Audit | `audit_logs` | special RLS | append-only; `shop_id` NULL for identity events |
| Platform | `idempotency_keys` | special RLS | partial unique `(shop_id,user_id,key)` / `(user_id,key) WHERE shop_id IS NULL` |
| | `jobs` | global | PostgreSQL job queue |

Circular foreign keys (created after all tables): `business_transactions → approval_requests / pending_actions`, `approval_requests → pending_actions`, `voice_sessions → pending_actions`, `users.last_active_shop_id → shops`.

## 4. Row-level security

**Context.** The API sets two transaction-local settings at the start of **every** transaction (SQLAlchemy `after_begin` hook, `set_config(..., true)`):

```sql
app.current_user_id   -- authenticated user
app.current_shop_id   -- verified active shop (membership re-checked per request)
```

Read through two functions, so an empty or missing value becomes NULL and every comparison is false (**fail closed**):

```sql
CREATE FUNCTION app_current_shop_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.current_shop_id', true), '')::uuid $$;
```

**Policies (40).**

| Tables | Policy |
|---|---|
| 31 standard tenant tables | `tenant_isolation FOR ALL USING (shop_id = app_current_shop_id()) WITH CHECK (same)` |
| `shops` | SELECT: active shop **or** the user has an active membership; INSERT: `id = app_current_shop_id() AND created_by_user_id = app_current_user_id()`; UPDATE: active shop only |
| `shop_members` | SELECT: active shop's members **or** the user's own memberships; INSERT/UPDATE: active shop only |
| `audit_logs` | SELECT: active shop only; INSERT: active shop or `shop_id IS NULL` (shop-less rows are write-only) |
| `idempotency_keys` | ALL: `user_id = app_current_user_id() AND (shop_id IS NULL OR shop_id = app_current_shop_id())` |

`FORCE ROW LEVEL SECURITY` makes the policies apply to the owner role `munim_owner` too. Global tables (`users`, `auth_sessions`, `login_attempts`, `units`, `jobs`) have no RLS, and the tests assert that, so they are never accidentally tenant-scoped.

**Shop creation under RLS.** The new shop's id is generated in Python and set as the transaction's shop context *before* the INSERTs, so the `shops` and first `shop_members` rows satisfy WITH CHECK.

## 5. Append-only financial records

| Mechanism | Detail |
|---|---|
| Grants | `munim_app` has no DELETE on any financial or audit table, and UPDATE only on listed status/link/cache columns (§6) |
| Trigger `munim_forbid_delete` | Rejects DELETE on `business_transactions, stock_movements, credit_entries, payments, payment_allocations, sales, sale_items, expenses, goods_receipts, goods_receipt_items, product_prices, audit_logs`. Binds the owner role too |
| Trigger `munim_guard_immutable(mutable cols…)` | Compares `to_jsonb(OLD)` and `to_jsonb(NEW)` minus the allowed columns; any other change raises |
| Trigger `munim_guard_transaction_status` | A business transaction changes at most once: `posted → reversed` with `reversed_by_transaction_id` set |
| Constraints | `reversal ⇔ reverses_transaction_id`; partial unique index on `reverses_transaction_id` (one reversal per transaction); reversals can't be reversed; override fields all-or-nothing; reason required for reversal, write-off and adjustment |

## 6. Grants for `munim_app`

The baseline is `REVOKE ALL ON ALL TABLES`, then explicit grants. The full list is in migration 0002 (`GRANTS`). Summary:

| Category | Privileges |
|---|---|
| Append-only financial (`business_transactions`, `sales`, `credit_entries`, `payments`, `expenses`, …) | SELECT, INSERT, UPDATE on status/link/cache columns only |
| Pure append-only (`stock_movements`, `sale_items`, `payment_allocations`, `goods_receipts`, `goods_receipt_items`, `product_prices`, `audit_logs`) | SELECT, INSERT |
| Master data (`products`, `customers`, `suppliers`, …) | SELECT, INSERT, UPDATE on explicit columns (never `id`, `shop_id`, `created_at`) |
| Approvals, pending actions | UPDATE on state columns only (request content immutable) |
| DELETE | only `auth_sessions`, `login_attempts`, `product_aliases`, `customer_aliases`, `supplier_products` |
| `units` | SELECT |
| Schema / database | USAGE on `public`; no CREATE; no TEMPORARY; owns nothing |

## 7. Verifying on any database

```powershell
cd backend
.venv\Scripts\alembic current      # expect: 0003 (head)
.venv\Scripts\alembic check        # expect: No new upgrade operations detected.
```

The integration suite (`pytest tests/integration`) checks all of the above on a disposable PostgreSQL 18 cluster.
