"""Shop management: create/update shops, memberships, roles and shop switching.

Every function runs inside the caller's transaction; the API layer commits once.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import Conflict, InvalidInput, NotFound, PermissionDenied
from app.core.security import hash_password, mask_phone, password_problems
from app.database.session import set_tenant_context
from app.modules.audit import service as audit
from app.modules.audit.models import AuditLog
from app.modules.identity.models import AuthSession, User
from app.modules.identity.service import AuthContext, password_policy_error
from app.modules.shops.context import ShopContext
from app.modules.shops.models import Shop, ShopMember, ShopSettings
from app.modules.shops.permissions import Permission, can_manage_member, has_permission
from app.modules.shops.schemas import MemberAdd, MemberOut, MemberUpdate, ShopCreate, ShopUpdate
from app.shared.ids import uuid7

SHOP_FIELDS = (
    "name",
    "business_type",
    "address",
    "city",
    "state",
    "pincode",
    "timezone",
    "default_language",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _shop_snapshot(shop: Shop) -> dict:
    return {f: getattr(shop, f) for f in SHOP_FIELDS} | {"version": shop.version}


def member_out(member: ShopMember, user: User) -> MemberOut:
    return MemberOut(
        id=member.id,
        user_id=user.id,
        name=user.name,
        phone_masked=mask_phone(user.phone),
        role=member.role,
        status=member.status,
        credit_limit_paise=member.credit_limit_paise,
        joined_at=member.joined_at,
        removed_at=member.removed_at,
    )


# ----------------------------------------------------------------------------- shops
def create_shop(db: Session, auth: AuthContext, data: ShopCreate) -> tuple[Shop, ShopMember]:
    """Create a shop with the caller as its first owner and make it the active shop.

    The id is generated up front and set as the transaction's shop context *before* the
    INSERTs, so the rows satisfy RLS WITH CHECK (a shop can only be created as the active shop
    of the creating user).
    """
    shop_id = uuid7()
    set_tenant_context(db, user_id=auth.user.id, shop_id=shop_id)
    shop = Shop(id=shop_id, created_by_user_id=auth.user.id, **data.model_dump())
    db.add(shop)
    db.flush()
    db.add(ShopSettings(shop_id=shop_id, settings={}))
    member = ShopMember(shop_id=shop_id, user_id=auth.user.id, role="owner")
    db.add(member)
    auth.session.active_shop_id = shop_id
    auth.user.last_active_shop_id = shop_id
    db.flush()
    audit.record(
        db,
        action="shop.created",
        actor_user_id=auth.user.id,
        shop_id=shop_id,
        entity_type="shop",
        entity_id=shop_id,
        after=_shop_snapshot(shop),
    )
    return shop, member


def update_shop(db: Session, ctx: ShopContext, data: ShopUpdate) -> Shop:
    shop = db.execute(select(Shop).where(Shop.id == ctx.shop_id).with_for_update()).scalar_one()
    if shop.version != data.version:
        raise Conflict(
            "This shop was changed by someone else. Reload and try again.",
            code="VERSION_CONFLICT",
            details={"current_version": shop.version},
        )
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "name" in changes and changes["name"] is None:
        raise InvalidInput("Shop name cannot be empty.")
    before = _shop_snapshot(shop)
    for field, value in changes.items():
        setattr(shop, field, value)
    shop.version += 1
    db.flush()
    audit.record(
        db,
        action="shop.updated",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="shop",
        entity_id=shop.id,
        before=before,
        after=_shop_snapshot(shop),
    )
    return shop


def list_my_shops(db: Session, auth: AuthContext) -> list[tuple[Shop, ShopMember]]:
    return list(
        db.execute(
            select(Shop, ShopMember)
            .join(ShopMember, ShopMember.shop_id == Shop.id)
            .where(ShopMember.user_id == auth.user.id, ShopMember.status == "active")
            .order_by(Shop.name)
        ).all()
    )


def switch_shop(db: Session, auth: AuthContext, shop_id: uuid.UUID) -> tuple[Shop, ShopMember]:
    """Make ``shop_id`` the session's active shop. Requires an active membership; a shop the
    user does not belong to is reported exactly like a non-existent one."""
    row = db.execute(
        select(Shop, ShopMember)
        .join(ShopMember, ShopMember.shop_id == Shop.id)
        .where(
            Shop.id == shop_id,
            ShopMember.user_id == auth.user.id,
            ShopMember.status == "active",
            Shop.status == "active",
        )
    ).first()
    if row is None:
        raise NotFound("Shop not found.")
    shop, member = row
    previous = auth.session.active_shop_id
    auth.session.active_shop_id = shop.id
    auth.user.last_active_shop_id = shop.id
    set_tenant_context(db, user_id=auth.user.id, shop_id=shop.id)
    audit.record(
        db,
        action="session.shop_switched",
        actor_user_id=auth.user.id,
        shop_id=shop.id,
        entity_type="auth_session",
        entity_id=auth.session.id,
        before={"active_shop_id": previous},
        after={"active_shop_id": shop.id},
    )
    return shop, member


# ----------------------------------------------------------------------------- members
def list_members(
    db: Session, ctx: ShopContext, *, limit: int, offset: int, include_removed: bool
) -> tuple[list[MemberOut], int]:
    conditions = [ShopMember.shop_id == ctx.shop_id]
    if not include_removed:
        conditions.append(ShopMember.status == "active")
    total = db.execute(select(func.count()).select_from(ShopMember).where(*conditions)).scalar_one()
    rows = db.execute(
        select(ShopMember, User)
        .join(User, User.id == ShopMember.user_id)
        .where(*conditions)
        .order_by(ShopMember.joined_at, ShopMember.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [member_out(m, u) for m, u in rows], total


def add_member(db: Session, ctx: ShopContext, data: MemberAdd) -> tuple[ShopMember, User, bool]:
    if not can_manage_member(ctx.role, data.role):
        raise PermissionDenied("You cannot add a member with this role.")
    user = db.execute(select(User).where(User.phone == data.phone)).scalar_one_or_none()
    created = False
    if user is None:
        if not data.temporary_password or not data.name:
            raise InvalidInput(
                "This phone number has no account yet. Provide the person's name and a "
                "temporary password; they will be asked to change it on first login.",
                code="ACCOUNT_DETAILS_REQUIRED",
            )
        problems = password_problems(data.temporary_password, phone=data.phone)
        if problems:
            raise password_policy_error(problems)
        user = User(
            phone=data.phone,
            name=data.name,
            password_hash=hash_password(data.temporary_password),
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        created = True
    existing = db.execute(
        select(ShopMember).where(ShopMember.shop_id == ctx.shop_id, ShopMember.user_id == user.id)
    ).scalar_one_or_none()
    if existing is not None and existing.status == "active":
        raise Conflict("This person is already a member of the shop.", code="ALREADY_MEMBER")
    if existing is not None:  # re-activate a removed membership
        existing.status = "active"
        existing.removed_at = None
        existing.role = data.role
        existing.credit_limit_paise = data.credit_limit_paise
        member = existing
    else:
        member = ShopMember(
            shop_id=ctx.shop_id,
            user_id=user.id,
            role=data.role,
            credit_limit_paise=data.credit_limit_paise,
            invited_by_user_id=ctx.user_id,
        )
        db.add(member)
    db.flush()
    audit.record(
        db,
        action="member.added",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="shop_member",
        entity_id=member.id,
        after={"user_id": user.id, "role": member.role, "account_created": created},
    )
    return member, user, created


def _lock_active_owners(db: Session, shop_id: uuid.UUID) -> list[ShopMember]:
    return list(
        db.execute(
            select(ShopMember)
            .where(
                ShopMember.shop_id == shop_id,
                ShopMember.role == "owner",
                ShopMember.status == "active",
            )
            .order_by(ShopMember.id)
            .with_for_update()
        ).scalars()
    )


def _get_member(db: Session, ctx: ShopContext, member_id: uuid.UUID) -> tuple[ShopMember, User]:
    row = db.execute(
        select(ShopMember, User)
        .join(User, User.id == ShopMember.user_id)
        .where(ShopMember.id == member_id, ShopMember.shop_id == ctx.shop_id)
        .with_for_update(of=ShopMember)
    ).first()
    if row is None:
        raise NotFound("Member not found.")
    return row[0], row[1]


def update_member(
    db: Session, ctx: ShopContext, member_id: uuid.UUID, data: MemberUpdate
) -> tuple[ShopMember, User]:
    owners = _lock_active_owners(db, ctx.shop_id)
    member, user = _get_member(db, ctx, member_id)
    if member.status != "active":
        raise Conflict("This membership is not active.", code="MEMBER_NOT_ACTIVE")
    changes = data.model_dump(exclude_unset=True)
    before = {"role": member.role, "credit_limit_paise": member.credit_limit_paise}
    if "role" in changes and changes["role"] is not None and changes["role"] != member.role:
        if not has_permission(ctx.role, Permission.MEMBERS_MANAGE_PRIVILEGED):
            raise PermissionDenied("Only an owner can change member roles.")
        if member.role == "owner" and len(owners) <= 1:
            raise Conflict(
                "A shop must always have at least one owner. Make someone else an owner first.",
                code="LAST_OWNER",
            )
        member.role = changes["role"]
    if "credit_limit_paise" in changes:
        if not can_manage_member(ctx.role, member.role):
            raise PermissionDenied("You cannot change this member's limits.")
        member.credit_limit_paise = changes["credit_limit_paise"]
    db.flush()
    audit.record(
        db,
        action="member.updated",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="shop_member",
        entity_id=member.id,
        before=before,
        after={"role": member.role, "credit_limit_paise": member.credit_limit_paise},
    )
    return member, user


def deactivate_member(
    db: Session, ctx: ShopContext, member_id: uuid.UUID
) -> tuple[ShopMember, User]:
    owners = _lock_active_owners(db, ctx.shop_id)
    member, user = _get_member(db, ctx, member_id)
    if member.status != "active":
        raise Conflict("This membership is already inactive.", code="MEMBER_NOT_ACTIVE")
    is_self = member.user_id == ctx.user_id
    if not is_self and not can_manage_member(ctx.role, member.role):
        raise PermissionDenied("You cannot remove this member.")
    if member.role == "owner" and len(owners) <= 1:
        raise Conflict(
            "The last owner cannot be removed. Make someone else an owner first.",
            code="LAST_OWNER",
        )
    member.status = "removed"
    member.removed_at = _now()
    # Sessions pointing at this shop lose it immediately (access is also re-checked per request).
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == member.user_id, AuthSession.active_shop_id == ctx.shop_id)
        .values(active_shop_id=None)
    )
    db.flush()
    audit.record(
        db,
        action="member.deactivated",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="shop_member",
        entity_id=member.id,
        before={"status": "active", "role": member.role},
        after={"status": "removed"},
    )
    return member, user


def list_audit(db: Session, ctx: ShopContext, *, limit: int, offset: int) -> list[AuditLog]:
    return list(
        db.execute(
            select(AuditLog)
            .where(AuditLog.shop_id == ctx.shop_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
