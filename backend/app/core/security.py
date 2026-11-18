"""Security primitives: password hashing, password policy, session tokens, keyed hashing,
phone normalisation and client-IP resolution. Nothing here logs or returns secrets."""

import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
import unicodedata
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from starlette.requests import Request

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- passwords
# argon2-cffi defaults = RFC 9106 "low memory" profile: Argon2id, t=3, m=64 MiB, p=4.
_hasher = PasswordHasher()
# Verified when the phone number is unknown, so both paths cost the same (no user enumeration
# through response timing).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
_COMMON_PASSWORDS = frozenset(
    [
        "password",
        "password1",
        "password123",
        "passw0rd",
        "12345678",
        "123456789",
        "1234567890",
        "11111111",
        "00000000",
        "12341234",
        "87654321",
        "qwerty123",
        "qwertyuiop",
        "iloveyou",
        "admin123",
        "welcome1",
        "welcome123",
        "abc12345",
        "abcd1234",
        "letmein1",
        "sunshine",
        "monkey123",
        "football",
        "baseball",
        "princess",
        "dragon123",
        "india123",
        "bharat123",
        "hindustan",
        "krishna123",
        "ganesh123",
        "shree123",
        "jaishreeram",
        "jaimatadi",
        "sairam123",
        "kirana123",
        "dukaan123",
        "munim123",
        "munimai123",
        "changeme",
        "changeme123",
        "test1234",
        "testtest",
    ]
)


def normalize_password(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def password_problems(password: str, *, phone: str | None = None) -> list[str]:
    """Return policy violations (codes) for a candidate password. Empty list = acceptable."""
    pw = normalize_password(password)
    problems = []
    if len(pw) < MIN_PASSWORD_LENGTH:
        problems.append("too_short")
    if len(pw) > MAX_PASSWORD_LENGTH:
        problems.append("too_long")
    if pw.lower() in _COMMON_PASSWORDS:
        problems.append("too_common")
    if len(set(pw)) <= 2:
        problems.append("too_repetitive")
    if phone:
        digits = re.sub(r"\D", "", phone)
        if digits and (pw == digits or pw == digits[-10:]):
            problems.append("same_as_phone")
    return problems


def hash_password(password: str) -> str:
    return _hasher.hash(normalize_password(password))


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-cost verification; an unknown user (hash None) verifies against a dummy hash."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, normalize_password(password)) and (
            password_hash is not None
        )
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ----------------------------------------------------------------------------- session tokens
def new_session_token() -> str:
    """256-bit random token for the session cookie. Only its SHA-256 digest is stored."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


# ----------------------------------------------------------------------------- keyed hashing
@lru_cache
def _ephemeral_key() -> bytes:
    logger.warning(
        "AUTH_SECRET_KEY is not set; using a random per-process key (development only). "
        "Login rate-limit history resets on restart."
    )
    return secrets.token_bytes(32)


def _hmac_key(settings: Settings) -> bytes:
    if settings.auth_secret_key is not None:
        return settings.auth_secret_key.get_secret_value().encode("utf-8")
    return _ephemeral_key()


def keyed_hash(value: str, *, purpose: str, settings: Settings | None = None) -> str:
    """HMAC-SHA256 hex digest, domain-separated by purpose. Used instead of raw phones/IPs."""
    settings = settings or get_settings()
    return hmac.new(_hmac_key(settings), f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


# ----------------------------------------------------------------------------- phone numbers
class InvalidPhoneNumber(ValueError):
    pass


def normalize_indian_mobile(raw: str) -> str:
    """Normalise an Indian mobile number to E.164 (+91XXXXXXXXXX).

    Accepts spaces, dashes, dots, brackets and the prefixes +91, 91, 0091 or 0.
    Valid Indian mobile numbers have 10 digits starting with 6-9.
    """
    if raw is None:
        raise InvalidPhoneNumber("phone number is required")
    digits = re.sub(r"[\s\-().]", "", raw.strip())
    if digits.startswith("+"):
        digits = digits[1:]
        if not digits.startswith("91"):
            raise InvalidPhoneNumber("only Indian (+91) mobile numbers are supported")
    if not digits.isdigit():
        raise InvalidPhoneNumber("phone number may contain digits only")
    if digits.startswith("0091"):
        digits = digits[4:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise InvalidPhoneNumber("enter a valid 10-digit Indian mobile number")
    return "+91" + digits


def mask_phone(phone: str) -> str:
    return phone[:3] + "******" + phone[-4:] if len(phone) >= 7 else "***"


# ----------------------------------------------------------------------------- client IP
def client_ip(request: Request, settings: Settings | None = None) -> str | None:
    """Direct peer address, or the right-most untrusted X-Forwarded-For hop when the peer is a
    trusted proxy (e.g. the Next.js server forwarding /api/v1/*)."""
    settings = settings or get_settings()
    peer = request.client.host if request.client else None
    if peer is None or peer not in settings.trusted_proxy_list:
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    for hop in reversed([h.strip() for h in forwarded.split(",") if h.strip()]):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            continue
        if hop not in settings.trusted_proxy_list:
            return hop
    return peer
