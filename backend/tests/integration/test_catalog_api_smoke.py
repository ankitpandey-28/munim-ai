"""Stage 4 smoke tests: catalogue routes are wired correctly over HTTP (disposable PostgreSQL).

These check routing, dependencies, idempotency, commit behaviour and query validation. The
comprehensive behaviour/permission/isolation suite is the Stage 5 API test plan.
"""

import os
import uuid

import pytest

from tests.integration.conftest import next_phone

CAT = "/api/v1/catalog"
ROUTES = [
    ("GET", "/units"),
    ("GET", "/categories"),
    ("POST", "/categories"),
    ("GET", "/categories/{id}"),
    ("PATCH", "/categories/{id}"),
    ("POST", "/categories/{id}/archive"),
    ("GET", "/products"),
    ("POST", "/products"),
    ("GET", "/products/{id}"),
    ("PATCH", "/products/{id}"),
    ("POST", "/products/{id}/archive"),
    ("GET", "/products/{id}/aliases"),
    ("POST", "/products/{id}/aliases"),
    ("DELETE", "/products/{id}/aliases/{id}"),
    ("GET", "/products/{id}/prices"),
    ("POST", "/products/{id}/prices"),
]


def _key() -> dict:
    return {"Idempotency-Key": os.urandom(12).hex()}


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_catalog_route_requires_authentication(client, method, path) -> None:
    url = CAT + path.replace("{id}", str(uuid.uuid4()))
    response = client.request(method, url, json={} if method in ("POST", "PATCH") else None)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_no_permanent_delete_routes(owner) -> None:
    c = owner["client"]
    some = str(uuid.uuid4())
    for path in (f"{CAT}/products/{some}", f"{CAT}/categories/{some}"):
        assert c.delete(path).status_code == 405


def test_owner_flow_persists_and_is_idempotent(owner, make_client) -> None:
    c = owner["client"]
    assert {"kg", "piece"} <= {u["code"] for u in c.get(f"{CAT}/units").json()["items"]}

    key = _key()
    cat1 = c.post(f"{CAT}/categories", json={"name": "Staples"}, headers=key)
    cat2 = c.post(f"{CAT}/categories", json={"name": "Staples"}, headers=key)
    assert cat1.status_code == cat2.status_code == 201
    assert cat1.json() == cat2.json() and cat2.headers.get("Idempotent-Replayed") == "true"
    assert c.post(f"{CAT}/categories", json={"name": "No Key"}).status_code == 400
    cat_id = cat1.json()["id"]

    product = c.post(
        f"{CAT}/products",
        json={"name": "Atta", "base_unit_code": "kg", "selling_price_paise": 4200,
              "default_cost_price_paise": 3900, "is_loose": True, "category_id": cat_id},
        headers=_key(),
    )  # fmt: skip
    assert product.status_code == 201, product.text
    p = product.json()
    assert p["default_cost_price_paise"] == 3900 and p["costs_visible"] is True

    # committed: visible from a fresh request/session
    assert c.get(f"{CAT}/products/{p['id']}").json()["name"] == "Atta"
    listed = c.get(f"{CAT}/products", params={"q": "att", "category_id": cat_id, "limit": 10})
    assert listed.status_code == 200 and listed.json()["total"] == 1

    with_price = c.patch(
        f"{CAT}/products/{p['id']}", json={"version": 1, "selling_price_paise": 1}, headers=_key()
    )
    assert with_price.status_code == 422  # prices only via /prices
    renamed = c.patch(
        f"{CAT}/products/{p['id']}", json={"version": 1, "name_hi": "आटा"}, headers=_key()
    )
    assert renamed.status_code == 200 and renamed.json()["version"] == 2

    price_body = {"version": 2, "selling_price_paise": 4400}
    price = c.post(f"{CAT}/products/{p['id']}/prices", json=price_body, headers=_key())
    assert price.status_code == 200 and price.json()["version"] == 3
    history = c.get(f"{CAT}/products/{p['id']}/prices").json()
    assert history["total"] == 3 and history["costs_visible"] is True

    alias = c.post(f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "Aata"}, headers=_key())
    assert alias.status_code == 201
    assert [
        a["alias_text"] for a in c.get(f"{CAT}/products/{p['id']}/aliases").json()["items"]
    ] == ["Aata"]
    assert "normalized_text" not in alias.json()
    assert c.delete(f"{CAT}/products/{p['id']}/aliases/{alias.json()['id']}").status_code == 204
    assert c.get(f"{CAT}/products/{p['id']}/aliases").json()["items"] == []

    assert c.post(f"{CAT}/categories/{cat_id}/archive").json()["error"]["code"] == "CATEGORY_IN_USE"
    archived = c.post(f"{CAT}/products/{p['id']}/archive")
    assert archived.status_code == 200 and archived.json()["archived_at"]
    assert c.post(f"{CAT}/products/{p['id']}/archive").status_code == 409
    assert c.post(f"{CAT}/categories/{cat_id}/archive").status_code == 200


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 121}, {"category_id": "nope"},
     {"shop_id": str(uuid.uuid4())}],
)  # fmt: skip
def test_product_list_query_validation(owner, params) -> None:
    response = owner["client"].get(f"{CAT}/products", params=params)
    assert response.status_code == 422


def test_body_shop_id_and_bad_ids_rejected(owner) -> None:
    c = owner["client"]
    body = {"name": "X", "shop_id": str(uuid.uuid4())}
    assert c.post(f"{CAT}/categories", json=body, headers=_key()).status_code == 422
    assert c.get(f"{CAT}/products/not-a-uuid").status_code == 422
    assert c.get(f"{CAT}/products/{uuid.uuid4()}").status_code == 404
    assert (
        c.get(f"{CAT}/products/{uuid.uuid4()}/prices", params={"price_type": "x"}).status_code
        == 422
    )


def test_staff_sees_selling_price_only_and_cannot_write(owner, make_client) -> None:
    c = owner["client"]
    p = c.post(f"{CAT}/products", headers=_key(), json={
        "name": "Ghee", "base_unit_code": "l", "selling_price_paise": 65000,
        "default_cost_price_paise": 59000})  # fmt: skip
    assert p.status_code == 201
    pid = p.json()["id"]
    phone, temp = next_phone(), "Temp-Pass-" + os.urandom(4).hex()
    added = c.post("/api/v1/shops/current/members", headers=_key(), json={
        "phone": phone, "name": "Helper", "role": "staff", "temporary_password": temp})  # fmt: skip
    assert added.status_code == 201
    staff = make_client()
    staff.post("/api/v1/auth/login", json={"phone": phone, "password": temp})
    staff.post("/api/v1/auth/change-password",
               json={"current_password": temp, "new_password": "Staff-New-Pass-42"})  # fmt: skip
    seen = staff.get(f"{CAT}/products/{pid}")
    assert seen.status_code == 200
    assert seen.json()["selling_price_paise"] == 65000
    assert seen.json()["default_cost_price_paise"] is None and seen.json()["costs_visible"] is False
    history = staff.get(f"{CAT}/products/{pid}/prices")
    assert history.status_code == 200 and "59000" not in history.text
    assert (
        staff.get(f"{CAT}/products/{pid}/prices", params={"price_type": "cost"}).status_code == 403
    )
    assert staff.post(f"{CAT}/categories", json={"name": "X"}, headers=_key()).status_code == 403
    assert staff.post(f"{CAT}/products/{pid}/prices", json={"version": 1, "selling_price_paise": 1},
                      headers=_key()).status_code == 403  # fmt: skip
