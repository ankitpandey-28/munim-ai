"""Authentication endpoints: /api/v1/auth/*"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import AuthAnyDep, DbSession, Meta, SettingsDep, get_session_token
from app.core.config import Settings
from app.modules.identity import service
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MembershipOut,
    MeResponse,
    PublicUser,
    RegisterRequest,
    SessionList,
    SessionOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_absolute_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


def build_me(db, user: User, active_shop_id: uuid.UUID | None) -> MeResponse:
    memberships = service.memberships_for(db, user.id)
    return MeResponse(
        user=PublicUser.model_validate(user, from_attributes=True),
        active_shop_id=active_shop_id,
        memberships=[
            MembershipOut(shop_id=shop.id, shop_name=shop.name, role=member.role)
            for member, shop in memberships
        ],
    )


def _session_response(
    db, settings: Settings, user: User, issued: service.IssuedSession, status_code: int
) -> JSONResponse:
    me = build_me(db, user, issued.session.active_shop_id)
    db.commit()
    response = JSONResponse(content=me.model_dump(mode="json"), status_code=status_code)
    set_session_cookie(response, settings, issued.token)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=MeResponse,
    summary="Register an owner account (phone + password) and start a session",
)
def register(body: RegisterRequest, db: DbSession, settings: SettingsDep, meta: Meta):
    user, issued = service.register(
        db,
        settings,
        phone=body.phone,
        name=body.name,
        password=body.password,
        preferred_language=body.preferred_language,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
    return _session_response(db, settings, user, issued, status.HTTP_201_CREATED)


@router.post("/login", response_model=MeResponse, summary="Log in with phone + password")
def login(
    body: LoginRequest,
    db: DbSession,
    settings: SettingsDep,
    meta: Meta,
    presented_token: Annotated[str | None, Depends(get_session_token)],
):
    """Always issues a brand-new session token (no session fixation); a session cookie sent
    with the login request is revoked."""
    user, issued = service.login(
        db,
        settings,
        raw_phone=body.phone,
        password=body.password,
        ip=meta.ip,
        user_agent=meta.user_agent,
        presented_token=presented_token,
    )
    return _session_response(db, settings, user, issued, status.HTTP_200_OK)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End this session")
def logout(db: DbSession, settings: SettingsDep, auth: AuthAnyDep) -> Response:
    service.logout(db, auth)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response


@router.post(
    "/logout-all", status_code=status.HTTP_204_NO_CONTENT, summary="End all of my sessions"
)
def logout_all(db: DbSession, settings: SettingsDep, auth: AuthAnyDep) -> Response:
    service.logout_all(db, auth)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response


@router.post(
    "/change-password",
    response_model=MeResponse,
    summary="Change password; revokes all sessions and issues a new one",
)
def change_password(
    body: ChangePasswordRequest, db: DbSession, settings: SettingsDep, auth: AuthAnyDep, meta: Meta
):
    issued = service.change_password(
        db,
        settings,
        auth,
        current_password=body.current_password,
        new_password=body.new_password,
        user_agent=meta.user_agent,
    )
    return _session_response(db, settings, auth.user, issued, status.HTTP_200_OK)


@router.get("/me", response_model=MeResponse, summary="Current user, memberships, active shop")
def me(db: DbSession, auth: AuthAnyDep) -> MeResponse:
    return build_me(db, auth.user, auth.session.active_shop_id)


@router.get("/sessions", response_model=SessionList, summary="My active sessions")
def sessions(db: DbSession, auth: AuthAnyDep) -> SessionList:
    return SessionList(
        items=[
            SessionOut(
                id=s.id,
                created_at=s.created_at,
                last_seen_at=s.last_seen_at,
                expires_at=s.expires_at,
                user_agent=s.user_agent,
                current=s.id == auth.session.id,
            )
            for s in service.list_sessions(db, auth)
        ]
    )


@router.delete(
    "/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a session"
)
def revoke_session(session_id: uuid.UUID, db: DbSession, auth: AuthAnyDep) -> Response:
    service.revoke_session(db, auth, session_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
