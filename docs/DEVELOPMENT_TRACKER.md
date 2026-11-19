# Munim AI — Development Tracker

Resume procedure after any interruption: read this file and [DECISION_LOG.md](DECISION_LOG.md) → `git status` / `git log -3` → inspect code and tests → continue from the last **verified** milestone. Never assume an operation succeeded without checking.

## Current state

| Field | Value |
|---|---|
| Last updated | 2026-11-19 |
| Current phase | 3A — Catalogue frontend |
| Current milestone | 3A.1 catalogue UI (products, categories, prices, aliases) |
| Git branch | `feat/phase-3-catalog` (from `main`) |
| Latest verified commit | `be86e58` feat(catalog): complete product and category management |
| Latest push | see "Milestone log" |
| Database revision (code) | `0003` (head); catalogue needed no new migration |
| Real `munim_ai` revision | `0003` (last verified in Phase 2; not touched since) |

## Milestone log

| Date | Milestone | Commit | Verification |
|---|---|---|---|
| 2026-11-19 | Phase 2 foundation | `4a9e91b` | 169 backend tests, frontend lint/types/23 unit tests/build, 20/20 E2E (see phase-2-implementation.md) |
| 2026-11-19 | Phase 3 catalogue backend (units, categories, products, aliases, price history, search, archive, permissions, G7/G8 concurrency + audit tests) | `be86e58` | `ruff check` clean; `pytest` 365 passed, 0 skipped (1 third-party httpx deprecation warning) |

## Phase plan

| Phase | Scope | Status |
|---|---|---|
| 3 (backend) | Catalogue API | ✅ Verified, committed |
| 3A | Catalogue frontend | ✅ Verified, committed |
| 4 | Inventory (opening stock, receipts, adjustments, counts, history, low stock, valuation, weighted-average cost) | ⏳ |
| 5 | Customers and udhaar ledger (payments, allocation, advances, credit limits, statements) | ⏳ (credit-limit semantics = decision Q-21) |
| 6 | Sales, billing, payments, reversals, approvals | ⏳ |
| 7 | Voice (Saaras STT, GPT tool calling, Bulbul TTS, pending actions) | ⏳ (needs provider API keys) |
| 8 | Dashboard, reports, expenses, reminders (wa.me links) | ⏳ |
| 9 | Security and production readiness (no live deployment without approval) | ⏳ |

## Open blockers / decision gates

| ID | Topic | Blocks | Status |
|---|---|---|---|
| Q-21 | Staff credit-limit semantics | Phase 5 approvals | Decided: per transaction (D-07) |
| Q-22 | Products without stock tracking | Phase 4 | Decided: `track_stock` flag (D-08) |
| Q-17 | Reversal date treatment in reports | Phase 8 | Decided: exclude on original date (D-09) |
| Q-23 | Admin role scope for business modules | Phases 4–8 | Decided: owner minus privileged (D-10) |
| Q-18 | Password recovery procedure | Phase 9 / pilot | Open |
| Q-13 | Hosting provider | Deployment | Open |
| — | Sarvam + OpenAI API keys | Phase 7 live tests | Not available |

## Phase 3A progress (on `feat/phase-3-catalog`)

| Item | Status |
|---|---|
| Catalogue UI: `/catalog` (list, search, category filter, archived toggle, add), `/catalog/[productId]` (details/edit, prices with confirmation, price history, aliases, archive), `/catalog/categories` | Implemented |
| `src/lib/catalog.ts` (paise/quantity parsing without floats, permissions, queries) + 85 i18n keys × 3 languages + catalogue error mapping | Implemented |
| Frontend typecheck, ESLint, Vitest (61 tests), production build | ✅ Pass |
| `backend/scripts/e2e_stack.py` (disposable DB + API) and `scripts/e2e_catalog.py` | ✅ 40/40 scripted checks through the Next.js proxy |
| Playwright (Edge, pinned 1.64.1): staff no-cost, cross-shop 404, logged-out redirect, 360px mobile layout | ✅ Pass |
| Playwright owner UI workflow test | ✅ Pass (selectors scoped to visible fields; Next keeps hidden `<Activity>` routes mounted) — 5/5 Playwright |
| Backend `pytest` after Phase 3A changes | ✅ 365 passed |

Known dev-only audit finding: vitest/tinypool advisories (fix = breaking vitest 5 upgrade) → Phase 9 dependency review.

## Next task

Phase 3A committed and pushed on `feat/phase-3-catalog` (PR #1). Next: check PR #1 CI, then Phase 4 inventory on `feat/phase-4-inventory` (starts with the `track_stock` migration, D-08).

## Frontend master prompt (2026-11-19) — resume here

Decision (stakeholder): for each module build the backend API **and** the screens, verified end to end; Punjabi UI added now (interface only, machine-drafted, needs native review). Order: catalogue completion → inventory → customers/udhaar → sales/POS → voice → dashboard/expenses/reports → suppliers → settings.

- PR #1 (`feat/phase-3-catalog`): CI green (backend, frontend, secret scan) after fixes `8613d77`, `667c4d9`, `8dc3336`, `ac8bd1e`.
- `feat/phase-4-inventory` (stacked on PR #1): catalogue completion — migration `0004` `products.track_stock` (D-08; backward compatible; **not applied to the real `munim_ai`** — back up first), UNIT_LOCKED / STOCK_NOT_ZERO guards (D-12), track-stock + other-names-on-create in the UI, Punjabi dictionary (`frontend/src/lib/i18n/pa.ts`), Noto Sans Devanagari/Gurmukhi fonts. Verified: pytest 367, Vitest 63, lint/types/build, Playwright 6/6.
- Next: inventory API (opening stock, receipts, adjustments, counts, reversals via ledger handlers with D-11/D-12, low stock, valuation hidden from staff) + inventory screens + guard tests for UNIT_LOCKED/STOCK_NOT_ZERO.

### Incident 2026-11-19 ~12:19 UTC — browser tests reached the real database

A dev server (`uvicorn --reload`, real `munim_ai`) was already on :8000; the disposable stack's API could not bind, the health check was answered by the dev server, and one Playwright run went there. Read-only check: **10 users "E2E Owner" (12:19:32–12:20:30 UTC), 10 empty shops, 10 memberships, 10 sessions** (+ registration audit rows/idempotency keys); 0 products/categories/transactions. Nothing deleted (awaiting decision). Fixed in `7dcc48d` (stack refuses a busy port). That run's results are void.

Pending on the stakeholder:
1. Superuser backup of `munim_ai` (owner dumps fail under FORCE RLS; README updated). Then apply migration `0004` (SQL reviewed: `backups/migration_0004.sql`). Until then the dev server's catalogue endpoints return 500 because it auto-reloaded code expecting `products.track_stock`.
2. Free port 8000, then re-run Playwright; commit the inventory screens (uncommitted: typecheck/lint/Vitest 71/build pass).
3. Decide whether to remove the 10 test accounts/shops.
