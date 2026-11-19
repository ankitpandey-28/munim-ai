# Munim AI — API Reference (Phases 2–3)

Base path: `/api/v1`. Interactive OpenAPI docs: `http://127.0.0.1:8000/docs` (disabled in production).

Sections: [Conventions](#conventions) · [Health](#health) · [Authentication](#authentication-auth) · [Shops](#shops-and-memberships) · [Catalogue](#catalogue-catalog) · [Role permissions](#role-permissions)

## Conventions

| Topic | Rule |
|---|---|
| Authentication | Opaque session token in the httpOnly, `SameSite=Strict`, `Secure` cookie `munim_session`. JavaScript never sees it |
| Shop context | Always the session's **active shop**, re-verified against an active membership on every request. Never accepted in paths or bodies (unknown fields → 422) |
| Idempotency | Endpoints marked **Idem** require `Idempotency-Key` (8–128 chars). A duplicate returns the stored response with `Idempotent-Replayed: true`; the same key with a different body → 409 `IDEMPOTENCY_KEY_REUSED` |
| CSRF | State-changing requests with an `Origin` header outside `FRONTEND_ORIGINS` → 403 `ORIGIN_NOT_ALLOWED` |
| Errors | `{"error": {"code", "message", "details", "request_id"}}`; validation errors never echo input |
| Request id | `X-Request-ID` echoed on every response and recorded in audit entries |
| Money | Integer **paise** in every request and response (`4400` = ₹44.00). Requests must send JSON integers: floats (`44.5`, `4400.0`), numeric strings (`"4400"`) and booleans are rejected with 422. Range 0 to 2⁵³−1 |
| Quantities | Decimal **strings** with up to 3 decimal places (`"2.500"`), matching `NUMERIC(14,3)`. Requests may send a string or an integer; floats are rejected. Responses always use exactly 3 decimal places (`"30"` → `"30.000"`) |
| Pagination | `limit` (1–100, default 50) + `offset`; responses include `total` where cheap |
| Common errors | 401 `AUTHENTICATION_REQUIRED`; 403 `PASSWORD_CHANGE_REQUIRED`, `NO_ACTIVE_SHOP`, `PERMISSION_DENIED`, `ORIGIN_NOT_ALLOWED`; 422 `VALIDATION_ERROR` (with `details[].loc`); 400 `IDEMPOTENCY_KEY_REQUIRED`; 409 `IDEMPOTENCY_KEY_REUSED` |

## Health

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | — | Status, version, database connectivity and runtime identity (`role_check`) |

## Authentication (`/auth`)

| Method | Path | Auth | Description | Errors |
|---|---|---|---|---|
| POST | `/auth/register` | — | `{phone, name, password, preferred_language?}` → 201 + session cookie. Phone normalised to E.164 | 409 `PHONE_ALREADY_REGISTERED`, 422 `WEAK_PASSWORD`, 429 |
| POST | `/auth/login` | — | `{phone, password}` → new session (any presented session is revoked) | 401 `INVALID_CREDENTIALS` (same for unknown phone), 429 `TOO_MANY_ATTEMPTS` (lockout or IP throttle) |
| POST | `/auth/logout` | session | Revoke this session, clear cookie → 204 | 401 |
| POST | `/auth/logout-all` | session | Revoke all of the user's sessions → 204 | 401 |
| POST | `/auth/change-password` | session* | `{current_password, new_password}` → revokes every session, issues a new cookie | 401 `INVALID_CURRENT_PASSWORD`, 422 `WEAK_PASSWORD`/`PASSWORD_UNCHANGED` |
| GET | `/auth/me` | session* | User (no secrets), memberships, active shop | 401 |
| GET | `/auth/sessions` | session* | Active sessions (`current` flag) | 401 |
| DELETE | `/auth/sessions/{id}` | session* | Revoke one of my sessions → 204 | 404 |

\* Also allowed while `must_change_password` is true. Every other authenticated endpoint returns 403 `PASSWORD_CHANGE_REQUIRED` until the password is changed.

## Shops and memberships

| Method | Path | Permission | Description | Notable errors |
|---|---|---|---|---|
| POST | `/shops` **Idem** | authenticated | Create a shop; caller becomes owner; becomes active shop | 400 `IDEMPOTENCY_KEY_REQUIRED` |
| GET | `/shops/mine` | authenticated | My active memberships (`is_active` marks the session's shop) | |
| POST | `/session/active-shop` | authenticated | `{shop_id}` → switch active shop (requires active membership) | 404 (non-member looks like non-existent) |
| GET | `/shops/current` | member | Active shop + my role | 403 `NO_ACTIVE_SHOP` |
| PATCH | `/shops/current` **Idem** | owner, admin | Partial update with `version` (optimistic concurrency) | 409 `VERSION_CONFLICT` |
| GET | `/shops/current/members` | owner, admin | Paginated members (`include_removed`); phones masked | |
| POST | `/shops/current/members` **Idem** | owner (any role), admin (staff only) | `{phone, role, name?, temporary_password?, credit_limit_paise?}`; creates an account with `must_change_password` if the phone is new | 409 `ALREADY_MEMBER`, 422 `ACCOUNT_DETAILS_REQUIRED` |
| PATCH | `/shops/current/members/{id}` | owner (roles), owner/admin (staff limits) | `{role?, credit_limit_paise?}` | 409 `LAST_OWNER` |
| POST | `/shops/current/members/{id}/deactivate` | owner (anyone), admin (staff), self (leave) | Removes membership; that user's sessions lose this shop immediately | 409 `LAST_OWNER` |
| GET | `/shops/current/audit-logs` | owner | Paginated audit trail (secrets masked) | |

## Catalogue (`/catalog`)

Units of measure, product categories, products, product aliases and price history (Phase 3).

### Catalogue rules (apply to every endpoint below)

| Topic | Behaviour |
|---|---|
| Authentication | Every catalogue endpoint requires a valid session (401 otherwise) and an active shop membership (403 `NO_ACTIVE_SHOP`) |
| Shop isolation | Records always belong to the session's verified active shop. No endpoint accepts a `shop_id` (body or query: 422). A category, product or alias of **another shop returns 404 with the same message as a non-existent id**, so existence is never revealed. PostgreSQL row-level security enforces the same rule in the database |
| Archive, never delete | Categories and products are archived (`archived_at` set), never permanently deleted; there are no DELETE routes for them (405). Archived records are hidden from lists unless `include_archived=true`, stay readable by id, and can't be edited (409) |
| Optimistic concurrency | Products carry an integer `version`. `PATCH /products/{id}` and `POST /products/{id}/prices` require the current `version`; a stale one → 409 `VERSION_CONFLICT` with `details.current_version`. Every effective change (including archiving) increments it; a request that changes nothing leaves it unchanged. Categories have no version (last write wins) |
| Prices | Prices change **only** through `POST /products/{id}/prices`. `PATCH /products/{id}` rejects price fields (422). Price history is **append-only**: rows are never updated or deleted (enforced by database privileges and a trigger). A product's initial prices are recorded when it's created; later rows are added only for prices whose value actually changes |
| Cost prices | Only roles with `catalog.view_costs` (owner, admin) see `default_cost_price_paise` and cost-price history. For staff, product responses return `default_cost_price_paise: null` with `costs_visible: false`, cost rows are excluded from price history (and from its `total`), and `price_type=cost` → 403 |
| Name rules | Names are trimmed, internal whitespace collapsed, control characters rejected. Category names 1–80 characters, product names 1–120; optional Hindi names have the same limits (blank → `null`). Active names are unique per shop **case-insensitively**; an archived record's name can be reused |
| Barcodes | Optional, at most 64 characters, no spaces or control characters (blank → `null`). Unique per shop **including archived products**: an archived product keeps its barcode reserved |
| Units and decimals | `base_unit_code` must exist in `GET /catalog/units` (input lower-cased). A loose (weighed/measured) product needs a unit with `allows_decimal: true`; a fractional `reorder_level` is allowed only for such units |

**Shared response objects**

| Object | Fields |
|---|---|
| Unit | `code`, `dimension` (`mass`/`volume`/`count`), `factor_to_dimension_base` (decimal string, e.g. g → `"0.001000"` of kg), `allows_decimal`, `name_en`, `name_hi`, `spoken_forms[]` |
| Category | `id`, `name`, `name_hi`, `sort_order`, `archived_at`, `created_at`, `updated_at` |
| Product | `id`, `name`, `name_hi`, `category_id`, `base_unit_code`, `is_loose`, `selling_price_paise`, `default_cost_price_paise` (null for staff), `costs_visible`, `reorder_level` (decimal string or null), `barcode`, `archived_at`, `version`, `created_at`, `updated_at` |
| Alias | `id`, `product_id`, `alias_text`, `language` (`hi`/`hinglish`/`en`/`pa`/null), `source` (`seed`/`manual`/`learned`), `created_at`. Internal matching fields (`normalized_text`, `phonetic_key`) are never returned |
| Price record | `id`, `product_id`, `price_type` (`selling`/`cost`), `price_paise`, `effective_from`, `set_by_user_id`, `source` (`manual`/`voice`/`system`), `created_at` |

### Units

| Method | Path | Permission | Request | Response | Status |
|---|---|---|---|---|---|
| GET | `/catalog/units` | `catalog.view` | — | `{items: Unit[]}`, ordered by dimension and size | 200 |

Units are global reference data (seeded by migration); there are no endpoints to change them.

### Categories

| Method | Path | Permission | Request | Response | Status / errors |
|---|---|---|---|---|---|
| POST | `/catalog/categories` **Idem** | `catalog.manage` | `{name, name_hi?, sort_order? (integer, default 0)}` | Category | 201; 409 `CATEGORY_NAME_TAKEN` |
| GET | `/catalog/categories` | `catalog.view` | query `include_archived` (bool, default false) | `{items: Category[], total}`, ordered by `sort_order`, then name (case-insensitive). Not paginated (few per shop) | 200 |
| GET | `/catalog/categories/{category_id}` | `catalog.view` | — | Category (archived ones too) | 200; 404 |
| PATCH | `/catalog/categories/{category_id}` **Idem** | `catalog.manage` | At least one of `name` (not null), `name_hi` (null clears), `sort_order` (not null) | Category | 200; 404; 409 `CATEGORY_NAME_TAKEN`, `CATEGORY_ARCHIVED`; 422 (empty body) |
| POST | `/catalog/categories/{category_id}/archive` | `catalog.manage` | — | Category with `archived_at` | 200; 404; 409 `ALREADY_ARCHIVED`; 409 `CATEGORY_IN_USE` with `details.active_products` while active products are assigned |

### Products

| Method | Path | Permission | Request | Response | Status / errors |
|---|---|---|---|---|---|
| POST | `/catalog/products` **Idem** | `catalog.manage` **and** `catalog.manage_prices` | `{name, base_unit_code, selling_price_paise, name_hi?, category_id?, is_loose? (default false), default_cost_price_paise?, reorder_level?, barcode?}`. Initial selling price (and cost price, if given) are written to price history | Product (`version: 1`) | 201; 422 `INVALID_UNIT`, `INVALID_CATEGORY` (missing or another shop's), `CATEGORY_ARCHIVED`, `LOOSE_REQUIRES_DECIMAL_UNIT`, `DECIMAL_NOT_ALLOWED_FOR_UNIT`; 409 `PRODUCT_NAME_TAKEN`, `BARCODE_TAKEN`, `BARCODE_RESERVED_BY_ARCHIVED` |
| GET | `/catalog/products` | `catalog.view` | query: `q`, `category_id`, `include_archived`, `limit`, `offset` (see below) | `{items: Product[], total, limit, offset}` | 200; 422 |
| GET | `/catalog/products/{product_id}` | `catalog.view` | — | Product (archived ones too) | 200; 404 |
| PATCH | `/catalog/products/{product_id}` **Idem** | `catalog.manage` | `{version}` plus at least one of `name`, `base_unit_code`, `is_loose` (these three can't be null), `name_hi`, `category_id`, `reorder_level`, `barcode` (null clears). **Price fields → 422** (use `/prices`) | Product (`version` + 1, or unchanged if nothing changed) | 200; 404; 409 `VERSION_CONFLICT`, `PRODUCT_ARCHIVED`, `PRODUCT_NAME_TAKEN`, `BARCODE_TAKEN`, `BARCODE_RESERVED_BY_ARCHIVED`; 422 (same unit/category codes as create) |
| POST | `/catalog/products/{product_id}/archive` | `catalog.manage` | — | Product with `archived_at`, `version` + 1 | 200; 404; 409 `ALREADY_ARCHIVED` |

**Search and filtering** (`GET /catalog/products`)

| Parameter | Rules |
|---|---|
| `q` | Optional, at most 120 characters; blank is ignored. Matches a product if any of these holds: the **name** or **Hindi name** contains `q` (case-insensitive substring); an **alias** contains `q` after text normalisation (e.g. `CHEENI!` finds alias "Cheeni"); the **barcode equals** `q` exactly (no partial barcode matching). `%` and `_` are treated as ordinary characters |
| `category_id` | Optional UUID; only products in that category |
| `include_archived` | Boolean, default `false` |
| `limit` / `offset` | 1–100 (default 50) / 0–100000 (default 0) |
| other | Unknown query parameters (including `shop_id`) → 422 |

Results are ordered by name (case-insensitive), then id, so pages are stable.

**Alias normalisation** (used for alias matching and duplicate detection): Unicode NFKC, case-folding, symbols and punctuation become spaces, whitespace is collapsed, Devanagari and Gurmukhi vowel signs are kept, and Indic digits map to ASCII. There's no transliteration between scripts ("chini" and "चीनी" are different keys).

### Product aliases

| Method | Path | Permission | Request | Response | Status / errors |
|---|---|---|---|---|---|
| GET | `/catalog/products/{product_id}/aliases` | `catalog.view` | — | `{items: Alias[]}`, oldest first | 200; 404 |
| POST | `/catalog/products/{product_id}/aliases` **Idem** | `catalog.manage` | `{alias_text (1–120, must contain letters or digits), language?}` | Alias (`source: "manual"`) | 201; 404; 409 `ALIAS_EXISTS` (same normalised text on this product), `PRODUCT_ARCHIVED`; 422 |
| DELETE | `/catalog/products/{product_id}/aliases/{alias_id}` | `catalog.manage` | — | no body | 204; 404 (unknown alias, or alias of a different product); 409 `PRODUCT_ARCHIVED` |

The same alias text may be used on different products. Alias removal deletes the row (aliases are matching hints, not records of value) and is recorded in the audit log.

### Price history and price updates

| Method | Path | Permission | Request | Response | Status / errors |
|---|---|---|---|---|---|
| GET | `/catalog/products/{product_id}/prices` | `catalog.view` (cost rows need `catalog.view_costs`) | query `price_type` (`selling`/`cost`, optional), `limit` (1–100, default 50), `offset` (0–100000) | `{items: PriceRecord[], total, limit, offset, costs_visible}`, newest first | 200; 404; 403 if staff ask for `price_type=cost`; 422 |
| POST | `/catalog/products/{product_id}/prices` **Idem** | `catalog.manage_prices` | `{version, selling_price_paise?, default_cost_price_paise?}`: at least one price; an omitted price stays unchanged; `null` is rejected | Product. A history row is added for each price whose value changes, and `version` + 1. If no value changes, nothing is written and `version` stays the same | 200; 404; 409 `VERSION_CONFLICT`, `PRODUCT_ARCHIVED`; 422 |

### Idempotency in the catalogue

| Requires `Idempotency-Key` | Doesn't require it (retry-safe without it) |
|---|---|
| POST/PATCH categories; POST/PATCH products; POST aliases; POST prices | Archive endpoints (a repeat → 409 `ALREADY_ARCHIVED`) and alias DELETE (a repeat → 404); neither repeats any effect |

A failed request (any 4xx) leaves nothing behind (no partial product, price-history, alias, audit or idempotency rows), so its key can be reused for a corrected request.

### Audit events

`category.created`, `category.updated`, `category.archived`, `product.created`, `product.updated`, `product.archived`, `product.alias_added`, `product.alias_removed`, `product.price_changed` (with before/after prices and versions). They're visible to owners via `GET /shops/current/audit-logs`.

## Role permissions

| Permission | Owner | Admin | Staff |
|---|:-:|:-:|:-:|
| View shop | ✓ | ✓ | ✓ |
| Edit shop details | ✓ | ✓ | — |
| View members | ✓ | ✓ | — |
| Add/remove staff, staff credit limits | ✓ | ✓ | — |
| Add/remove owners/admins, change roles | ✓ | — | — |
| Audit trail | ✓ | — | — |
| Leave the shop | ✓ (not the last owner) | ✓ | ✓ |
| `catalog.view`: units, categories, products, aliases, **selling** prices and selling-price history | ✓ | ✓ | ✓ |
| `catalog.view_costs`: default cost price, cost-price history | ✓ | ✓ | — |
| `catalog.manage`: create/edit/archive categories and products; add/remove aliases | ✓ | ✓ | — |
| `catalog.manage_prices`: change selling/cost prices (also required to create a product) | ✓ | ✓ | — |

Permissions are enforced by the API dependencies and again in the service layer. Per-member permission overrides are not implemented.
