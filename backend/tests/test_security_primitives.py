"""Unit tests for security primitives (no database)."""

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.security import (
    InvalidPhoneNumber,
    client_ip,
    hash_password,
    hash_session_token,
    keyed_hash,
    mask_phone,
    needs_rehash,
    new_session_token,
    normalize_indian_mobile,
    password_problems,
    verify_password,
)
from app.modules.shops.permissions import Permission, can_manage_member, has_permission
from app.shared.ids import uuid7


def test_uuid7_version_variant_and_order() -> None:
    ids = [uuid7() for _ in range(2000)]
    assert all(u.version == 7 for u in ids)
    assert all((u.int >> 62) & 0b11 == 0b10 for u in ids)  # RFC 9562 variant
    assert ids == sorted(ids)  # monotonic within the process
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize(
    "raw", ["9876543210", "+919876543210", "+91 98765-43210", "09876543210", "00919876543210"]
)
def test_phone_normalisation(raw: str) -> None:
    assert normalize_indian_mobile(raw) == "+919876543210"


@pytest.mark.parametrize(
    "raw", ["", "123", "+14155550100", "5876543210", "98765432101", "98x6543210"]
)
def test_phone_rejection(raw: str) -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_indian_mobile(raw)


def test_mask_phone() -> None:
    assert mask_phone("+919876543210") == "+91******3210"


def test_password_policy() -> None:
    assert password_problems("Kirana-Strong-1") == []
    assert "too_short" in password_problems("Ab1!")
    assert "too_common" in password_problems("Password123")
    assert "same_as_phone" in password_problems("9876543210", phone="+919876543210")
    assert "too_long" in password_problems("x1" * 70)


def test_argon2id_hash_and_verify() -> None:
    hashed = hash_password("Kirana-Strong-1")
    assert hashed.startswith("$argon2id$")
    assert verify_password("Kirana-Strong-1", hashed)
    assert not verify_password("kirana-strong-1", hashed)
    assert not verify_password("anything", None)  # unknown user path
    assert not verify_password("anything", "not-a-hash")
    assert not needs_rehash(hashed)


def test_session_tokens_are_random_and_hashed() -> None:
    a, b = new_session_token(), new_session_token()
    assert a != b and len(a) >= 43
    assert len(hash_session_token(a)) == 32 and hash_session_token(a) != a.encode()


def test_keyed_hash_is_domain_separated() -> None:
    s = Settings(_env_file=None, auth_secret_key="x" * 40)
    assert keyed_hash("+919876543210", purpose="phone", settings=s) != keyed_hash(
        "+919876543210", purpose="ip", settings=s
    )
    assert "9876543210" not in keyed_hash("+919876543210", purpose="phone", settings=s)


def _request(peer: str, xff: str | None = None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_client_ip_trusts_forwarded_header_only_from_trusted_proxy() -> None:
    s = Settings(_env_file=None, trusted_proxy_ips="127.0.0.1")
    assert client_ip(_request("127.0.0.1", "203.0.113.9"), s) == "203.0.113.9"
    assert client_ip(_request("198.51.100.4", "203.0.113.9"), s) == "198.51.100.4"  # spoof ignored
    assert client_ip(_request("127.0.0.1", "garbage, 203.0.113.9"), s) == "203.0.113.9"
    assert client_ip(_request("127.0.0.1"), s) == "127.0.0.1"


def test_role_permission_matrix() -> None:
    assert all(has_permission("owner", p) for p in Permission)
    assert has_permission("admin", Permission.SHOP_UPDATE)
    assert not has_permission("admin", Permission.AUDIT_VIEW)
    assert not has_permission("staff", Permission.MEMBERS_VIEW)
    assert can_manage_member("admin", "staff") and not can_manage_member("admin", "admin")
    assert can_manage_member("owner", "owner")
    assert not can_manage_member("staff", "staff")
    assert not has_permission("unknown-role", Permission.SHOP_VIEW)
