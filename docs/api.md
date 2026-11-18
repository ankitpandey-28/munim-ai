# Munim AI — API Reference (Phase 2)

Base path: `/api/v1`. Interactive OpenAPI docs: `http://127.0.0.1:8000/docs` (disabled in production).

## Conventions

| Topic | Rule |
|---|---|
| Authentication | Opaque session token in the httpOnly, `SameSite=Strict`, `Secure` cookie `munim_session`. JavaScript never sees it |
| Shop context | Always the session's **active shop**, re-verified against an active membership on every request. Never accepted in paths or bodies (unknown fields → 422) |
| Idempotency | Endpoints marked **Idem** require `Idempotency-Key` (8–128 chars). A duplicate returns the stored response with `Idempotent-Replayed: true`; the same key with a different body → 409 `IDEMPOTENCY_KEY_REUSED` |
| CSRF | State-changing requests with an `Origin` header outside `FRONTEND_ORIGINS` → 403 `ORIGIN_NOT_ALLOWED` |
| Errors | `{"error": {"code", "message", "details", "request_id"}}`; validation errors never echo input |
| Request id | `X-Request-ID` echoed on every response and recorded in audit entries |
| Money | integer paise |
| Pagination | `limit` (1–100, default 50) + `offset`; responses include `total` where cheap |

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

## Role permissions (Phase 2)

| Permission | Owner | Admin | Staff |
|---|:-:|:-:|:-:|
| View shop | ✓ | ✓ | ✓ |
| Edit shop details | ✓ | ✓ | — |
| View members | ✓ | ✓ | — |
| Add/remove staff, staff credit limits | ✓ | ✓ | — |
| Add/remove owners/admins, change roles | ✓ | — | — |
| Audit trail | ✓ | — | — |
| Leave the shop | ✓ (not the last owner) | ✓ | ✓ |
