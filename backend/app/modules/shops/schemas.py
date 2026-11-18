import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import InvalidPhoneNumber, normalize_indian_mobile

Language = Literal["hi", "hinglish", "en", "pa"]
Role = Literal["owner", "admin", "staff"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check_timezone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("unknown timezone") from None
    return value


class ShopCreate(_Strict):
    name: str = Field(min_length=1, max_length=120)
    business_type: str = Field(default="kirana", min_length=1, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    pincode: str | None = Field(default=None, pattern=r"^[1-9][0-9]{5}$")
    timezone: str = Field(default="Asia/Kolkata", max_length=64)
    default_language: Language = "hinglish"

    _tz = field_validator("timezone")(_check_timezone)


class ShopUpdate(_Strict):
    """Partial update with optimistic concurrency: ``version`` must match the current row."""

    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    business_type: str | None = Field(default=None, min_length=1, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    pincode: str | None = Field(default=None, pattern=r"^[1-9][0-9]{5}$")
    timezone: str | None = Field(default=None, max_length=64)
    default_language: Language | None = None

    _tz = field_validator("timezone")(_check_timezone)


class ShopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    business_type: str
    address: str | None
    city: str | None
    state: str | None
    pincode: str | None
    timezone: str
    default_language: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class CurrentShopOut(BaseModel):
    shop: ShopOut
    role: Role


class MyShopOut(BaseModel):
    shop_id: uuid.UUID
    name: str
    role: Role
    is_active: bool


class MyShopList(BaseModel):
    items: list[MyShopOut]


class SwitchShopRequest(_Strict):
    shop_id: uuid.UUID


class MemberAdd(_Strict):
    phone: str = Field(min_length=10, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Role = "staff"
    # Required only when the phone is not registered yet: the new user must change it on
    # first login (must_change_password).
    temporary_password: str | None = Field(default=None, max_length=256, repr=False)
    credit_limit_paise: int | None = Field(default=None, ge=0)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        try:
            return normalize_indian_mobile(value)
        except InvalidPhoneNumber as exc:
            raise ValueError(str(exc)) from None


class MemberUpdate(_Strict):
    role: Role | None = None
    credit_limit_paise: int | None = Field(default=None, ge=0)


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    phone_masked: str
    role: Role
    status: str
    credit_limit_paise: int | None
    joined_at: datetime
    removed_at: datetime | None


class MemberAdded(BaseModel):
    member: MemberOut
    account_created: bool


class MemberPage(BaseModel):
    items: list[MemberOut]
    total: int
    limit: int
    offset: int


class AuditEntryOut(BaseModel):
    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    entity_type: str | None
    entity_id: uuid.UUID | None
    before: dict | None
    after: dict | None
    request_id: str | None
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEntryOut]
    limit: int
    offset: int
