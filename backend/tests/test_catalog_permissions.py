"""Catalogue permissions (Phase 3) and preservation of pre-existing permissions."""

import pytest

from app.modules.shops.permissions import ROLE_PERMISSIONS, Permission, has_permission

CATALOG = {
    Permission.CATALOG_VIEW,
    Permission.CATALOG_VIEW_COSTS,
    Permission.CATALOG_MANAGE,
    Permission.CATALOG_MANAGE_PRICES,
}

# Permissions exactly as they were before Phase 3 (must not change).
PRE_PHASE_3 = {
    "owner": {
        Permission.SHOP_VIEW,
        Permission.SHOP_UPDATE,
        Permission.MEMBERS_VIEW,
        Permission.MEMBERS_MANAGE_STAFF,
        Permission.MEMBERS_MANAGE_PRIVILEGED,
        Permission.AUDIT_VIEW,
    },
    "admin": {
        Permission.SHOP_VIEW,
        Permission.SHOP_UPDATE,
        Permission.MEMBERS_VIEW,
        Permission.MEMBERS_MANAGE_STAFF,
    },
    "staff": {Permission.SHOP_VIEW},
}


def test_catalog_permission_values() -> None:
    assert {p.value for p in CATALOG} == {
        "catalog.view",
        "catalog.view_costs",
        "catalog.manage",
        "catalog.manage_prices",
    }


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_have_full_catalog_access(role: str) -> None:
    assert all(has_permission(role, p) for p in CATALOG)


def test_staff_can_only_view_catalog() -> None:
    assert has_permission("staff", Permission.CATALOG_VIEW)
    assert not has_permission("staff", Permission.CATALOG_VIEW_COSTS)
    assert not has_permission("staff", Permission.CATALOG_MANAGE)
    assert not has_permission("staff", Permission.CATALOG_MANAGE_PRICES)


@pytest.mark.parametrize("role", ["owner", "admin", "staff"])
def test_pre_existing_permissions_unchanged(role: str) -> None:
    non_catalog = {p for p in ROLE_PERMISSIONS[role] if p not in CATALOG}
    assert non_catalog == PRE_PHASE_3[role]


def test_unknown_role_has_no_catalog_access() -> None:
    assert not any(has_permission("viewer", p) for p in CATALOG)
