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
| 3A | Catalogue frontend | ⏳ In progress |
| 4 | Inventory (opening stock, receipts, adjustments, counts, history, low stock, valuation, weighted-average cost) | ⏳ |
| 5 | Customers and udhaar ledger (payments, allocation, advances, credit limits, statements) | ⏳ (credit-limit semantics = decision Q-21) |
| 6 | Sales, billing, payments, reversals, approvals | ⏳ |
| 7 | Voice (Saaras STT, GPT tool calling, Bulbul TTS, pending actions) | ⏳ (needs provider API keys) |
| 8 | Dashboard, reports, expenses, reminders (wa.me links) | ⏳ |
| 9 | Security and production readiness (no live deployment without approval) | ⏳ |

## Open blockers / decision gates

| ID | Topic | Blocks | Status |
|---|---|---|---|
| Q-21 | Staff credit-limit semantics | Phase 5 approvals | Open |
| Q-22 | Products without stock tracking | Phase 4 | Open |
| Q-17 | Reversal date treatment in reports | Phase 8 | Open |
| Q-23 | Admin role scope for business modules | Phases 4–8 | Open (confirmed only for catalogue) |
| Q-18 | Password recovery procedure | Phase 9 / pilot | Open |
| Q-13 | Hosting provider | Deployment | Open |
| — | Sarvam + OpenAI API keys | Phase 7 live tests | Not available |

## Next task

Build the catalogue frontend (Phase 3A) against the existing `/api/v1/catalog` endpoints.
