"""Comprehensive catalogue API tests over real HTTP and real PostgreSQL 18 (disposable cluster).

Every request goes through FastAPI -> auth/session -> verified shop context -> permission
dependency -> service -> PostgreSQL with RLS, as the frontend would use it. Real owner, admin
and staff accounts are used (no role overrides, no mocked services).

Database-level assertions (row counts, partial-write checks) use the disposable cluster's
throwaway superuser, read-only, so they can see rows across shops regardless of RLS. Nothing
here connects to the developer's real database.
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.integration.conftest import create_shop, next_phone, register

CAT = "/api/v1/catalog"
SECRET_COST = 73919  # distinctive values: must never appear in a staff response
SECRET_COST_2 = 81737


# ----------------------------------------------------------------------------- helpers
def _key() -> dict:
    return {"Idempotency-Key": os.urandom(12).hex()}


def _member(make_client, owner_client: TestClient, role: str) -> TestClient:
    """Create a real member account via the API and return a logged-in client for it."""
    phone, temp = next_phone(), "Temp-Pass-" + os.urandom(4).hex()
    added = owner_client.post(
        "/api/v1/shops/current/members",
        json={
            "phone": phone,
            "name": f"{role.title()} Person",
            "role": role,
            "temporary_password": temp,
        },
        headers=_key(),
    )
    assert added.status_code == 201, added.text
    client = make_client()
    assert (
        client.post("/api/v1/auth/login", json={"phone": phone, "password": temp}).status_code
        == 200
    )
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": temp, "new_password": "Member-New-Pass-42"},
    )
    assert changed.status_code == 200
    return client


def cat(c: TestClient, name: str, **extra) -> dict:
    r = c.post(f"{CAT}/categories", json={"name": name, **extra}, headers=_key())
    assert r.status_code == 201, r.text
    return r.json()


def prod(c: TestClient, name: str, **extra) -> dict:
    body = {"name": name, "base_unit_code": "kg", "selling_price_paise": 4400} | extra
    r = c.post(f"{CAT}/products", json=body, headers=_key())
    assert r.status_code == 201, r.text
    return r.json()


def err(response) -> str:
    return response.json()["error"]["code"]


def count(engine, sql: str, **params) -> int:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


@pytest.fixture
def world(owner, make_client):
    """Shop A: owner + admin + staff. Shop B: separate owner + staff."""
    a_owner = owner["client"]
    b_owner = make_client()
    register(b_owner, name="Other Owner")
    b_shop = create_shop(b_owner, "Other Store")["shop"]["id"]
    return SimpleNamespace(
        a_shop=owner["shop_id"],
        a_owner=a_owner,
        a_admin=_member(make_client, a_owner, "admin"),
        a_staff=_member(make_client, a_owner, "staff"),
        b_shop=b_shop,
        b_owner=b_owner,
        b_staff=_member(make_client, b_owner, "staff"),
    )


# ============================================================================ 1. roles / auth
def test_role_access_matrix_over_http(world) -> None:
    """Owner and admin can do everything; staff can read only."""
    category = cat(world.a_owner, "Matrix Category")
    product = prod(
        world.a_owner,
        "Matrix Product",
        category_id=category["id"],
        default_cost_price_paise=SECRET_COST,
    )
    pid, cid = product["id"], category["id"]
    reads = [
        ("GET", f"{CAT}/units", None),
        ("GET", f"{CAT}/categories", None),
        ("GET", f"{CAT}/categories/{cid}", None),
        ("GET", f"{CAT}/products", None),
        ("GET", f"{CAT}/products/{pid}", None),
        ("GET", f"{CAT}/products/{pid}/aliases", None),
        ("GET", f"{CAT}/products/{pid}/prices", None),
    ]
    for role, client in (
        ("owner", world.a_owner),
        ("admin", world.a_admin),
        ("staff", world.a_staff),
    ):
        for method, url, _ in reads:
            assert client.request(method, url).status_code == 200, (role, url)

    def writes(suffix: str):
        return [
            ("POST", f"{CAT}/categories", {"name": f"New Cat {suffix}"}),
            ("PATCH", f"{CAT}/categories/{cid}", {"sort_order": 7}),
            (
                "POST",
                f"{CAT}/products",
                {"name": f"New Prod {suffix}", "base_unit_code": "kg", "selling_price_paise": 100},
            ),
            ("POST", f"{CAT}/products/{pid}/aliases", {"alias_text": f"alias {suffix}"}),
        ]

    for method, url, body in writes("staff"):
        r = world.a_staff.request(method, url, json=body, headers=_key())
        assert r.status_code == 403 and err(r) == "PERMISSION_DENIED", (url, r.text)
    for role, client in (("owner", world.a_owner), ("admin", world.a_admin)):
        for method, url, body in writes(role):
            r = client.request(method, url, json=body, headers=_key())
            assert r.status_code in (200, 201), (role, url, r.text)


# ============================================================================ 2. categories
def test_category_create_list_get_update(owner) -> None:
    c = owner["client"]
    dairy = cat(c, "Dairy", sort_order=2)
    staples = cat(c, "  Staples   & Grains ", name_hi="अनाज", sort_order=1)
    assert staples["name"] == "Staples & Grains" and staples["name_hi"] == "अनाज"
    listed = c.get(f"{CAT}/categories").json()
    assert [x["name"] for x in listed["items"]] == ["Staples & Grains", "Dairy"]
    assert listed["total"] == 2
    assert c.get(f"{CAT}/categories/{dairy['id']}").json()["sort_order"] == 2
    upd = c.patch(
        f"{CAT}/categories/{dairy['id']}",
        json={"name": "Dairy & Eggs", "name_hi": "दूध", "sort_order": 0},
        headers=_key(),
    )
    assert upd.status_code == 200
    assert (upd.json()["name"], upd.json()["name_hi"], upd.json()["sort_order"]) == (
        "Dairy & Eggs",
        "दूध",
        0,
    )
    assert c.get(f"{CAT}/categories").json()["items"][0]["name"] == "Dairy & Eggs"
    cleared = c.patch(f"{CAT}/categories/{dairy['id']}", json={"name_hi": None}, headers=_key())
    assert cleared.json()["name_hi"] is None
    assert c.patch(f"{CAT}/categories/{dairy['id']}", json={}, headers=_key()).status_code == 422


def test_category_duplicates(owner) -> None:
    c = owner["client"]
    cat(c, "Snacks")
    for name in ("Snacks", "SNACKS", "  snacks "):
        r = c.post(f"{CAT}/categories", json={"name": name}, headers=_key())
        assert r.status_code == 409 and err(r) == "CATEGORY_NAME_TAKEN", name
    other = cat(c, "Beverages")
    r = c.patch(f"{CAT}/categories/{other['id']}", json={"name": "snacks"}, headers=_key())
    assert r.status_code == 409 and err(r) == "CATEGORY_NAME_TAKEN"
    # renaming a category to a different case of its own name is fine
    same = c.patch(f"{CAT}/categories/{other['id']}", json={"name": "BEVERAGES"}, headers=_key())
    assert same.status_code == 200 and same.json()["name"] == "BEVERAGES"


def test_category_archive_rules(owner) -> None:
    c = owner["client"]
    oils = cat(c, "Oils")
    p1 = prod(c, "Mustard Oil", base_unit_code="l", category_id=oils["id"])
    p2 = prod(c, "Groundnut Oil", base_unit_code="l", category_id=oils["id"])
    r = c.post(f"{CAT}/categories/{oils['id']}/archive")
    assert r.status_code == 409 and err(r) == "CATEGORY_IN_USE"
    assert r.json()["error"]["details"] == {"active_products": 2}
    c.post(f"{CAT}/products/{p1['id']}/archive")
    assert err(c.post(f"{CAT}/categories/{oils['id']}/archive")) == "CATEGORY_IN_USE"
    c.post(f"{CAT}/products/{p2['id']}/archive")
    archived = c.post(f"{CAT}/categories/{oils['id']}/archive")
    assert archived.status_code == 200 and archived.json()["archived_at"]

    # archived behaviour
    assert oils["id"] not in [x["id"] for x in c.get(f"{CAT}/categories").json()["items"]]
    all_cats = c.get(f"{CAT}/categories", params={"include_archived": "true"}).json()["items"]
    assert oils["id"] in [x["id"] for x in all_cats]
    assert c.get(f"{CAT}/categories/{oils['id']}").json()["archived_at"]  # readable, not deleted
    r = c.patch(f"{CAT}/categories/{oils['id']}", json={"name": "Edible Oils"}, headers=_key())
    assert r.status_code == 409 and err(r) == "CATEGORY_ARCHIVED"
    assert err(c.post(f"{CAT}/categories/{oils['id']}/archive")) == "ALREADY_ARCHIVED"
    r = c.post(
        f"{CAT}/products",
        headers=_key(),
        json={
            "name": "Sesame Oil",
            "base_unit_code": "l",
            "selling_price_paise": 1,
            "category_id": oils["id"],
        },
    )
    assert r.status_code == 422 and err(r) == "CATEGORY_ARCHIVED"
    assert cat(c, "Oils")["id"] != oils["id"]  # archived name is reusable


# ============================================================================ 3. products
def test_product_create_list_get_update(owner) -> None:
    c = owner["client"]
    grains = cat(c, "Grains")
    p = prod(
        c,
        "Basmati Rice",
        name_hi="बासमती चावल",
        category_id=grains["id"],
        is_loose=True,
        selling_price_paise=12000,
        default_cost_price_paise=10500,
        reorder_level="25.500",
        barcode="8906000000011",
    )
    assert p["version"] == 1 and p["reorder_level"] == "25.500" and p["costs_visible"] is True
    assert c.get(f"{CAT}/products/{p['id']}").json() == p
    listed = c.get(f"{CAT}/products").json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == p["id"]
    upd = c.patch(
        f"{CAT}/products/{p['id']}",
        headers=_key(),
        json={"version": 1, "name": "Basmati Rice Premium", "reorder_level": "30", "barcode": None},
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["version"] == 2 and body["name"] == "Basmati Rice Premium"
    assert body["reorder_level"] == "30.000" and body["barcode"] is None
    assert body["selling_price_paise"] == 12000  # unchanged by PATCH


def test_patch_rejects_price_fields(owner) -> None:
    c = owner["client"]
    p = prod(c, "Poha")
    for field in ("selling_price_paise", "default_cost_price_paise"):
        r = c.patch(f"{CAT}/products/{p['id']}", json={"version": 1, field: 1}, headers=_key())
        assert r.status_code == 422 and "/prices" in r.text
    assert c.get(f"{CAT}/products/{p['id']}").json()["selling_price_paise"] == 4400


def test_duplicate_names_and_barcodes(owner) -> None:
    c = owner["client"]
    salt = prod(c, "Tata Salt 1kg", base_unit_code="packet", barcode="8901058000017")
    r = c.post(
        f"{CAT}/products",
        headers=_key(),
        json={"name": "TATA SALT 1KG", "base_unit_code": "packet", "selling_price_paise": 1},
    )
    assert r.status_code == 409 and err(r) == "PRODUCT_NAME_TAKEN"
    r = c.post(
        f"{CAT}/products",
        headers=_key(),
        json={
            "name": "Other Salt",
            "base_unit_code": "packet",
            "selling_price_paise": 1,
            "barcode": "8901058000017",
        },
    )
    assert r.status_code == 409 and err(r) == "BARCODE_TAKEN"
    other = prod(c, "Rock Salt", base_unit_code="packet")
    r = c.patch(
        f"{CAT}/products/{other['id']}",
        json={"version": 1, "name": "tata salt 1kg"},
        headers=_key(),
    )
    assert err(r) == "PRODUCT_NAME_TAKEN"
    r = c.patch(
        f"{CAT}/products/{other['id']}",
        json={"version": 1, "barcode": "8901058000017"},
        headers=_key(),
    )
    assert err(r) == "BARCODE_TAKEN"

    # archive: name becomes reusable, barcode stays reserved (approved rule 1)
    c.post(f"{CAT}/products/{salt['id']}/archive")
    reused = prod(c, "Tata Salt 1kg", base_unit_code="packet")
    r = c.post(
        f"{CAT}/products",
        headers=_key(),
        json={
            "name": "Salt Again",
            "base_unit_code": "packet",
            "selling_price_paise": 1,
            "barcode": "8901058000017",
        },
    )
    assert r.status_code == 409 and err(r) == "BARCODE_RESERVED_BY_ARCHIVED"
    r = c.patch(
        f"{CAT}/products/{reused['id']}",
        json={"version": 1, "barcode": "8901058000017"},
        headers=_key(),
    )
    assert r.status_code == 409 and err(r) == "BARCODE_RESERVED_BY_ARCHIVED"


def test_invalid_category_unit_and_decimal_rules(world) -> None:
    a, b = world.a_owner, world.b_owner
    foreign = cat(b, "B Category")

    def create(**body):
        base = {
            "name": "Probe " + os.urandom(3).hex(),
            "base_unit_code": "kg",
            "selling_price_paise": 1,
        }
        return a.post(f"{CAT}/products", json=base | body, headers=_key())

    missing = create(category_id=str(uuid.uuid4()))
    cross = create(category_id=foreign["id"])
    assert missing.status_code == cross.status_code == 422
    assert err(missing) == err(cross) == "INVALID_CATEGORY"
    assert (
        missing.json()["error"]["message"] == cross.json()["error"]["message"]
    )  # no existence leak
    r = create(base_unit_code="tola")
    assert r.status_code == 422 and err(r) == "INVALID_UNIT"
    r = create(base_unit_code="piece", is_loose=True)
    assert r.status_code == 422 and err(r) == "LOOSE_REQUIRES_DECIMAL_UNIT"
    r = create(base_unit_code="dozen", reorder_level="1.5")
    assert r.status_code == 422 and err(r) == "DECIMAL_NOT_ALLOWED_FOR_UNIT"
    assert create(base_unit_code="dozen", reorder_level="2").status_code == 201
    assert create(base_unit_code="g", is_loose=True, reorder_level="0.250").status_code == 201

    # the same rules apply on update (final values are validated together)
    loose = prod(a, "Loose Sugar", is_loose=True)
    r = a.patch(
        f"{CAT}/products/{loose['id']}",
        json={"version": 1, "base_unit_code": "packet"},
        headers=_key(),
    )
    assert err(r) == "LOOSE_REQUIRES_DECIMAL_UNIT"
    counted = prod(a, "Eggs Tray", base_unit_code="piece")
    r = a.patch(
        f"{CAT}/products/{counted['id']}",
        json={"version": 1, "reorder_level": "2.5"},
        headers=_key(),
    )
    assert err(r) == "DECIMAL_NOT_ALLOWED_FOR_UNIT"
    r = a.patch(
        f"{CAT}/products/{counted['id']}",
        json={"version": 1, "category_id": foreign["id"]},
        headers=_key(),
    )
    assert err(r) == "INVALID_CATEGORY"
    r = a.patch(
        f"{CAT}/products/{counted['id']}",
        json={"version": 1, "base_unit_code": "tola"},
        headers=_key(),
    )
    assert err(r) == "INVALID_UNIT"


def test_version_conflict(owner) -> None:
    c = owner["client"]
    p = prod(c, "Sooji")
    assert (
        c.patch(
            f"{CAT}/products/{p['id']}", json={"version": 1, "name_hi": "सूजी"}, headers=_key()
        ).status_code
        == 200
    )
    r = c.patch(f"{CAT}/products/{p['id']}", json={"version": 1, "name": "Rava"}, headers=_key())
    assert r.status_code == 409 and err(r) == "VERSION_CONFLICT"
    assert r.json()["error"]["details"] == {"current_version": 2}
    assert c.get(f"{CAT}/products/{p['id']}").json()["name"] == "Sooji"


def test_archived_product_behaviour(owner) -> None:
    c = owner["client"]
    p = prod(c, "Old Biscuit", base_unit_code="packet", default_cost_price_paise=1000)
    alias = c.post(
        f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "parle"}, headers=_key()
    ).json()
    archived = c.post(f"{CAT}/products/{p['id']}/archive")
    assert archived.status_code == 200 and archived.json()["version"] == 2
    got = c.get(f"{CAT}/products/{p['id']}")
    assert got.status_code == 200 and got.json()["archived_at"]  # readable by id
    assert p["id"] not in [x["id"] for x in c.get(f"{CAT}/products").json()["items"]]
    with_archived = c.get(f"{CAT}/products", params={"include_archived": "true"}).json()["items"]
    assert p["id"] in [x["id"] for x in with_archived]
    assert c.get(f"{CAT}/products/{p['id']}/prices").json()["total"] == 2  # history kept
    blocked = [
        c.patch(f"{CAT}/products/{p['id']}", json={"version": 2, "name": "New"}, headers=_key()),
        c.post(
            f"{CAT}/products/{p['id']}/prices",
            json={"version": 2, "selling_price_paise": 1},
            headers=_key(),
        ),
        c.post(f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "glucose"}, headers=_key()),
        c.delete(f"{CAT}/products/{p['id']}/aliases/{alias['id']}"),
    ]
    for r in blocked:
        assert r.status_code == 409 and err(r) == "PRODUCT_ARCHIVED", r.text
    assert err(c.post(f"{CAT}/products/{p['id']}/archive")) == "ALREADY_ARCHIVED"


def test_search_filter_and_pagination(owner) -> None:
    c = owner["client"]
    dairy, bakery = cat(c, "Dairy"), cat(c, "Bakery")
    milk = prod(
        c,
        "Amul Gold Milk",
        base_unit_code="l",
        name_hi="दूध",
        category_id=dairy["id"],
        barcode="8901262010016",
    )
    butter = prod(c, "Amul Butter", base_unit_code="packet", category_id=dairy["id"])
    sugar = prod(c, "Sugar")
    c.post(f"{CAT}/products/{sugar['id']}/aliases", json={"alias_text": "Cheeni"}, headers=_key())
    breads = [
        prod(c, f"Bread {n}", base_unit_code="packet", category_id=bakery["id"]) for n in "ABCDE"
    ]

    def ids(**params):
        r = c.get(f"{CAT}/products", params=params)
        assert r.status_code == 200, r.text
        return [x["id"] for x in r.json()["items"]], r.json()["total"]

    assert set(ids(q="amul")[0]) == {milk["id"], butter["id"]}
    assert set(ids(q="AMUL gold")[0]) == {milk["id"]}
    assert ids(q="दूध")[0] == [milk["id"]]  # Hindi name
    assert ids(q="CHEENI!")[0] == [sugar["id"]]  # alias via normalisation
    assert ids(q="8901262010016")[0] == [milk["id"]]  # exact barcode
    assert ids(q="890126")[1] == 0  # no partial barcode match
    assert ids(q="%")[1] == 0 and ids(q="_")[1] == 0  # wildcards are literal
    assert set(ids(category_id=dairy["id"])[0]) == {milk["id"], butter["id"]}
    assert ids(category_id=str(uuid.uuid4()))[1] == 0
    assert set(ids(q="amul", category_id=bakery["id"])[0]) == set()
    pages = [ids(category_id=bakery["id"], limit=2, offset=o) for o in (0, 2, 4)]
    assert [len(p[0]) for p in pages] == [2, 2, 1] and all(p[1] == 5 for p in pages)
    seen = [i for p in pages for i in p[0]]
    assert seen == [b["id"] for b in breads]  # stable ordering, no overlap or gaps
    assert ids(category_id=bakery["id"], limit=2, offset=10) == ([], 5)


# ============================================================================ 4. aliases
def test_alias_add_list_remove_and_no_internal_fields(owner) -> None:
    c = owner["client"]
    p = prod(c, "Sugar Loose", is_loose=True)
    a1 = c.post(
        f"{CAT}/products/{p['id']}/aliases",
        json={"alias_text": "  Cheeni ", "language": "hinglish"},
        headers=_key(),
    )
    a2 = c.post(
        f"{CAT}/products/{p['id']}/aliases",
        json={"alias_text": "शक्कर", "language": "hi"},
        headers=_key(),
    )
    assert a1.status_code == a2.status_code == 201
    assert a1.json()["alias_text"] == "Cheeni" and a1.json()["source"] == "manual"
    listing = c.get(f"{CAT}/products/{p['id']}/aliases")
    assert [x["alias_text"] for x in listing.json()["items"]] == ["Cheeni", "शक्कर"]
    for body in (a1.text, a2.text, listing.text):
        assert "normalized_text" not in body and "phonetic_key" not in body
    for variant in ("CHEENI", "cheeni!!", " Cheeni. "):
        r = c.post(
            f"{CAT}/products/{p['id']}/aliases", json={"alias_text": variant}, headers=_key()
        )
        assert r.status_code == 409 and err(r) == "ALIAS_EXISTS", variant
    assert c.delete(f"{CAT}/products/{p['id']}/aliases/{a1.json()['id']}").status_code == 204
    assert [x["id"] for x in c.get(f"{CAT}/products/{p['id']}/aliases").json()["items"]] == [
        a2.json()["id"]
    ]
    assert c.delete(f"{CAT}/products/{p['id']}/aliases/{a1.json()['id']}").status_code == 404
    other = prod(c, "Sugar Cubes", base_unit_code="packet")
    assert (
        c.post(
            f"{CAT}/products/{other['id']}/aliases", json={"alias_text": "cheeni"}, headers=_key()
        ).status_code
        == 201
    )
    # an alias cannot be removed through a different product's URL
    assert c.delete(f"{CAT}/products/{other['id']}/aliases/{a2.json()['id']}").status_code == 404
    bad = c.post(f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "!!!"}, headers=_key())
    assert bad.status_code == 422


# ============================================================================ 5. prices
def test_price_history_lifecycle(owner, super_engine) -> None:
    c = owner["client"]
    p = prod(c, "Toor Dal", selling_price_paise=14000, default_cost_price_paise=12000)
    pid = p["id"]
    hist = c.get(f"{CAT}/products/{pid}/prices").json()
    assert hist["total"] == 2
    assert sorted((h["price_type"], h["price_paise"]) for h in hist["items"]) == [
        ("cost", 12000),
        ("selling", 14000),
    ]

    def change(version, **prices):
        return c.post(
            f"{CAT}/products/{pid}/prices", json={"version": version, **prices}, headers=_key()
        )

    r = change(1, selling_price_paise=14500)
    assert (
        r.status_code == 200
        and r.json()["version"] == 2
        and r.json()["selling_price_paise"] == 14500
    )
    r = change(2, default_cost_price_paise=12300)
    assert r.json()["version"] == 3 and r.json()["default_cost_price_paise"] == 12300
    r = change(3, selling_price_paise=15000, default_cost_price_paise=12500)
    assert r.json()["version"] == 4
    rows_before = count(
        super_engine, "SELECT count(*) FROM product_prices WHERE product_id=:p", p=pid
    )
    assert rows_before == 6
    same = change(4, selling_price_paise=15000, default_cost_price_paise=12500)  # unchanged
    assert same.status_code == 200 and same.json()["version"] == 4
    assert (
        count(super_engine, "SELECT count(*) FROM product_prices WHERE product_id=:p", p=pid) == 6
    )
    partial = change(
        4, selling_price_paise=15000, default_cost_price_paise=12600
    )  # only cost changes
    assert partial.json()["version"] == 5
    assert (
        count(super_engine, "SELECT count(*) FROM product_prices WHERE product_id=:p", p=pid) == 7
    )

    stale = change(4, selling_price_paise=1)
    assert stale.status_code == 409 and err(stale) == "VERSION_CONFLICT"
    assert (
        count(super_engine, "SELECT count(*) FROM product_prices WHERE product_id=:p", p=pid) == 7
    )

    selling = c.get(f"{CAT}/products/{pid}/prices", params={"price_type": "selling"}).json()
    assert [h["price_paise"] for h in selling["items"]] == [15000, 14500, 14000]
    costs = c.get(f"{CAT}/products/{pid}/prices", params={"price_type": "cost"}).json()
    assert [h["price_paise"] for h in costs["items"]] == [12600, 12500, 12300, 12000]
    page = c.get(f"{CAT}/products/{pid}/prices", params={"limit": 3, "offset": 3}).json()
    assert page["total"] == 7 and len(page["items"]) == 3
    assert all(
        h["set_by_user_id"] == owner["user_id"] and h["source"] == "manual"
        for h in costs["items"] + selling["items"]
    )


def test_staff_never_receives_cost_values(world) -> None:
    a = world.a_owner
    p = prod(a, "Kesar", default_cost_price_paise=SECRET_COST, selling_price_paise=99000)
    a.post(
        f"{CAT}/products/{p['id']}/prices",
        json={"version": 1, "default_cost_price_paise": SECRET_COST_2},
        headers=_key(),
    )
    s = world.a_staff
    responses = [
        s.get(f"{CAT}/products/{p['id']}"),
        s.get(f"{CAT}/products", params={"q": "kesar"}),
        s.get(f"{CAT}/products", params={"include_archived": "true"}),
        s.get(f"{CAT}/products/{p['id']}/prices"),
        s.get(f"{CAT}/products/{p['id']}/prices", params={"price_type": "selling"}),
    ]
    for r in responses:
        assert r.status_code == 200
        assert str(SECRET_COST) not in r.text and str(SECRET_COST_2) not in r.text
    detail = responses[0].json()
    assert detail["selling_price_paise"] == 99000
    assert detail["default_cost_price_paise"] is None and detail["costs_visible"] is False
    history = responses[3].json()
    assert history["total"] == 1 and history["costs_visible"] is False
    assert {h["price_type"] for h in history["items"]} == {"selling"}
    denied = s.get(f"{CAT}/products/{p['id']}/prices", params={"price_type": "cost"})
    assert denied.status_code == 403 and err(denied) == "PERMISSION_DENIED"
    # the admin of the same shop does see costs
    admin_view = world.a_admin.get(f"{CAT}/products/{p['id']}").json()
    assert admin_view["default_cost_price_paise"] == SECRET_COST_2 and admin_view["costs_visible"]


# ============================================================================ 6. role permissions
def test_admin_performs_all_catalog_operations(world) -> None:
    ad = world.a_admin
    c = cat(ad, "Admin Category")
    upd = ad.patch(f"{CAT}/categories/{c['id']}", json={"name": "Admin Cat 2"}, headers=_key())
    assert upd.status_code == 200
    p = prod(ad, "Admin Product", category_id=c["id"], default_cost_price_paise=500)
    assert p["costs_visible"] and p["default_cost_price_paise"] == 500
    assert (
        ad.patch(
            f"{CAT}/products/{p['id']}", json={"version": 1, "name_hi": "उत्पाद"}, headers=_key()
        ).status_code
        == 200
    )
    alias = ad.post(
        f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "admin alias"}, headers=_key()
    )
    assert alias.status_code == 201
    assert ad.delete(f"{CAT}/products/{p['id']}/aliases/{alias.json()['id']}").status_code == 204
    price = ad.post(
        f"{CAT}/products/{p['id']}/prices",
        json={"version": 2, "default_cost_price_paise": 550},
        headers=_key(),
    )
    assert price.status_code == 200
    assert (
        ad.get(f"{CAT}/products/{p['id']}/prices", params={"price_type": "cost"}).json()["total"]
        == 2
    )
    assert ad.post(f"{CAT}/products/{p['id']}/archive").status_code == 200
    assert ad.post(f"{CAT}/categories/{c['id']}/archive").status_code == 200


def test_staff_cannot_modify_anything(world, super_engine) -> None:
    a, s = world.a_owner, world.a_staff
    c = cat(a, "Owner Category")
    p = prod(a, "Owner Product", category_id=c["id"], default_cost_price_paise=300)
    alias = a.post(
        f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "owner alias"}, headers=_key()
    ).json()
    snapshot = lambda: (  # noqa: E731
        count(
            super_engine, "SELECT count(*) FROM product_categories WHERE shop_id=:s", s=world.a_shop
        ),
        count(super_engine, "SELECT count(*) FROM products WHERE shop_id=:s", s=world.a_shop),
        count(
            super_engine, "SELECT count(*) FROM product_aliases WHERE shop_id=:s", s=world.a_shop
        ),
        count(super_engine, "SELECT count(*) FROM product_prices WHERE shop_id=:s", s=world.a_shop),
        count(super_engine, "SELECT version FROM products WHERE id=:p", p=p["id"]),
    )
    before = snapshot()
    attempts = [
        s.post(f"{CAT}/categories", json={"name": "Staff Cat"}, headers=_key()),
        s.patch(f"{CAT}/categories/{c['id']}", json={"name": "Hacked"}, headers=_key()),
        s.post(f"{CAT}/categories/{c['id']}/archive"),
        s.post(
            f"{CAT}/products",
            json={"name": "Staff P", "base_unit_code": "kg", "selling_price_paise": 1},
            headers=_key(),
        ),
        s.patch(f"{CAT}/products/{p['id']}", json={"version": 1, "name": "Hacked"}, headers=_key()),
        s.post(f"{CAT}/products/{p['id']}/archive"),
        s.post(
            f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "staff alias"}, headers=_key()
        ),
        s.delete(f"{CAT}/products/{p['id']}/aliases/{alias['id']}"),
        s.post(
            f"{CAT}/products/{p['id']}/prices",
            json={"version": 1, "selling_price_paise": 1},
            headers=_key(),
        ),
        s.post(
            f"{CAT}/products/{p['id']}/prices",
            json={"version": 1, "default_cost_price_paise": 1},
            headers=_key(),
        ),
    ]
    for r in attempts:
        assert r.status_code == 403 and err(r) == "PERMISSION_DENIED", r.text
    assert snapshot() == before


# ============================================================================ 7. tenant isolation
def test_cross_shop_access_returns_404_without_leaks(world, super_engine) -> None:
    a = world.a_owner
    c = cat(a, "Private Category")
    p = prod(a, "Private Product", category_id=c["id"], default_cost_price_paise=SECRET_COST)
    alias = a.post(
        f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "secret"}, headers=_key()
    ).json()
    a_rows = count(super_engine, "SELECT count(*) FROM products WHERE shop_id=:s", s=world.a_shop)

    def probes(cid, pid, aid):
        return [
            ("GET", f"{CAT}/categories/{cid}", None),
            ("PATCH", f"{CAT}/categories/{cid}", {"name": "Mine"}),
            ("POST", f"{CAT}/categories/{cid}/archive", None),
            ("GET", f"{CAT}/products/{pid}", None),
            ("PATCH", f"{CAT}/products/{pid}", {"version": 1, "name": "Mine"}),
            ("POST", f"{CAT}/products/{pid}/archive", None),
            ("GET", f"{CAT}/products/{pid}/aliases", None),
            ("POST", f"{CAT}/products/{pid}/aliases", {"alias_text": "mine"}),
            ("DELETE", f"{CAT}/products/{pid}/aliases/{aid}", None),
            ("GET", f"{CAT}/products/{pid}/prices", None),
            ("POST", f"{CAT}/products/{pid}/prices", {"version": 1, "selling_price_paise": 1}),
        ]

    real = probes(c["id"], p["id"], alias["id"])
    fake = probes(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    for client in (world.b_owner, world.b_staff):
        for (method, url, body), (_, fake_url, _) in zip(real, fake, strict=True):
            hdr = _key() if method != "GET" else None
            r = client.request(method, url, json=body, headers=hdr)
            r_fake = client.request(
                method, fake_url, json=body, headers=_key() if method != "GET" else None
            )
            if r.status_code == 403:  # B staff lacks write permission: refused before any lookup
                assert r_fake.status_code == 403 and method != "GET", (method, url)
                continue
            assert r.status_code == 404 and err(r) == "NOT_FOUND", (method, url, r.text)
            # identical to a random id: existence is not revealed
            assert r_fake.status_code == 404
            assert r.json()["error"]["message"] == r_fake.json()["error"]["message"]
            assert str(SECRET_COST) not in r.text and "Private" not in r.text

    for client in (world.b_owner, world.b_staff):
        assert client.get(f"{CAT}/products", params={"q": "private"}).json()["total"] == 0
        assert client.get(f"{CAT}/products", params={"q": "secret"}).json()["total"] == 0
        assert (
            client.get(f"{CAT}/categories", params={"include_archived": "true"}).json()["total"]
            == 0
        )

    # A's data untouched; shops have independent name spaces
    fresh = a.get(f"{CAT}/products/{p['id']}").json()
    assert (fresh["name"], fresh["version"], fresh["archived_at"]) == ("Private Product", 1, None)
    assert [x["id"] for x in a.get(f"{CAT}/products/{p['id']}/aliases").json()["items"]] == [
        alias["id"]
    ]
    assert (
        count(super_engine, "SELECT count(*) FROM products WHERE shop_id=:s", s=world.a_shop)
        == a_rows
    )
    same_name_in_b = prod(world.b_owner, "Private Product")
    assert same_name_in_b["id"] != p["id"]
    assert (
        count(super_engine, "SELECT count(*) FROM products WHERE shop_id=:s", s=world.b_shop) == 1
    )
    assert (
        count(
            super_engine,
            "SELECT count(*) FROM product_aliases WHERE shop_id=:s AND product_id=:p",
            s=world.b_shop,
            p=p["id"],
        )
        == 0
    )


# ======================================================== 8. idempotency / transactions
def test_duplicate_keys_never_duplicate_rows(owner, super_engine) -> None:
    c, shop = owner["client"], owner["shop_id"]

    def twice(method, url, body):
        hdr = _key()
        first = c.request(method, url, json=body, headers=hdr)
        second = c.request(method, url, json=body, headers=hdr)
        assert first.status_code == second.status_code and first.status_code in (200, 201), (
            first.text
        )
        assert first.json() == second.json()
        assert second.headers.get("Idempotent-Replayed") == "true"
        return first.json()

    category = twice("POST", f"{CAT}/categories", {"name": "Idem Category"})
    product = twice(
        "POST",
        f"{CAT}/products",
        {
            "name": "Idem Product",
            "base_unit_code": "kg",
            "selling_price_paise": 100,
            "default_cost_price_paise": 80,
            "category_id": category["id"],
        },
    )
    twice("POST", f"{CAT}/products/{product['id']}/aliases", {"alias_text": "idem alias"})
    twice(
        "POST", f"{CAT}/products/{product['id']}/prices", {"version": 1, "selling_price_paise": 120}
    )
    twice("PATCH", f"{CAT}/products/{product['id']}", {"version": 2, "name_hi": "आइडेम"})
    twice("PATCH", f"{CAT}/categories/{category['id']}", {"sort_order": 9})

    cat_sql = "SELECT count(*) FROM product_categories WHERE shop_id=:s AND name='Idem Category'"
    assert count(super_engine, cat_sql, s=shop) == 1
    assert (
        count(
            super_engine,
            "SELECT count(*) FROM products WHERE shop_id=:s AND name='Idem Product'",
            s=shop,
        )
        == 1
    )
    assert (
        count(
            super_engine,
            "SELECT count(*) FROM product_aliases WHERE product_id=:p",
            p=product["id"],
        )
        == 1
    )
    # initial selling + initial cost + one price change
    assert (
        count(
            super_engine, "SELECT count(*) FROM product_prices WHERE product_id=:p", p=product["id"]
        )
        == 3
    )
    assert count(super_engine, "SELECT version FROM products WHERE id=:p", p=product["id"]) == 3


def test_same_key_different_body_rejected(owner) -> None:
    c = owner["client"]
    hdr = _key()
    assert c.post(f"{CAT}/categories", json={"name": "Key Reuse A"}, headers=hdr).status_code == 201
    r = c.post(f"{CAT}/categories", json={"name": "Key Reuse B"}, headers=hdr)
    assert r.status_code == 409 and err(r) == "IDEMPOTENCY_KEY_REUSED"


def test_missing_idempotency_key_on_required_writes(owner) -> None:
    c = owner["client"]
    category = cat(c, "Keyless Category")
    p = prod(c, "Keyless Product")
    requests = [
        ("POST", f"{CAT}/categories", {"name": "No Key"}),
        ("PATCH", f"{CAT}/categories/{category['id']}", {"sort_order": 1}),
        (
            "POST",
            f"{CAT}/products",
            {"name": "No Key", "base_unit_code": "kg", "selling_price_paise": 1},
        ),
        ("PATCH", f"{CAT}/products/{p['id']}", {"version": 1, "name_hi": "x"}),
        ("POST", f"{CAT}/products/{p['id']}/aliases", {"alias_text": "no key"}),
        ("POST", f"{CAT}/products/{p['id']}/prices", {"version": 1, "selling_price_paise": 1}),
    ]
    for method, url, body in requests:
        r = c.request(method, url, json=body)
        assert r.status_code == 400 and err(r) == "IDEMPOTENCY_KEY_REQUIRED", (method, url)
    assert c.get(f"{CAT}/products/{p['id']}").json()["version"] == 1


def test_failed_operations_leave_no_partial_records(owner, super_engine) -> None:
    c, shop = owner["client"], owner["shop_id"]
    prod(c, "Existing", barcode="1111111111")

    tables = (
        "products",
        "product_prices",
        "product_aliases",
        "product_categories",
        "idempotency_keys",
    )
    audit_sql = "SELECT count(*) FROM audit_logs WHERE shop_id=:s AND action LIKE 'product.%'"

    def counts():
        per_table = [
            count(super_engine, f"SELECT count(*) FROM {t} WHERE shop_id=:s", s=shop)
            for t in tables
        ]
        return (*per_table, count(super_engine, audit_sql, s=shop))

    before = counts()
    hdr = _key()
    failures = [
        c.post(
            f"{CAT}/products",
            headers=hdr,
            json={  # duplicate barcode
                "name": "New One",
                "base_unit_code": "kg",
                "selling_price_paise": 1,
                "default_cost_price_paise": 1,
                "barcode": "1111111111",
            },
        ),
        c.post(
            f"{CAT}/products",
            headers=_key(),
            json={  # invalid unit
                "name": "New Two",
                "base_unit_code": "tola",
                "selling_price_paise": 1,
            },
        ),
        c.post(
            f"{CAT}/products",
            headers=_key(),
            json={  # duplicate name
                "name": "EXISTING",
                "base_unit_code": "kg",
                "selling_price_paise": 1,
            },
        ),
    ]
    assert [r.status_code for r in failures] == [409, 422, 409]
    # no product, price-history, alias, category, idempotency or audit rows were left behind
    assert counts() == before
    # the failed request's key was rolled back with it, so it can be reused for a valid request
    ok = c.post(
        f"{CAT}/products",
        headers=hdr,
        json={
            "name": "New One",
            "base_unit_code": "kg",
            "selling_price_paise": 1,
            "default_cost_price_paise": 1,
        },
    )
    assert ok.status_code == 201
    after = counts()
    assert after[0] == before[0] + 1 and after[1] == before[1] + 2  # product + 2 history rows


def test_failed_price_update_writes_no_history(owner, super_engine) -> None:
    c = owner["client"]
    p = prod(c, "Chana Dal", default_cost_price_paise=8000)
    q = "SELECT count(*) FROM product_prices WHERE product_id=:p"
    before = count(super_engine, q, p=p["id"])
    bad = [
        c.post(
            f"{CAT}/products/{p['id']}/prices",
            json={"version": 9, "selling_price_paise": 1},
            headers=_key(),
        ),
        c.post(
            f"{CAT}/products/{p['id']}/prices",
            json={"version": 1, "selling_price_paise": -1},
            headers=_key(),
        ),
        c.post(f"{CAT}/products/{p['id']}/prices", json={"version": 1}, headers=_key()),
    ]
    assert [r.status_code for r in bad] == [409, 422, 422]
    assert count(super_engine, q, p=p["id"]) == before
    assert c.get(f"{CAT}/products/{p['id']}").json()["version"] == 1
