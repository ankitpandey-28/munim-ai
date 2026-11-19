# Munim AI — Decision Log

Architectural, business-rule and security decisions, with trade-offs and deferrals. Earlier decisions: SRS §13 (open questions), architecture.md (ADRs), phase-2-implementation.md §3 (X1–X7).

| # | Date | Area | Decision | Rationale / trade-off | Source |
|---|---|---|---|---|---|
| D-01 | 2026-11-19 | Catalogue permissions | Owner and admin: full catalogue access incl. cost prices and price changes. Staff: view only, never cost prices. No per-member overrides | Simplest safe rule; replaces SRS "configurable" | Approved by stakeholder (SRS §3.2 note) |
| D-02 | 2026-11-19 | Price history | Initial prices recorded at product creation; later rows only when a value changes; prices change only via `/prices` | Complete history from day one; append-only | database-design.md |
| D-03 | 2026-11-19 | Barcodes | Archived products keep their barcode reserved | Avoids silently reusing a code that historic records reference | Approved rule |
| D-04 | 2026-11-19 | Categories | No optimistic-concurrency version; last write wins | Low-risk metadata; schema has no version column | database-design.md |
| D-05 | 2026-11-19 | Costing (Q-19) | Weighted-average cost from goods receipts; default cost price used until the first receipt | Confirmed in the master development brief ("approved weighted-average costing approach") | Master brief 2026-11-19 |
| D-06 | 2026-11-19 | Git workflow | Phase-specific feature branches pushed to `origin`; PRs opened so CI runs; no automatic merge to `main`, no force-push | Master brief §17 | Master brief 2026-11-19 |
