# Munim AI — Risk Analysis

| Field | Value |
|---|---|
| Version | 0.2 (Phase 1 — revised after stakeholder review) |
| Date | 2026-11-18 |
| Related | [SRS.md](SRS.md), [architecture.md](architecture.md), [database-design.md](database-design.md) |

Scoring: Likelihood (L) and Impact (I) 1–5; Score = L × I; ≥ 15 critical, 8–14 high, ≤ 7 medium/low. Scores are before mitigation.

### Changes since v0.1

| Risk | Change |
|---|---|
| R-13 | Rewritten for **password** authentication (unverified phone numbers, credential stuffing, recovery without OTP) |
| R-06 | Lowered likelihood: **raw audio is never retained** |
| R-14 | Reduced: no messaging API; owner sends WhatsApp links manually |
| R-17 – R-21 | **New:** approval bottleneck, override abuse, misleading profit figures, stock-block friction, allocation disputes |

## 1. Risk register

| ID | Risk | L | I | Score | Owner module |
|---|---|:-:|:-:|:-:|---|
| R-01 | Speech recognition errors | 5 | 4 | **20** | voice |
| R-02 | Duplicate transactions | 4 | 5 | **20** | core, all writes |
| R-03 | Incorrect customer identification | 4 | 5 | **20** | voice, customers |
| R-04 | Incorrect financial calculations | 2 | 5 | **10** | sales, credit, reports |
| R-05 | Network failures | 5 | 3 | **15** | frontend, core |
| R-06 | Data privacy breach / non-compliance | 2 | 5 | **10** | all |
| R-07 | Multi-shop data leakage | 2 | 5 | **10** | core, DB |
| R-08 | AI hallucinations / wrong intent | 4 | 4 | **16** | voice |
| R-09 | AI provider outage / latency / price | 3 | 4 | **12** | ai |
| R-10 | Low adoption / trust | 4 | 5 | **20** | product |
| R-11 | Unit/quantity misinterpretation | 4 | 3 | **12** | voice, catalog |
| R-12 | Concurrency on balances/stock | 3 | 4 | **12** | inventory, credit |
| R-13 | Account compromise (password auth) | 3 | 4 | **12** | identity |
| R-14 | Reminder misuse / customer annoyance | 2 | 3 | **6** | notifications |
| R-15 | Prompt injection | 2 | 3 | **6** | voice |
| R-16 | AI cost overrun | 3 | 3 | **9** | voice |
| R-17 | Approval bottleneck (owner unavailable) | 4 | 3 | **12** | approvals |
| R-18 | Override abuse / phantom stock | 3 | 3 | **9** | inventory, approvals |
| R-19 | Misleading profit figures | 4 | 3 | **12** | reports |
| R-20 | Stock-block friction during onboarding | 4 | 4 | **16** | inventory, product |
| R-21 | Payment allocation disputes | 3 | 3 | **9** | credit |

## 2. Detailed analysis

### R-01 Speech recognition errors
**Causes:** noise, code-mixing, accents, Hindi/Punjabi number homophones ("saat/saath", "pachaas/pachpan"), brand names, poor mics.
**Mitigations:** transcript always shown; all voice writes confirmed, with amounts in words and digits; push-to-talk; language hints and shop vocabulary; alias-based fuzzy/phonetic resolution; number sanity checks; voice/tap correction; typed fallback; quality metrics (confidence, correction and cancel rates) and a consented regression test set from the pilot. Because audio is not retained, the test set must be **recorded deliberately with consent**, not collected from production.
**Residual:** medium; errors are caught at confirmation.

### R-02 Duplicate transactions
**Mitigations:** Idempotency-Key on every write, with the key record committed in the same DB transaction as the business rows; conditional single execution of pending actions and approvals; client reuses the key on retry and disables buttons in flight; near-duplicate warning within 60 s; one-tap reversal; unique constraints (one reversal per transaction, one credit entry per sale credit portion).
**Residual:** low.

### R-03 Incorrect customer identification
**Mitigations:** udhaar always confirmed, showing name + nickname/landmark + masked phone + **current → new balance**; no auto-select among close candidates; nicknames encouraged and prompted for duplicate names; explicit new-customer step; reversal + re-post to the correct customer; allocation history to settle disputes.
**Residual:** medium-low.

### R-04 Incorrect financial calculations
**Mitigations:** integer paise; one rounding function; backend-only arithmetic; re-validation at confirm/approval; DB CHECKs (`total = paid_now + credit`); invariants I1–I14 with property-based tests and nightly reconciliation; cost snapshots so profit doesn't drift; shop-timezone business dates with midnight tests; metric definitions shown on screen; ban on the ambiguous "kamai" label.
**Residual:** low.

### R-05 Network failures
**Mitigations:** idempotent retries with backoff; small audio (Opus, ≤ 15 s); explicit UI states; local retry queue for manual writes with a "pending sync" badge; AI circuit breakers; manual UI unaffected by AI outages; pending-action and approval TTLs.
**Residual:** medium.

### R-06 Data privacy
**Data:** customer names, phone numbers, debts, shop revenue, transcripts, password hashes.
**Mitigations:** **no raw audio retention** (in-memory only, below spool threshold, verified by test SV-9); transcripts time-limited then redacted; PII-free logs via allowlist + redaction, verified by sentinel tests (SV-8); minimal data to AI providers and provider retention terms reviewed; DPDP Act 2023 processes (notice, consent for reminders, deletion, breach plan); TLS and encryption at rest; least-privilege DB roles; secrets outside Git; India-region hosting preferred.
**Residual:** low.

### R-07 Multi-shop data isolation
Higher exposure now that one owner can hold several shops, since a bug in active-shop handling could mix two shops of the *same* owner.
**Mitigations:** active shop only from the server-side session; switching re-verifies membership and reissues the token; shop-scoped repositories; RLS `ENABLE + FORCE`, fail-closed; app role without BYPASSRLS, verified at startup (SV-2); composite FKs; 404 for foreign IDs; isolation suite including **two shops owned by the same user** (SV-4); worker sets context per job.
**Residual:** low.

### R-08 AI hallucinations / wrong intent
**Mitigations:** LLM has no write path; strict schemas; backend entity resolution; numbers cross-checked against the transcript; direction-sensitive phrasing ("Ramesh **ne** diye" vs "Ramesh **ko** diye") confirmed in plain words; template-only numeric replies; evaluation suite per language; human confirmation.
**Residual:** medium-low.

### R-09 AI provider outage / latency / price
Adapters with fakes; timeouts and circuit breakers; manual UI fallback; cost/latency monitoring; optional rule-based parser for top intents.

### R-10 Low adoption / trust
Pilot of 5–10 shops with close support; starter catalogue; opening-balance import for udhaar; Hindi onboarding; visible safety cues; retention metrics per feature.

### R-11 Unit/quantity misinterpretation
Deterministic unit and number-word tables; allowed units per product; confirmation shows spoken and normalized forms ("paav kilo = 0.250 kg"); per-product sanity limits.

### R-12 Concurrency
Row locks with a fixed lock order (database-design §9); `x = x + delta` on locked rows; optimistic versions on master data; concurrent-writer tests (two staff giving udhaar to the same customer; simultaneous sales of the last unit).

### R-13 Account compromise (password authentication)
**Causes:** weak or reused passwords, credential stuffing, shoulder-surfing in the shop, shared family phones, **unverified phone numbers** (someone registers another person's number), no self-service recovery until OTP.
**Mitigations:**
1. Argon2id hashing (SV-7); common-password blocklist; 8-char minimum.
2. Per-phone progressive lockout and per-IP rate limits; generic errors; dummy-hash timing equalization.
3. Rotating refresh tokens with reuse detection; device list and remote logout; password change revokes sessions.
4. Owner-only sensitive actions (reversal, write-off, staff management, reminders) may require password re-entry **[decide in Phase 2]**.
5. Staff accounts are separate from the owner's (no password sharing); deactivation revokes sessions immediately.
6. Unverified numbers: support process for "my number is already registered"; OTP verification as soon as an SMS provider is chosen.
7. Recovery: interim platform-assisted reset with identity check, audited (open Q-18).
**Residual:** medium until OTP is added.

### R-14 Reminder misuse / customer annoyance
Owner sends manually, so there is no platform-level messaging liability. Still: consent flag, frequency cap, polite approved template, exact recipient list shown before links are generated, `wa.me` URLs not logged.

### R-15 Prompt injection
No privileged LLM tools; names passed as structured data; outputs validated; confirmation and permissions cannot be bypassed by model output.

### R-16 AI cost overrun
Per-command cost logging; deterministic "haan/nahi" handling; smallest adequate model; cached TTS for fixed phrases; per-shop rate limits; budget alerts.

### R-17 Approval bottleneck (new)
**Scenario:** staff request udhaar above limit while the owner is away; the customer is waiting.
**Mitigations:** in-app notification with a prominent approvals inbox; owner can approve from any device; owner sets realistic staff limits; request expiry so stale requests don't post days later; clear staff message ("Owner approval pending — customer ko rukne ko kahein ya cash lein"); metrics on approval latency to tune limits during the pilot. Future: push notifications / WhatsApp alert to owner.

### R-18 Override abuse / phantom stock (new)
**Mitigations:** overrides are Owner-only (staff must request); mandatory reason codes; override recorded on the business transaction and in the audit log; negative-stock products flagged for counting; override report for the owner; invariant I11 test.

### R-19 Misleading profit figures (new)
**Causes:** missing cost prices, unitemized sales, personal withdrawals mixed with expenses.
**Mitigations:** gross profit only over lines with known cost, with **cost coverage %** displayed; unitemized sales shown separately and excluded; net profit always labelled "estimated"; personal withdrawals excluded via category kind; definitions on screen; no single "kamai" number.

### R-20 Stock-block friction during onboarding (new)
**Scenario:** blocking sales above recorded stock (decision Q-07) will block constantly in week one, when shops haven't entered opening stock, and could kill adoption.
**Mitigations:** guided opening-stock entry (voice-friendly bulk entry) during onboarding; quick owner override with a one-tap "stock not entered" reason; unitemized sales as a fallback; evaluate a per-product "not stock-tracked" option (open Q-22); monitor override frequency in the pilot.

### R-21 Payment allocation disputes (new)
**Scenario:** the customer says a payment was for a specific old bill; FIFO allocated it elsewhere.
**Mitigations:** FIFO by default (matches the common expectation that old dues are cleared first); manual selection of entries in the UI; allocation history visible on the customer profile and statement; reallocation by reversing and re-recording the payment (audited).

## 3. Risk-to-control traceability

| Control | Risks |
|---|---|
| Mandatory confirmation with resolved details | R-01, R-03, R-08, R-11 |
| Idempotency keys committed with business writes; single execution | R-02, R-05 |
| Deterministic backend calculation, paise, cost snapshots | R-04, R-08, R-19 |
| Business transactions, append-only ledgers, linked reversals, audit | R-02, R-03, R-04, R-18, R-21 |
| RLS (FORCE), no-BYPASSRLS app role, composite FKs, isolation suite | R-07 |
| Argon2id, lockout, session rotation | R-13 |
| In-memory audio, log redaction, transcript retention | R-06 |
| Approval requests with expiry | R-17, R-18 |
| Adapters + manual fallback | R-05, R-09, R-16 |
| Evaluation suite | R-01, R-08, R-11 |
| Row locks + lock order | R-12 |

## 4. Monitoring indicators

| Indicator | Alert |
|---|---|
| Voice cancel/correct rate | > 20 % per shop/language per week |
| Ledger reconciliation drift | Any non-zero |
| Failed logins / lockouts | Spike per phone or IP |
| Cross-shop 404s on foreign IDs | Unusual spike |
| Approval latency | Median > 15 min during the pilot (tune limits) |
| Stock overrides per shop | Trend review weekly |
| Gross-profit cost coverage | < 60 % → prompt owner to add costs |
| AI error rate / p95 latency / cost | > 5 % errors, p95 > 5 s, cost over budget |
