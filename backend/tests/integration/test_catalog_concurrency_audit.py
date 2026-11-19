"""Closes security-checklist gaps G7 and G8 for the catalogue, over real HTTP + PostgreSQL 18.

G7: simultaneous identical requests (same Idempotency-Key) execute exactly one business
    operation; simultaneous conflicting requests (different keys) are resolved cleanly.
G8: successful catalogue operations write the expected audit events (actor, shop, entity,
    before/after, request id); failed requests write none.

Disposable cluster only. Cross-shop/RLS-independent checks use the throwaway superuser, read-only.
"""

import os
import threading
import uuid
from collections import Counter

from sqlalchemy import text

from tests.integration.test_catalog_api import _key, _member, cat, count, err, prod

CAT = "/api/v1/catalog"
AUDIT = "/api/v1/shops/current/audit-logs"


def _race(make_client, cookie_name: str, cookie: str, n: int, send) -> list:
    """Fire ``n`` requests at the same moment from ``n`` clients sharing one session."""
    barrier = threading.Barrier(n)
    results: list = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        client = make_client()
        client.cookies.set(cookie_name, cookie)
        barrier.wait()
        response = send(client, i)
        with lock:
            results.append(response)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert len(results) == n, "a request did not complete"
    return results


# ============================================================================ G7: concurrency
def test_concurrent_identical_product_creation_executes_once(
    owner, make_client, settings, super_engine
):
    c = owner["client"]
    cookie = c.cookies.get(settings.session_cookie_name)
    key = {"Idempotency-Key": os.urandom(12).hex()}
    body = {"name": "Race Product", "base_unit_code": "kg", "selling_price_paise": 5000,
            "default_cost_price_paise": 4500}  # fmt: skip

    results = _race(make_client, settings.session_cookie_name, cookie, 4,
                    lambda cl, _i: cl.post(f"{CAT}/products", json=body, headers=key))  # fmt: skip

    assert [r.status_code for r in results] == [201] * 4, [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1  # every caller got the same product
    assert sum(r.headers.get("Idempotent-Replayed") == "true" for r in results) == 3
    pid = results[0].json()["id"]
    shop = owner["shop_id"]
    assert (
        count(
            super_engine,
            "SELECT count(*) FROM products WHERE shop_id=:s AND name='Race Product'",
            s=shop,
        )
        == 1
    )
    assert (
        count(super_engine, "SELECT count(*) FROM product_prices WHERE product_id=:p", p=pid) == 2
    )
    audit_q = "SELECT count(*) FROM audit_logs WHERE entity_id=:p AND action='product.created'"
    assert count(super_engine, audit_q, p=pid) == 1


def test_concurrent_identical_price_update_executes_once(
    owner, make_client, settings, super_engine
):
    c = owner["client"]
    p = prod(c, "Race Price Product", selling_price_paise=1000, default_cost_price_paise=800)
    cookie = c.cookies.get(settings.session_cookie_name)
    key = {"Idempotency-Key": os.urandom(12).hex()}
    body = {"version": 1, "selling_price_paise": 1100, "default_cost_price_paise": 850}

    url = f"{CAT}/products/{p['id']}/prices"
    results = _race(
        make_client,
        settings.session_cookie_name,
        cookie,
        4,
        lambda cl, _i: cl.post(url, json=body, headers=key),
    )

    assert [r.status_code for r in results] == [200] * 4, [r.text for r in results]
    # identical response content (replays come from JSONB, which doesn't keep key order,
    # so compare parsed JSON rather than raw bytes)
    assert all(r.json() == results[0].json() for r in results)
    assert results[0].json()["version"] == 2
    q = "SELECT count(*) FROM product_prices WHERE product_id=:p"
    assert count(super_engine, q, p=p["id"]) == 4  # 2 initial + exactly 2 for the single change
    assert count(super_engine, "SELECT version FROM products WHERE id=:p", p=p["id"]) == 2
    audit_q = (
        "SELECT count(*) FROM audit_logs WHERE entity_id=:p AND action='product.price_changed'"
    )
    assert count(super_engine, audit_q, p=p["id"]) == 1


def test_concurrent_same_name_different_keys_creates_one(
    owner, make_client, settings, super_engine
):
    """Different keys, same product name: exactly one succeeds; the rest get a clean 409
    (pre-check or the unique-index guard), never a 500."""
    c = owner["client"]
    cookie = c.cookies.get(settings.session_cookie_name)
    body = {"name": "Contested Name", "base_unit_code": "kg", "selling_price_paise": 100}

    results = _race(
        make_client,
        settings.session_cookie_name,
        cookie,
        4,
        lambda cl, _i: cl.post(f"{CAT}/products", json=body, headers=_key()),
    )

    codes = Counter(r.status_code for r in results)
    assert codes == {201: 1, 409: 3}, [r.text for r in results]
    assert all(err(r) == "PRODUCT_NAME_TAKEN" for r in results if r.status_code == 409)
    shop = owner["shop_id"]
    assert (
        count(
            super_engine,
            "SELECT count(*) FROM products WHERE shop_id=:s AND name='Contested Name'",
            s=shop,
        )
        == 1
    )
    winner = next(r for r in results if r.status_code == 201).json()["id"]
    assert (
        count(super_engine, "SELECT count(*) FROM product_prices WHERE product_id=:p", p=winner)
        == 1
    )


def test_concurrent_price_changes_same_version_one_wins(owner, make_client, settings, super_engine):
    """Different keys, same expected version: the row lock serialises them; one succeeds and
    the others see VERSION_CONFLICT. No lost update, no extra history."""
    c = owner["client"]
    p = prod(c, "Contested Price", selling_price_paise=2000)
    cookie = c.cookies.get(settings.session_cookie_name)

    results = _race(make_client, settings.session_cookie_name, cookie, 4,
                    lambda cl, i: cl.post(f"{CAT}/products/{p['id']}/prices",
                                          json={"version": 1, "selling_price_paise": 2100 + i},
                                          headers=_key()))  # fmt: skip

    codes = Counter(r.status_code for r in results)
    assert codes == {200: 1, 409: 3}, [r.text for r in results]
    assert all(err(r) == "VERSION_CONFLICT" for r in results if r.status_code == 409)
    winner_price = next(r for r in results if r.status_code == 200).json()["selling_price_paise"]
    assert c.get(f"{CAT}/products/{p['id']}").json()["selling_price_paise"] == winner_price
    assert (
        count(super_engine, "SELECT count(*) FROM product_prices WHERE product_id=:p", p=p["id"])
        == 2
    )
    assert count(super_engine, "SELECT version FROM products WHERE id=:p", p=p["id"]) == 2


# ============================================================================ G8: audit
def _rid(label: str) -> dict:
    """A distinctive, valid X-Request-ID (8-64 chars of [A-Za-z0-9._-])."""
    return {"X-Request-ID": f"t-{label}-{uuid.uuid4().hex[:12]}"}


def _audit_by_request(client) -> dict:
    items = client.get(AUDIT, params={"limit": 100}).json()["items"]
    return {e["request_id"]: e for e in items if e["request_id"]}


def test_successful_operations_write_expected_audit_events(owner, make_client, super_engine):
    c, shop, owner_id = owner["client"], owner["shop_id"], owner["user_id"]
    admin = _member(make_client, c, "admin")
    admin_id = admin.get("/api/v1/auth/me").json()["user"]["id"]
    rids: dict[str, str] = {}

    def send(label, client, method, url, body=None, idempotent=True):
        headers = _rid(label) | (_key() if idempotent else {})
        rids[label] = headers["X-Request-ID"]
        response = client.request(method, url, json=body, headers=headers)
        assert response.status_code in (200, 201, 204), (label, response.text)
        assert response.headers["X-Request-ID"] == rids[label]
        return response.json() if response.status_code != 204 else None

    category = send("cat-create", c, "POST", f"{CAT}/categories", {"name": "Audited Cat"})
    send("cat-update", c, "PATCH", f"{CAT}/categories/{category['id']}", {"sort_order": 4})
    product = send("prod-create", c, "POST", f"{CAT}/products",
                   {"name": "Audited Product", "base_unit_code": "kg", "selling_price_paise": 3000,
                    "default_cost_price_paise": 2500, "category_id": category["id"]})  # fmt: skip
    pid = product["id"]
    send("prod-update", admin, "PATCH", f"{CAT}/products/{pid}", {"version": 1, "name_hi": "जाँच"})
    send(
        "price",
        c,
        "POST",
        f"{CAT}/products/{pid}/prices",
        {"version": 2, "selling_price_paise": 3200},
    )
    alias = send(
        "alias-add", c, "POST", f"{CAT}/products/{pid}/aliases", {"alias_text": "audit alias"}
    )
    send(
        "alias-remove", c, "DELETE", f"{CAT}/products/{pid}/aliases/{alias['id']}", idempotent=False
    )
    send("prod-archive", c, "POST", f"{CAT}/products/{pid}/archive", idempotent=False)
    send("cat-archive", c, "POST", f"{CAT}/categories/{category['id']}/archive", idempotent=False)

    events = _audit_by_request(c)
    expected = {
        "cat-create": ("category.created", "product_category", category["id"], owner_id),
        "cat-update": ("category.updated", "product_category", category["id"], owner_id),
        "prod-create": ("product.created", "product", pid, owner_id),
        "prod-update": ("product.updated", "product", pid, admin_id),
        "price": ("product.price_changed", "product", pid, owner_id),
        "alias-add": ("product.alias_added", "product_alias", alias["id"], owner_id),
        "alias-remove": ("product.alias_removed", "product_alias", alias["id"], owner_id),
        "prod-archive": ("product.archived", "product", pid, owner_id),
        "cat-archive": ("category.archived", "product_category", category["id"], owner_id),
    }
    for label, (action, entity_type, entity_id, actor) in expected.items():
        e = events.get(rids[label])
        assert e is not None, f"no audit event for {label}"
        assert (e["action"], e["entity_type"], e["entity_id"], e["actor_user_id"]) == (
            action, entity_type, entity_id, actor), label  # fmt: skip

    # before/after snapshots
    ev = {label: events[rids[label]] for label in expected}
    assert ev["cat-create"]["before"] is None and ev["cat-create"]["after"]["name"] == "Audited Cat"
    assert (
        ev["cat-update"]["before"]["sort_order"] == 0
        and ev["cat-update"]["after"]["sort_order"] == 4
    )
    created = ev["prod-create"]["after"]
    assert created["name"] == "Audited Product"
    assert created["selling_price_paise"] == 3000
    assert created["default_cost_price_paise"] == 2500
    assert created["version"] == 1
    assert created["category_id"] == category["id"]
    upd = ev["prod-update"]
    assert upd["before"]["name_hi"] is None and upd["after"]["name_hi"] == "जाँच"
    assert (upd["before"]["version"], upd["after"]["version"]) == (1, 2)
    price = ev["price"]
    assert price["before"] == {"selling_price_paise": 3000, "version": 2}
    assert price["after"] == {"selling_price_paise": 3200, "version": 3}
    assert ev["alias-add"]["after"]["alias_text"] == "audit alias"
    assert ev["alias-add"]["after"]["product_id"] == pid
    assert (
        ev["alias-remove"]["before"]["alias_text"] == "audit alias"
        and ev["alias-remove"]["after"] is None
    )
    assert (
        ev["prod-archive"]["before"]["archived_at"] is None
        and ev["prod-archive"]["after"]["archived_at"]
    )
    assert (
        ev["cat-archive"]["before"]["archived_at"] is None
        and ev["cat-archive"]["after"]["archived_at"]
    )

    # shop is recorded on every event (not exposed by the API; checked in the database)
    with super_engine.connect() as conn:
        shops = (
            conn.execute(
                text("SELECT DISTINCT shop_id::text FROM audit_logs WHERE request_id = ANY(:r)"),
                {"r": list(rids.values())},
            )
            .scalars()
            .all()
        )
    assert shops == [shop]


def test_failed_requests_write_no_success_audit_event(owner, make_client, super_engine):
    c = owner["client"]
    staff = _member(make_client, c, "staff")
    cat(c, "Existing Cat")
    p = prod(c, "Existing Product")
    alias = c.post(
        f"{CAT}/products/{p['id']}/aliases", json={"alias_text": "dup"}, headers=_key()
    ).json()
    before = count(
        super_engine, "SELECT count(*) FROM audit_logs WHERE shop_id=:s", s=owner["shop_id"]
    )

    purl = f"{CAT}/products/{p['id']}"
    failures = [
        ("dup-cat", c, "POST", f"{CAT}/categories", {"name": "existing cat"}, 409),
        ("staff-cat", staff, "POST", f"{CAT}/categories", {"name": "Staff Cat"}, 403),
        ("bad-unit", c, "POST", f"{CAT}/products",
         {"name": "Bad Unit", "base_unit_code": "tola", "selling_price_paise": 1}, 422),
        ("dup-product", c, "POST", f"{CAT}/products",
         {"name": "EXISTING PRODUCT", "base_unit_code": "kg", "selling_price_paise": 1}, 409),
        ("stale-update", c, "PATCH", purl, {"version": 9, "name_hi": "x"}, 409),
        ("stale-price", c, "POST", f"{purl}/prices", {"version": 9, "selling_price_paise": 1}, 409),
        ("dup-alias", c, "POST", f"{purl}/aliases", {"alias_text": "DUP!"}, 409),
        ("staff-alias-del", staff, "DELETE", f"{purl}/aliases/{alias['id']}", None, 403),
        ("staff-archive", staff, "POST", f"{purl}/archive", None, 403),
        ("unknown-archive", c, "POST", f"{CAT}/products/{uuid.uuid4()}/archive", None, 404),
    ]  # fmt: skip
    rids = []
    for label, client, method, url, body, status in failures:
        headers = _rid(label) | _key()
        rids.append(headers["X-Request-ID"])
        r = client.request(method, url, json=body, headers=headers)
        assert r.status_code == status, (label, r.text)

    with super_engine.connect() as conn:
        leaked = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE request_id = ANY(:r)"), {"r": rids}
        ).scalar_one()
    assert leaked == 0
    assert (
        count(super_engine, "SELECT count(*) FROM audit_logs WHERE shop_id=:s", s=owner["shop_id"])
        == before
    )
    assert all(
        e["request_id"] not in rids for e in c.get(AUDIT, params={"limit": 100}).json()["items"]
    )
