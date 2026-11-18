"""Authentication end-to-end against real PostgreSQL (through RLS as munim_app)."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.security import hash_session_token
from tests.integration.conftest import STRONG_PASSWORD, next_phone, register

API = "/api/v1/auth"


def _login(client, phone, password=STRONG_PASSWORD):
    return client.post(f"{API}/login", json={"phone": phone, "password": password})


# ----------------------------------------------------------------------------- registration
def test_register_creates_user_and_session(client, settings) -> None:
    phone = next_phone()
    response = client.post(
        f"{API}/register",
        json={"phone": phone[3:], "name": "  Sunita Devi ", "password": STRONG_PASSWORD},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["phone"] == phone  # normalised to E.164
    assert body["user"]["name"] == "Sunita Devi"
    assert body["active_shop_id"] is None and body["memberships"] == []
    assert "password" not in json.dumps(body).lower().replace("must_change_password", "")
    cookie = response.headers["set-cookie"]
    assert f"{settings.session_cookie_name}=" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert client.get(f"{API}/me").status_code == 200


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("98765 43210", "+919876543210"),
        ("+91-98765-43210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
    ],
)
def test_phone_normalisation_variants_map_to_one_account(make_client, raw, expected) -> None:
    from app.core.security import normalize_indian_mobile

    assert normalize_indian_mobile(raw) == expected


@pytest.mark.parametrize("phone", ["12345", "+1 202 555 0100", "5876543210", "98765abc10"])
def test_invalid_phone_rejected(client, phone) -> None:
    response = client.post(
        f"{API}/register", json={"phone": phone, "name": "X", "password": STRONG_PASSWORD}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("password", "problem"),
    [("short1", "too_short"), ("password123", "too_common"), ("aaaaaaaaaa", "too_repetitive")],
)
def test_weak_passwords_rejected_without_echo(client, password, problem) -> None:
    response = client.post(
        f"{API}/register", json={"phone": next_phone(), "name": "X", "password": password}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "WEAK_PASSWORD"
    assert any(d["type"] == problem for d in error["details"])
    assert password not in response.text


def test_password_equal_to_phone_rejected(client) -> None:
    phone = next_phone()
    response = client.post(
        f"{API}/register", json={"phone": phone, "name": "X", "password": phone[3:]}
    )
    assert response.status_code == 422
    assert any(d["type"] == "same_as_phone" for d in response.json()["error"]["details"])


def test_duplicate_phone_rejected(make_client) -> None:
    user = register(make_client())
    response = make_client().post(
        f"{API}/register", json={"phone": user["phone"], "name": "Y", "password": STRONG_PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PHONE_ALREADY_REGISTERED"


def test_password_stored_as_argon2id(client, app_engine) -> None:
    user = register(client)
    with app_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT password_hash FROM users WHERE phone = :p"), {"p": user["phone"]}
        ).scalar_one()
    assert stored.startswith("$argon2id$")
    assert STRONG_PASSWORD not in stored


# ----------------------------------------------------------------------------- login / errors
def test_login_success_issues_new_session(make_client) -> None:
    user = register(make_client())
    client = make_client()
    response = _login(client, user["phone"])
    assert response.status_code == 200
    assert response.json()["user"]["phone"] == user["phone"]
    assert client.get(f"{API}/me").status_code == 200


def test_wrong_password_and_unknown_phone_are_indistinguishable(make_client) -> None:
    user = register(make_client())
    client = make_client()
    wrong = _login(client, user["phone"], "Wrong-Password-123")
    unknown = _login(client, next_phone(), "Wrong-Password-123")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_lockout_after_repeated_failures(make_client, settings, app_engine) -> None:
    user = register(make_client())
    client = make_client()
    for _ in range(settings.login_max_failures):
        assert _login(client, user["phone"], "Wrong-Password-123").status_code == 401
    # Locked: even the correct password is refused, with the generic throttle response.
    locked = _login(client, user["phone"])
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    with app_engine.connect() as conn:
        reasons = (
            conn.execute(
                text(
                    "SELECT failure_reason FROM login_attempts la"
                    " ORDER BY attempted_at DESC LIMIT :n"
                ),
                {"n": settings.login_max_failures + 1},
            )
            .scalars()
            .all()
        )
    assert reasons[0] == "locked"
    assert reasons.count("bad_credentials") == settings.login_max_failures


def test_login_attempts_store_only_keyed_hashes(make_client, app_engine) -> None:
    user = register(make_client())
    _login(make_client(), user["phone"], "Wrong-Password-123")
    digits = user["phone"][3:]
    with app_engine.connect() as conn:
        rows = conn.execute(text("SELECT phone_hash, ip_hash FROM login_attempts")).all()
    assert rows
    for phone_hash, ip_hash in rows:
        assert digits not in phone_hash and len(phone_hash) == 64
        assert ip_hash is None or len(ip_hash) == 64


def test_ip_rate_limit_uses_trusted_proxy_client_ip(make_client, settings) -> None:
    """The limit is per client IP: behind a trusted proxy the X-Forwarded-For hop is used,
    so other clients are unaffected."""
    import random

    limited = settings.model_copy(
        update={"login_ip_max_attempts": 5, "trusted_proxy_ips": "testclient"}
    )
    client = make_client(limited)
    attacker = f"203.0.113.{random.randint(1, 254)}"
    bystander = f"198.51.100.{random.randint(1, 254)}"

    def attempt(ip):
        return client.post(
            f"{API}/login",
            json={"phone": next_phone(), "password": "Wrong-Password-123"},
            headers={"X-Forwarded-For": ip},
        )

    for _ in range(5):
        assert attempt(attacker).status_code == 401
    assert attempt(attacker).status_code == 429
    assert attempt(bystander).status_code == 401  # a different client is not throttled


def test_registration_rate_limit(make_client, settings) -> None:
    client = make_client(settings.model_copy(update={"registration_ip_max_per_hour": 2}))
    for _ in range(2):
        register(client)
    response = client.post(
        f"{API}/register", json={"phone": next_phone(), "name": "X", "password": STRONG_PASSWORD}
    )
    assert response.status_code == 429


# ----------------------------------------------------------------------------- sessions
def test_unauthenticated_requests_rejected(client) -> None:
    for path in (f"{API}/me", f"{API}/sessions", "/api/v1/shops/current", "/api/v1/shops/mine"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_forged_or_fixed_session_cookie_is_not_accepted(client, settings) -> None:
    """Session fixation: a client-chosen token never becomes valid, and login replaces it."""
    user = register(client)
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, "attacker-chosen-token-value-1234567890")
    assert client.get(f"{API}/me").status_code == 401
    response = _login(client, user["phone"])
    new_token = response.cookies.get(settings.session_cookie_name)
    assert new_token and new_token != "attacker-chosen-token-value-1234567890"


def test_login_revokes_previously_presented_session(make_client, settings, app_engine) -> None:
    client = make_client()
    user = register(client)
    old_token = client.cookies.get(settings.session_cookie_name)
    _login(client, user["phone"])
    with app_engine.connect() as conn:
        reason = conn.execute(
            text("SELECT revoke_reason FROM auth_sessions WHERE token_hash = :h"),
            {"h": hash_session_token(old_token)},
        ).scalar_one()
    assert reason == "replaced_by_login"


def test_session_token_stored_only_as_hash(client, settings, app_engine) -> None:
    register(client)
    token = client.cookies.get(settings.session_cookie_name)
    with app_engine.connect() as conn:
        hashes = conn.execute(text("SELECT token_hash FROM auth_sessions")).scalars().all()
    assert hash_session_token(token) in hashes
    assert all(token.encode() not in h for h in hashes)


def test_logout_revokes_session(client, settings) -> None:
    register(client)
    token = client.cookies.get(settings.session_cookie_name)
    assert client.post(f"{API}/logout").status_code == 204
    client.cookies.set(settings.session_cookie_name, token)  # replaying the old cookie
    assert client.get(f"{API}/me").status_code == 401


def test_logout_all_revokes_every_session(make_client) -> None:
    first = make_client()
    user = register(first)
    second = make_client()
    _login(second, user["phone"])
    assert second.post(f"{API}/logout-all").status_code == 204
    assert first.get(f"{API}/me").status_code == 401
    assert second.get(f"{API}/me").status_code == 401


def test_list_and_revoke_specific_session(make_client) -> None:
    first = make_client()
    user = register(first)
    second = make_client()
    _login(second, user["phone"])
    sessions = second.get(f"{API}/sessions").json()["items"]
    assert len(sessions) == 2
    other = next(s for s in sessions if not s["current"])
    assert second.delete(f"{API}/sessions/{other['id']}").status_code == 204
    assert first.get(f"{API}/me").status_code == 401
    assert second.get(f"{API}/me").status_code == 200


def test_absolute_expiry(client, settings, super_engine) -> None:
    register(client)
    token = client.cookies.get(settings.session_cookie_name)
    with super_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE auth_sessions SET created_at = now() - interval '2 days',"
                " expires_at = now() - interval '1 second' WHERE token_hash = :h"
            ),
            {"h": hash_session_token(token)},
        )
    response = client.get(f"{API}/me")
    assert response.status_code == 401
    assert "expired" in response.json()["error"]["message"]


def test_idle_expiry(client, settings, super_engine) -> None:
    register(client)
    token = client.cookies.get(settings.session_cookie_name)
    idle = datetime.now(UTC) - timedelta(hours=settings.session_idle_ttl_hours + 1)
    with super_engine.begin() as conn:
        conn.execute(
            text("UPDATE auth_sessions SET last_seen_at = :t WHERE token_hash = :h"),
            {"t": idle, "h": hash_session_token(token)},
        )
    assert client.get(f"{API}/me").status_code == 401


# ----------------------------------------------------------------------------- password change
def test_change_password_rotates_and_revokes(make_client, settings) -> None:
    first = make_client()
    user = register(first)
    second = make_client()
    _login(second, user["phone"])
    old_token = second.cookies.get(settings.session_cookie_name)
    response = second.post(
        f"{API}/change-password",
        json={"current_password": STRONG_PASSWORD, "new_password": "New-Kirana-Pass-77"},
    )
    assert response.status_code == 200
    new_token = response.cookies.get(settings.session_cookie_name)
    assert new_token and new_token != old_token
    assert first.get(f"{API}/me").status_code == 401  # other sessions revoked
    assert second.get(f"{API}/me").status_code == 200  # this client got a fresh session
    assert _login(make_client(), user["phone"]).status_code == 401
    assert _login(make_client(), user["phone"], "New-Kirana-Pass-77").status_code == 200


def test_change_password_requires_current_password(client) -> None:
    register(client)
    response = client.post(
        f"{API}/change-password",
        json={"current_password": "Wrong-Password-1", "new_password": "New-Kirana-Pass-77"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"


def test_change_password_rejects_same_password(client) -> None:
    register(client)
    response = client.post(
        f"{API}/change-password",
        json={"current_password": STRONG_PASSWORD, "new_password": STRONG_PASSWORD},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PASSWORD_UNCHANGED"


# ----------------------------------------------------------------------------- hardening
def test_cross_origin_state_change_rejected(client) -> None:
    response = client.post(
        f"{API}/login",
        json={"phone": next_phone(), "password": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


def test_allowed_origin_accepted(client) -> None:
    response = client.post(
        f"{API}/register",
        json={"phone": next_phone(), "name": "X", "password": STRONG_PASSWORD},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 201


def test_secure_cookie_flag_by_default(make_client, settings) -> None:
    client = make_client(settings.model_copy(update={"session_cookie_secure": True}))
    response = client.post(
        f"{API}/register", json={"phone": next_phone(), "name": "X", "password": STRONG_PASSWORD}
    )
    assert "Secure" in response.headers["set-cookie"]


def test_no_credentials_in_logs(make_client, caplog) -> None:
    client = make_client()
    phone = next_phone()
    with caplog.at_level(logging.DEBUG):
        client.post(
            f"{API}/register", json={"phone": phone, "name": "X", "password": STRONG_PASSWORD}
        )
        client.post(f"{API}/login", json={"phone": phone, "password": "Wrong-Password-123"})
        client.post(f"{API}/login", json={"phone": phone, "password": STRONG_PASSWORD})
    from app.core.logging import JsonFormatter

    logs = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    token = client.cookies.get("munim_session")
    assert STRONG_PASSWORD not in logs
    assert "Wrong-Password-123" not in logs
    assert phone[3:] not in logs
    assert token not in logs
    assert "$argon2id$" not in logs
