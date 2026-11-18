"""Request/response models for authentication. Responses never include password hashes,
session token hashes or other secrets."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import InvalidPhoneNumber, normalize_indian_mobile

Language = Literal["hi", "hinglish", "en", "pa"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _phone(value: str) -> str:
    try:
        return normalize_indian_mobile(value)
    except InvalidPhoneNumber as exc:
        raise ValueError(str(exc)) from None


class RegisterRequest(_Strict):
    phone: str = Field(min_length=10, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    # Length/policy is enforced in the service so the error can be specific and safe.
    password: str = Field(min_length=1, max_length=256, repr=False)
    preferred_language: Language = "hinglish"

    _normalize_phone = field_validator("phone")(_phone)


class LoginRequest(_Strict):
    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=256, repr=False)


class ChangePasswordRequest(_Strict):
    current_password: str = Field(min_length=1, max_length=256, repr=False)
    new_password: str = Field(min_length=1, max_length=256, repr=False)


class MembershipOut(BaseModel):
    shop_id: uuid.UUID
    shop_name: str
    role: str


class PublicUser(BaseModel):
    """The only user representation returned by the API."""

    id: uuid.UUID
    phone: str
    name: str
    preferred_language: str
    must_change_password: bool
    created_at: datetime


class MeResponse(BaseModel):
    user: PublicUser
    active_shop_id: uuid.UUID | None
    memberships: list[MembershipOut]


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str | None
    current: bool


class SessionList(BaseModel):
    items: list[SessionOut]
