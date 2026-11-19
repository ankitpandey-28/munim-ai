"""Shop roles and permissions (SRS §3, extended with 'admin' in Phase 2).

Decision recorded in docs/phase-2-implementation.md (needs product confirmation):
'admin' is a trusted manager who can edit shop details and manage *staff*, but can never add,
promote, demote or remove owners/admins, and cannot view the audit trail. Owners can do
everything. Business-module permissions (sales, udhaar, stock...) arrive with Phase 3.

Catalogue permissions (Phase 3, approved 2026-11-19): owners and admins have full catalogue
access including cost visibility and price management; staff may only view products,
categories, aliases and selling prices (never cost prices or cost history).

Inventory permissions (Phase 4, D-10/D-12e): owners and admins do everything; staff may view
quantities and movement history and record goods received, but never see costs or stock value,
and cannot post opening stock, adjustments, counts or reversals.
"""

from enum import StrEnum


class Permission(StrEnum):
    SHOP_VIEW = "shop.view"
    SHOP_UPDATE = "shop.update"
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE_STAFF = "members.manage_staff"
    MEMBERS_MANAGE_PRIVILEGED = "members.manage_privileged"  # owners/admins, role changes
    AUDIT_VIEW = "audit.view"
    # Catalogue (Phase 3)
    CATALOG_VIEW = "catalog.view"  # units, categories, products, aliases, selling prices
    CATALOG_VIEW_COSTS = "catalog.view_costs"  # default cost price + cost price history
    CATALOG_MANAGE = "catalog.manage"  # create/edit/archive categories & products, aliases
    CATALOG_MANAGE_PRICES = "catalog.manage_prices"  # selling/cost price changes (+ history)
    # Inventory (Phase 4; D-10, D-12e, SRS §3.2)
    INVENTORY_VIEW = "inventory.view"  # quantities, low stock, movement history (no costs)
    INVENTORY_VIEW_VALUE = "inventory.view_value"  # average cost, movement costs, stock value
    INVENTORY_RECEIVE = "inventory.receive"  # record goods received (SRS: staff allowed)
    INVENTORY_ADJUST = "inventory.adjust"  # opening stock, adjustments, counts, reversals


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "owner": frozenset(Permission),
    "admin": frozenset(
        {
            Permission.SHOP_VIEW,
            Permission.SHOP_UPDATE,
            Permission.MEMBERS_VIEW,
            Permission.MEMBERS_MANAGE_STAFF,
            Permission.CATALOG_VIEW,
            Permission.CATALOG_VIEW_COSTS,
            Permission.CATALOG_MANAGE,
            Permission.CATALOG_MANAGE_PRICES,
            Permission.INVENTORY_VIEW,
            Permission.INVENTORY_VIEW_VALUE,
            Permission.INVENTORY_RECEIVE,
            Permission.INVENTORY_ADJUST,
        }
    ),
    "staff": frozenset(
        {
            Permission.SHOP_VIEW,
            Permission.CATALOG_VIEW,
            Permission.INVENTORY_VIEW,
            Permission.INVENTORY_RECEIVE,
        }
    ),
}


def has_permission(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def can_manage_member(actor_role: str, target_role: str) -> bool:
    """Whether actor may add/deactivate a member holding (or receiving) target_role."""
    if has_permission(actor_role, Permission.MEMBERS_MANAGE_PRIVILEGED):
        return True
    return target_role == "staff" and has_permission(actor_role, Permission.MEMBERS_MANAGE_STAFF)
