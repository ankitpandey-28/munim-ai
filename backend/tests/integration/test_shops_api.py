"""Shop management, roles, membership lifecycle and cross-tenant isolation via the API."""

import os

from tests.integration.conftest import STRONG_PASSWORD, create_shop, next_phone, register

SHOPS = "/api/v1/shops"
MEMBERS = "/api/v1/shops/current/members"


def _key() -> dict:
    return {"Idempotency-Key": os.urandom(12).hex()}


def _add_member(client, phone, role="staff", name="Helper", temp=STRONG_PASSWORD + "x"):
    body = {"phone": phone, "role": role, "name": name, "temporary_password": temp}
    return client.post(MEMBERS, json=body, headers=_key())


def _login(client, phone, password):
    return client.post("/api/v1/auth/login", json={"phone": phone, "password": password})


def _member_client(make_client, owner, role):
    """Create a member with `role` in owner's shop and return a logged-in client for them."""
    phone = next_phone()
    temp = "Temp-Pass-" + os.urandom(4).hex()
    assert _add_member(owner["client"], phone, role=role, temp=temp).status_code == 201
    client = make_client()
    assert _login(client, phone, temp).status_code == 200
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={"current_password": temp, "new_password": "Member-New-Pass-42"},
        ).status_code
        == 200
    )
    return client, phone


# ----------------------------------------------------------------------------- shops
def test_create_and_get_current_shop(make_client) -> None:
    client = make_client()
    register(client)
    assert client.get(f"{SHOPS}/current").json()["error"]["code"] == "NO_ACTIVE_SHOP"
    created = create_shop(client, "Gupta General Store")
    assert created["role"] == "owner"
    current = client.get(f"{SHOPS}/current").json()
    assert current["shop"]["name"] == "Gupta General Store"
    assert current["shop"]["timezone"] == "Asia/Kolkata"
    me = client.get("/api/v1/auth/me").json()
    assert me["active_shop_id"] == created["shop"]["id"]
    assert me["memberships"][0]["role"] == "owner"


def test_shop_creation_requires_idempotency_key(make_client) -> None:
    client = make_client()
    register(client)
    response = client.post(SHOPS, json={"name": "No Key Store"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_update_shop_with_optimistic_concurrency(owner) -> None:
    client = owner["client"]
    shop = client.get(f"{SHOPS}/current").json()["shop"]
    ok = client.patch(
        f"{SHOPS}/current", json={"version": shop["version"], "city": "Amritsar"}, headers=_key()
    )
    assert ok.status_code == 200 and ok.json()["city"] == "Amritsar"
    assert ok.json()["version"] == shop["version"] + 1
    stale = client.patch(
        f"{SHOPS}/current", json={"version": shop["version"], "city": "Delhi"}, headers=_key()
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_shop_input_validation(owner) -> None:
    client = owner["client"]
    bad = client.patch(f"{SHOPS}/current", json={"version": 1, "pincode": "12"}, headers=_key())
    assert bad.status_code == 422
    unknown_field = client.patch(
        f"{SHOPS}/current", json={"version": 1, "shop_id": "x"}, headers=_key()
    )
    assert unknown_field.status_code == 422  # shop context never comes from the body


# ----------------------------------------------------------------------------- members
def test_add_new_member_creates_account_requiring_password_change(owner, make_client) -> None:
    phone = next_phone()
    temp = "Temp-Pass-" + os.urandom(4).hex()
    added = _add_member(owner["client"], phone, temp=temp)
    assert added.status_code == 201
    body = added.json()
    assert body["account_created"] is True
    assert body["member"]["role"] == "staff"
    assert body["member"]["phone_masked"].endswith(phone[-4:]) and phone not in added.text
    member = make_client()
    assert _login(member, phone, temp).status_code == 200
    blocked = member.get(f"{SHOPS}/current")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert member.get("/api/v1/auth/me").json()["user"]["must_change_password"] is True
    member.post(
        "/api/v1/auth/change-password",
        json={"current_password": temp, "new_password": "Member-New-Pass-42"},
    )
    assert member.get(f"{SHOPS}/current").json()["role"] == "staff"


def test_add_existing_user_as_member(owner, make_client) -> None:
    other = register(make_client())
    added = owner["client"].post(
        MEMBERS, json={"phone": other["phone"], "role": "admin"}, headers=_key()
    )
    assert added.status_code == 201
    assert added.json()["account_created"] is False
    duplicate = owner["client"].post(MEMBERS, json={"phone": other["phone"]}, headers=_key())
    assert duplicate.status_code == 409


def test_new_account_requires_name_and_temporary_password(owner) -> None:
    response = owner["client"].post(MEMBERS, json={"phone": next_phone()}, headers=_key())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACCOUNT_DETAILS_REQUIRED"


def test_list_members_paginated(owner) -> None:
    for _ in range(3):
        assert _add_member(owner["client"], next_phone()).status_code == 201
    page = owner["client"].get(MEMBERS, params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    rest = owner["client"].get(MEMBERS, params={"limit": 2, "offset": 2}).json()
    assert len(rest["items"]) == 2
    assert {m["id"] for m in page["items"]}.isdisjoint({m["id"] for m in rest["items"]})
    assert owner["client"].get(MEMBERS, params={"limit": 101}).status_code == 422


def test_role_permissions(owner, make_client) -> None:
    admin, _ = _member_client(make_client, owner, "admin")
    staff, _ = _member_client(make_client, owner, "staff")
    # staff: can view the shop, cannot manage members or edit the shop
    assert staff.get(f"{SHOPS}/current").status_code == 200
    assert staff.get(MEMBERS).status_code == 403
    assert _add_member(staff, next_phone()).status_code == 403
    version = staff.get(f"{SHOPS}/current").json()["shop"]["version"]
    assert (
        staff.patch(
            f"{SHOPS}/current", json={"version": version, "city": "X"}, headers=_key()
        ).status_code
        == 403
    )
    # admin: can edit shop and add staff, cannot add admins/owners, change roles, or see audit
    assert (
        admin.patch(
            f"{SHOPS}/current", json={"version": version, "city": "Jalandhar"}, headers=_key()
        ).status_code
        == 200
    )
    assert _add_member(admin, next_phone(), role="staff").status_code == 201
    assert _add_member(admin, next_phone(), role="admin").status_code == 403
    assert _add_member(admin, next_phone(), role="owner").status_code == 403
    assert admin.get(f"{SHOPS}/current/audit-logs").status_code == 403
    staff_member = next(m for m in admin.get(MEMBERS).json()["items"] if m["role"] == "staff")
    assert admin.patch(f"{MEMBERS}/{staff_member['id']}", json={"role": "admin"}).status_code == 403
    # owner: audit trail available and records these actions
    audit = owner["client"].get(f"{SHOPS}/current/audit-logs").json()["items"]
    actions = {a["action"] for a in audit}
    assert {"shop.created", "member.added", "shop.updated"} <= actions


def test_last_owner_cannot_be_demoted_or_removed(owner) -> None:
    client = owner["client"]
    me = next(m for m in client.get(MEMBERS).json()["items"] if m["role"] == "owner")
    demote = client.patch(f"{MEMBERS}/{me['id']}", json={"role": "staff"})
    assert demote.status_code == 409 and demote.json()["error"]["code"] == "LAST_OWNER"
    remove = client.post(f"{MEMBERS}/{me['id']}/deactivate")
    assert remove.status_code == 409 and remove.json()["error"]["code"] == "LAST_OWNER"


def test_ownership_transfer_then_step_down(owner, make_client) -> None:
    second, _ = _member_client(make_client, owner, "staff")
    members = owner["client"].get(MEMBERS).json()["items"]
    me = next(m for m in members if m["role"] == "owner")
    other = next(m for m in members if m["role"] == "staff")
    assert (
        owner["client"].patch(f"{MEMBERS}/{other['id']}", json={"role": "owner"}).status_code == 200
    )
    assert owner["client"].patch(f"{MEMBERS}/{me['id']}", json={"role": "admin"}).status_code == 200
    assert second.get(f"{SHOPS}/current").json()["role"] == "owner"


def test_deactivated_member_loses_access_immediately(owner, make_client) -> None:
    staff, _ = _member_client(make_client, owner, "staff")
    assert staff.get(f"{SHOPS}/current").status_code == 200
    member = next(m for m in owner["client"].get(MEMBERS).json()["items"] if m["role"] == "staff")
    response = owner["client"].post(f"{MEMBERS}/{member['id']}/deactivate")
    assert response.status_code == 200 and response.json()["status"] == "removed"
    denied = staff.get(f"{SHOPS}/current")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "NO_ACTIVE_SHOP"
    assert staff.get(f"{SHOPS}/mine").json()["items"] == []


def test_member_can_leave_shop(owner, make_client) -> None:
    staff, _ = _member_client(make_client, owner, "staff")
    own_id = next(m for m in owner["client"].get(MEMBERS).json()["items"] if m["role"] == "staff")[
        "id"
    ]
    assert staff.post(f"{MEMBERS}/{own_id}/deactivate").status_code == 200


# ----------------------------------------------------------------------------- multi-shop
def test_switch_between_own_shops(make_client) -> None:
    client = make_client()
    register(client)
    first = create_shop(client, "Shop One")["shop"]["id"]
    second = create_shop(client, "Shop Two")["shop"]["id"]
    mine = client.get(f"{SHOPS}/mine").json()["items"]
    assert {s["shop_id"] for s in mine} == {first, second}
    assert next(s for s in mine if s["is_active"])["shop_id"] == second
    switched = client.post("/api/v1/session/active-shop", json={"shop_id": first})
    assert switched.status_code == 200
    assert client.get(f"{SHOPS}/current").json()["shop"]["id"] == first


def test_cannot_switch_into_or_read_another_users_shop(owner, make_client) -> None:
    intruder = make_client()
    register(intruder)
    intruder_shop = create_shop(intruder, "Intruder Shop")["shop"]["id"]
    # Switching to a shop without membership looks exactly like a non-existent shop.
    response = intruder.post("/api/v1/session/active-shop", json={"shop_id": owner["shop_id"]})
    assert response.status_code == 404
    # The intruder's view never includes the victim's shop or members.
    assert intruder.get(f"{SHOPS}/current").json()["shop"]["id"] == intruder_shop
    assert all(
        s["shop_id"] != owner["shop_id"] for s in intruder.get(f"{SHOPS}/mine").json()["items"]
    )
    names = [m["name"] for m in intruder.get(MEMBERS).json()["items"]]
    assert names == ["Ramesh Kumar"]  # only the intruder themself
    # A member id from the victim's shop cannot be modified from the intruder's shop.
    victim_member = owner["client"].get(MEMBERS).json()["items"][0]["id"]
    assert intruder.post(f"{MEMBERS}/{victim_member}/deactivate").status_code == 404


def test_login_restores_last_active_shop(make_client) -> None:
    client = make_client()
    user = register(client)
    first = create_shop(client, "Morning Shop")["shop"]["id"]
    create_shop(client, "Evening Shop")
    client.post("/api/v1/session/active-shop", json={"shop_id": first})
    fresh = make_client()
    response = fresh.post(
        "/api/v1/auth/login", json={"phone": user["phone"], "password": STRONG_PASSWORD}
    )
    assert response.json()["active_shop_id"] == first
