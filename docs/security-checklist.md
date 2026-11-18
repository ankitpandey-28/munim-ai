# Munim AI — Security Checklist (Phase 2)

Each control lists where it's implemented and the automated evidence. "Verified" means a test or check ran and passed on 2026-11-19. Integration tests run against a disposable PostgreSQL 18.4 cluster (never SQLite, never the developer's database).

## Database and tenancy

| # | Control | Implementation | Evidence | Status |
|---|---|---|---|---|
| D1 | Runtime role is `munim_app`: NOSUPERUSER, NOBYPASSRLS, NOINHERIT, owns nothing, no CREATE/TEMP | `infra/postgres/local-setup.sql`; migration 0002 grants | `test_runtime_and_owner_role_attributes`, `test_runtime_role_owns_nothing_and_cannot_create`; real DB check | ✅ Verified (test + real DB) |
| D2 | Migrations run only as `munim_owner` on `munim_ai`, verified live before migrating | `alembic/env.py` → `verify_migration_identity` | `test_verify_migration_identity_*`; refusals shown on a throwaway cluster | ✅ Verified |
| D3 | API refuses to start with an unsafe runtime identity; production also refuses when the DB is unreachable | `app/core/startup.py` | Startup check passed on the real DB; unit tests of the rules | ✅ Verified |
| D4 | RLS `ENABLE` + `FORCE` on all 35 tenant tables; global tables excluded | migration 0002 | `test_rls_enabled_and_forced_on_every_tenant_table`; real DB check | ✅ Verified |
| D5 | Missing or empty tenant context fails closed | `NULLIF(current_setting(...), '')::uuid` | `test_missing_context_fails_closed` | ✅ Verified |
| D6 | Tenant context is transaction-local and re-applied every transaction | `app/database/session.py` (`after_begin`, `set_config(..., true)`) | `test_tenant_context_survives_commit` | ✅ Verified |
| D7 | Cross-shop reads invisible, writes rejected (USING + WITH CHECK) | standard policy | `test_cross_shop_reads_are_invisible`, `test_cross_shop_writes_are_rejected` | ✅ Verified |
| D8 | Composite tenant FKs block cross-shop links | `tenant_fk()` | `test_composite_tenant_fk_blocks_cross_shop_links` | ✅ Verified |
| D9 | `FORCE` binds the owner role too | migration 0002 | `test_force_rls_binds_the_owner_role_too` | ✅ Verified |
| D10 | Shop context never from client input; membership re-verified per request | `app/api/deps.py::get_shop_context`; `extra="forbid"` | `test_cannot_switch_into_or_read_another_users_shop`, `test_shop_input_validation`, `test_deactivated_member_loses_access_immediately` | ✅ Verified |
| D11 | Append-only financial/audit rows: no DELETE, immutable amounts (grants + triggers, also for the owner) | migration 0002 | `test_financial_rows_cannot_be_deleted_or_amounts_changed`, `test_audit_log_is_append_only` | ✅ Verified |
| D12 | A transaction is reversed at most once; reversals are not reversible | unique index, CHECKs, status trigger, service lock | `test_transaction_can_only_be_reversed_once`, `test_reversal_is_linked_and_only_once` | ✅ Verified |
| D13 | Least privilege: DELETE only on 5 non-financial tables; no TRUNCATE/REFERENCES/TRIGGER | migration 0002 | `test_no_delete_on_financial_or_audit_tables`; real DB check | ✅ Verified |
| D14 | Migrations match models (no drift) | `alembic check` | `test_migrations_match_models_and_are_at_head`; real DB `alembic check` | ✅ Verified |

## Authentication and sessions

| # | Control | Evidence | Status |
|---|---|---|---|
| A1 | Argon2id hashing (RFC 9106 low-memory profile); rehash on parameter upgrade | `test_password_stored_as_argon2id`, `test_argon2id_hash_and_verify` | ✅ |
| A2 | Password policy (8–128, common list, not the phone, not repetitive) | `test_weak_passwords_rejected_without_echo`, `test_password_policy` | ✅ |
| A3 | No user enumeration at login (same error, same Argon2 cost) | `test_wrong_password_and_unknown_phone_are_indistinguishable` | ✅ |
| A4 | Lockout after N failures; per-IP throttle; registration throttle | `test_lockout_after_repeated_failures`, `test_ip_rate_limit_uses_trusted_proxy_client_ip`, `test_registration_rate_limit` | ✅ |
| A5 | Login attempts store only HMACs of phone/IP | `test_login_attempts_store_only_keyed_hashes` | ✅ |
| A6 | 256-bit random session tokens, stored only as SHA-256 | `test_session_token_stored_only_as_hash` | ✅ |
| A7 | No session fixation: new token on every login and password change; presented session revoked | `test_forged_or_fixed_session_cookie_is_not_accepted`, `test_login_revokes_previously_presented_session` | ✅ |
| A8 | Absolute (30 d) and idle (7 d) expiry; revocation effective immediately | `test_absolute_expiry`, `test_idle_expiry`, `test_logout_revokes_session`, `test_logout_all_revokes_every_session` | ✅ |
| A9 | Password change revokes all sessions | `test_change_password_rotates_and_revokes` | ✅ |
| A10 | Temporary passwords force a change before any other access | `test_add_new_member_creates_account_requiring_password_change` | ✅ |
| A11 | Cookie flags: HttpOnly, SameSite=Strict, Secure (default), Path=/ | `test_register_creates_user_and_session`, `test_secure_cookie_flag_by_default` | ✅ |
| A12 | CSRF: Origin allow-list on state-changing requests | `test_cross_origin_state_change_rejected`; E2E | ✅ |
| A13 | Password hashes never returned | `PublicUser` schema; `test_register_creates_user_and_session`; E2E | ✅ |

## Authorization

| # | Control | Evidence | Status |
|---|---|---|---|
| Z1 | Role matrix enforced server-side | `test_role_permissions`, `test_role_permission_matrix` | ✅ |
| Z2 | Last active owner can't be demoted or removed (rows locked) | `test_last_owner_cannot_be_demoted_or_removed`, `test_ownership_transfer_then_step_down` | ✅ |

## Integrity

| # | Control | Evidence | Status |
|---|---|---|---|
| I1 | Idempotency record committed in the same transaction as the operation; duplicates replay | `test_duplicate_request_replays_original_response` | ✅ |
| I2 | Concurrent duplicates execute once | `test_concurrent_duplicates_execute_once` (4 parallel requests) | ✅ |
| I3 | Key reuse with a different body rejected; keys per user | `test_same_key_different_body_is_rejected`, `test_keys_are_scoped_per_user` | ✅ |
| I4 | Failed operations roll back completely (header + audit) | `test_failed_operation_rolls_back_everything` | ✅ |
| I5 | Audit entries in the same transaction, secrets masked | `test_post_transaction_records_actor_and_audit`; `audit.service._sanitize` | ✅ |

## Secrets and logging

| # | Control | Evidence | Status |
|---|---|---|---|
| S1 | Secrets only from environment (`SecretStr`); `.env` git-ignored; backups git-ignored | `test_database_url_is_secret`; `.gitignore` | ✅ |
| S2 | Production config fails closed (auth key, Secure cookie, https origins, DB URL) | `test_production_rejects_unsafe_security_config` | ✅ |
| S3 | Logs contain no passwords, phones, tokens or hashes | `test_no_credentials_in_logs`, logging redaction tests; E2E log scan | ✅ |
| S4 | No stack traces or input echo in error responses | `test_unhandled_exception_returns_generic_500`, `test_validation_error_does_not_echo_input` | ✅ |
| S5 | Raw audio never stored (no audio column) | schema review; `voice_commands` model | ✅ |
| S6 | Frontend holds no secrets; same-origin proxy | `BACKEND_INTERNAL_URL` is server-only; E2E through the proxy | ✅ |

## Known gaps (tracked)

| # | Gap | Plan |
|---|---|---|
| G1 | Registration throttle is in-process (single API instance) | Move to PostgreSQL if more than one instance is run |
| G2 | Phone numbers aren't verified (no OTP) | OTP phase (SRS FR-AUTH-10) |
| G3 | Self-service password recovery is unavailable | Support-assisted reset pending decision Q-18 |
| G4 | Expired idempotency keys/sessions/login attempts aren't purged yet | Worker jobs (FORCE RLS needs a context-aware purge design) |
| G5 | CI pipeline updated but not yet executed (no GitHub repository) | Push to GitHub to run |
| G6 | Offline Alembic (`--sql`) can't verify identity | Review rendered SQL before applying (done for 0001–0003) |
