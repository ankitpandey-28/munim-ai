"""Authentication: registration, login with lockout/rate limiting, server-side sessions,
logout, password change. All database work for a request happens in one transaction; the
caller commits.

Security notes:
- Passwords: Argon2id (app.core.security). Never logged, never returned, never stored plain.
- Sessions: 256-bit random token in an httpOnly cookie; only SHA-256(token) is stored. A new
  token is issued on every login and password change (prevents session fixation), and any
  session presented with the login request is revoked.
- Enumeration: unknown phone and wrong password produce the same error and the same Argon2
  cost; locked accounts and IP throttling share one 429 response.
"""

import logging
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import NoReturn

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    AuthenticationRequired,
    Conflict,
    InvalidCredentials,
    InvalidInput,
    NotFound,
    RateLimited,
)
from app.core.security import (
    InvalidPhoneNumber,
    hash_password,
    hash_session_token,
    keyed_hash,
    needs_rehash,
    new_session_token,
    normalize_indian_mobile,
    password_problems,
    verify_password,
)
from app.database.session import set_tenant_context
from app.modules.audit import service as audit
from app.modules.identity.models import AuthSession, LoginAttempt, User
from app.modules.shops.models import Shop, ShopMember

logger = logging.getLogger(__name__)

GENERIC_LOGIN_ERROR = "Phone number or password is incorrect."
THROTTLED_ERROR = "Too many attempts. Please wait a few minutes and try again."
IP_WINDOW = timedelta(minutes=10)
TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass
class IssuedSession:
    session: AuthSession
    token: str  # plaintext token: goes only into the Set-Cookie header, never logged/stored


@dataclass
class AuthContext:
    user: User
    session: AuthSession


# ----------------------------------------------------------------------------- helpers
def _now() -> datetime:
    return datetime.now(UTC)


def password_policy_error(problems: list[str]) -> InvalidInput:
    messages = {
        "too_short": "Password must be at least 8 characters.",
        "too_long": "Password must be at most 128 characters.",
        "too_common": "This password is too common. Choose another.",
        "too_repetitive": "Password is too repetitive.",
        "same_as_phone": "Password must not be your phone number.",
    }
    return InvalidInput(
        " ".join(messages[p] for p in problems),
        code="WEAK_PASSWORD",
        details=[{"loc": ["body", "password"], "type": p} for p in problems],
    )


class _SlidingWindowLimiter:
    """In-process limiter for registration (single API instance in the pilot; documented)."""

    def __init__(self) -> None:
        self._events: dict[str, deque[datetime]] = {}
        self._lock = Lock()

    def allow(self, key: str, limit: int, window: timedelta) -> bool:
        now = _now()
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


registration_limiter = _SlidingWindowLimiter()


def _issue_session(
    db: Session, user: User, settings: Settings, *, user_agent: str | None, ip_hash: str | None
) -> IssuedSession:
    # Own memberships are visible to the user only through RLS ('own memberships' policy).
    set_tenant_context(db, user_id=user.id, shop_id=None)
    token = new_session_token()
    now = _now()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        active_shop_id=_default_active_shop(db, user),
        user_agent=(user_agent or "")[:256] or None,
        ip_hash=ip_hash,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_ttl_hours),
    )
    db.add(session)
    db.flush()
    return IssuedSession(session=session, token=token)


def _default_active_shop(db: Session, user: User) -> uuid.UUID | None:
    """Last active shop if the membership is still active, else the oldest active membership.
    Membership rows are visible through the 'own memberships' RLS policy."""
    rows = (
        db.execute(
            select(ShopMember.shop_id)
            .join(Shop, Shop.id == ShopMember.shop_id)
            .where(
                ShopMember.user_id == user.id,
                ShopMember.status == "active",
                Shop.status == "active",
            )
            .order_by(ShopMember.joined_at)
        )
        .scalars()
        .all()
    )
    if user.last_active_shop_id in rows:
        return user.last_active_shop_id
    return rows[0] if rows else None


def _record_attempt(db: Session, phone_hash: str, ip_hash: str | None, failure: str | None) -> None:
    db.add(
        LoginAttempt(
            phone_hash=phone_hash,
            ip_hash=ip_hash,
            succeeded=failure is None,
            failure_reason=failure,
        )
    )


# ----------------------------------------------------------------------------- registration
def register(
    db: Session,
    settings: Settings,
    *,
    phone: str,
    name: str,
    password: str,
    preferred_language: str,
    ip: str | None,
    user_agent: str | None,
) -> tuple[User, IssuedSession]:
    ip_key = keyed_hash(ip or "unknown", purpose="register-ip", settings=settings)
    if not registration_limiter.allow(
        ip_key, settings.registration_ip_max_per_hour, timedelta(hours=1)
    ):
        raise RateLimited(THROTTLED_ERROR)
    problems = password_problems(password, phone=phone)
    if problems:
        raise password_policy_error(problems)
    if db.execute(select(User.id).where(User.phone == phone)).first() is not None:
        raise Conflict(
            "An account with this phone number already exists. Please log in.",
            code="PHONE_ALREADY_REGISTERED",
        )
    user = User(
        phone=phone,
        name=name.strip(),
        preferred_language=preferred_language,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.flush()
    ip_hash = keyed_hash(ip, purpose="ip", settings=settings) if ip else None
    issued = _issue_session(db, user, settings, user_agent=user_agent, ip_hash=ip_hash)
    audit.record(
        db,
        action="auth.registered",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_hash=ip_hash,
        after={"preferred_language": preferred_language},
    )
    return user, issued


# ----------------------------------------------------------------------------- login
def login(
    db: Session,
    settings: Settings,
    *,
    raw_phone: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
    presented_token: str | None,
) -> tuple[User, IssuedSession]:
    """Authenticate and issue a NEW session. Failures commit their attempt record themselves
    (so lockout counting survives the error response)."""
    now = _now()
    ip_hash = keyed_hash(ip, purpose="ip", settings=settings) if ip else None
    try:
        phone = normalize_indian_mobile(raw_phone)
    except InvalidPhoneNumber:
        phone = raw_phone.strip()  # still rate-limited and recorded, never matches a user
    phone_hash = keyed_hash(phone, purpose="phone", settings=settings)

    def fail(reason: str, error: Exception) -> NoReturn:
        _record_attempt(db, phone_hash, ip_hash, reason)
        db.commit()
        raise error

    if ip_hash is not None:
        recent_ip_failures = db.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.ip_hash == ip_hash,
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.attempted_at > now - IP_WINDOW,
            )
        ).scalar_one()
        if recent_ip_failures >= settings.login_ip_max_attempts:
            fail("rate_limited", RateLimited(THROTTLED_ERROR))

    user = db.execute(
        select(User).where(User.phone == phone).with_for_update()
    ).scalar_one_or_none()
    if user is None:
        verify_password(password, None)  # equalise timing with the known-user path
        fail("bad_credentials", InvalidCredentials(GENERIC_LOGIN_ERROR))
    if user.locked_until is not None and user.locked_until > now:
        verify_password(password, None)
        fail("locked", RateLimited(THROTTLED_ERROR))
    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_count = 0
            audit.record(
                db,
                action="auth.account_locked",
                actor_user_id=None,
                entity_type="user",
                entity_id=user.id,
                ip_hash=ip_hash,
                actor_type="anonymous",
                after={"locked_minutes": settings.login_lockout_minutes},
            )
        fail("bad_credentials", InvalidCredentials(GENERIC_LOGIN_ERROR))
    if user.status != "active":
        fail("disabled", InvalidCredentials(GENERIC_LOGIN_ERROR))

    # Success.
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    if presented_token:
        _revoke_by_token(db, presented_token, reason="replaced_by_login")
    issued = _issue_session(db, user, settings, user_agent=user_agent, ip_hash=ip_hash)
    _record_attempt(db, phone_hash, ip_hash, None)
    audit.record(
        db,
        action="auth.login_succeeded",
        actor_user_id=user.id,
        entity_type="auth_session",
        entity_id=issued.session.id,
        ip_hash=ip_hash,
    )
    return user, issued


# ----------------------------------------------------------------------------- sessions
def authenticate_token(db: Session, settings: Settings, token: str | None) -> AuthContext:
    """Resolve a session cookie to an active user. Raises AuthenticationRequired otherwise."""
    if not token or len(token) > 128:
        raise AuthenticationRequired("Please log in.")
    now = _now()
    row = db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.token_hash == hash_session_token(token))
    ).first()
    if row is None:
        raise AuthenticationRequired("Please log in.")
    session, user = row
    idle_limit = session.last_seen_at + timedelta(hours=settings.session_idle_ttl_hours)
    if session.revoked_at is not None or session.expires_at <= now or idle_limit <= now:
        raise AuthenticationRequired("Your session has expired. Please log in again.")
    if user.status != "active":
        raise AuthenticationRequired("Please log in.")
    if now - session.last_seen_at > TOUCH_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return AuthContext(user=user, session=session)


def _revoke_by_token(db: Session, token: str, *, reason: str) -> None:
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.token_hash == hash_session_token(token), AuthSession.revoked_at.is_(None)
        )
        .values(revoked_at=_now(), revoke_reason=reason)
    )


def logout(db: Session, ctx: AuthContext) -> None:
    ctx.session.revoked_at = _now()
    ctx.session.revoke_reason = "logout"
    audit.record(
        db,
        action="auth.logout",
        actor_user_id=ctx.user.id,
        entity_type="auth_session",
        entity_id=ctx.session.id,
    )


def revoke_user_sessions(
    db: Session, user_id: uuid.UUID, *, reason: str, except_session_id: uuid.UUID | None = None
) -> int:
    stmt = update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if except_session_id is not None:
        stmt = stmt.where(AuthSession.id != except_session_id)
    return db.execute(stmt.values(revoked_at=_now(), revoke_reason=reason)).rowcount or 0


def logout_all(db: Session, ctx: AuthContext) -> int:
    count = revoke_user_sessions(db, ctx.user.id, reason="logout_all")
    audit.record(
        db,
        action="auth.logout_all",
        actor_user_id=ctx.user.id,
        entity_type="user",
        entity_id=ctx.user.id,
        after={"sessions_revoked": count},
    )
    return count


def revoke_session(db: Session, ctx: AuthContext, session_id: uuid.UUID) -> None:
    target = db.execute(
        select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == ctx.user.id)
    ).scalar_one_or_none()
    if target is None or target.revoked_at is not None:
        raise NotFound("Session not found.")
    target.revoked_at = _now()
    target.revoke_reason = "revoked_by_user"
    audit.record(
        db,
        action="auth.session_revoked",
        actor_user_id=ctx.user.id,
        entity_type="auth_session",
        entity_id=target.id,
    )


def list_sessions(db: Session, ctx: AuthContext) -> list[AuthSession]:
    now = _now()
    return list(
        db.execute(
            select(AuthSession)
            .where(
                AuthSession.user_id == ctx.user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .order_by(AuthSession.created_at.desc())
        ).scalars()
    )


def change_password(
    db: Session,
    settings: Settings,
    ctx: AuthContext,
    *,
    current_password: str,
    new_password: str,
    user_agent: str | None,
) -> IssuedSession:
    """Verify, replace the hash, revoke every session (including the current one) and issue a
    fresh session token for this client."""
    user = db.execute(select(User).where(User.id == ctx.user.id).with_for_update()).scalar_one()
    if not verify_password(current_password, user.password_hash):
        raise InvalidCredentials("Current password is incorrect.", code="INVALID_CURRENT_PASSWORD")
    problems = password_problems(new_password, phone=user.phone)
    if problems:
        raise password_policy_error(problems)
    if verify_password(new_password, user.password_hash):
        raise InvalidInput(
            "New password must be different from the current one.", code="PASSWORD_UNCHANGED"
        )
    user.password_hash = hash_password(new_password)
    user.password_changed_at = _now()
    user.must_change_password = False
    revoked = revoke_user_sessions(db, user.id, reason="password_changed")
    issued = _issue_session(db, user, settings, user_agent=user_agent, ip_hash=ctx.session.ip_hash)
    issued.session.active_shop_id = ctx.session.active_shop_id
    audit.record(
        db,
        action="auth.password_changed",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        after={"sessions_revoked": revoked},
    )
    return issued


def memberships_for(db: Session, user_id: uuid.UUID) -> list[tuple[ShopMember, Shop]]:
    return list(
        db.execute(
            select(ShopMember, Shop)
            .join(Shop, Shop.id == ShopMember.shop_id)
            .where(ShopMember.user_id == user_id, ShopMember.status == "active")
            .order_by(Shop.name)
        ).all()
    )
