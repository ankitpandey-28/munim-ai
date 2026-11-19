"""Inventory API over real HTTP and PostgreSQL 18 (disposable cluster): weighted-average costing,
reversals (D-11), counts, guards (D-12), permissions and cost hiding, shop isolation,
idempotency and concurrency. Database checks use the throwaway superuser, read-only."""

import threading

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_catalog_api import (  # noqa: F401 - `world` is a fixture
    _key,
    count,
    err,
    prod,
    world,
)

INV = "/api/v1/inventory"
CAT = "/api/v1/catalog"
SECRET_COST = 47123  # distinctive: must never appear in a staff response


def post(c: TestClient, path: str, body: dict, key: dict | None = None):
    return c.post(f"{INV}{path}", json=body, headers=key or _key())


def ok(r, code: int = 201) -> dict:
    assert r.status_code == code, r.text
    return r.json()


def stock(c: TestClient, product_id: str) -> dict:
    return ok(c.get(f"{INV}/stock/{product_id}"), 200)


def invariant_holds(engine) -> None:
    """I1: every cached level equals the sum of its movements."""
    bad = count(
        engine,
        "SELECT count(*) FROM inventory_levels l WHERE l.quantity_on_hand <> "
        "(SELECT coalesce(sum(m.quantity_delta), 0) FROM stock_movements m "
        " WHERE m.shop_id = l.shop_id AND m.product_id = l.product_id)",
    )
    assert bad == 0


# ============================================================================ costing
def test_weighted_average_and_receipt_reversal_backs_out_cost(owner, super_engine) -> None:
    c = owner["client"]
    sugar = prod(c, "Sugar", default_cost_price_paise=3800)
    ok(post(c, "/opening-stock", {"lines": [
        {"product_id": sugar["id"], "quantity": "10", "unit_cost_paise": 4000}]}))  # fmt: skip
    s = stock(c, sugar["id"])
    assert s["quantity_on_hand"] == "10.000" and s["avg_cost_paise"] == 4000
    receipt = ok(post(c, "/receipts", {"invoice_number": "INV-1", "lines": [
        {"product_id": sugar["id"], "quantity": "10", "unit_cost_paise": 5000}]}))  # fmt: skip
    assert receipt["txn_type"] == "goods_receipt"
    assert receipt["movements"][0]["movement_type"] == "purchase_receipt"
    s = stock(c, sugar["id"])
    assert s["quantity_on_hand"] == "20.000" and s["avg_cost_paise"] == 4500
    assert s["stock_value_paise"] == 90000
    summary = ok(c.get(f"{INV}/summary"), 200)
    assert summary["tracked_products"] == 1 and summary["stock_value_paise"] == 90000
    # D-11: reversing the receipt restores the previous average exactly
    rev = ok(
        post(c, f"/transactions/{receipt['transaction_id']}/reverse", {"reason": "wrong cost"})
    )
    assert rev["txn_type"] == "reversal"
    assert rev["movements"][0]["movement_type"] == "purchase_reversal"
    assert rev["movements"][0]["quantity_delta"] == "-10.000"
    s = stock(c, sugar["id"])
    assert s["quantity_on_hand"] == "10.000" and s["avg_cost_paise"] == 4000
    again = post(c, f"/transactions/{receipt['transaction_id']}/reverse", {"reason": "twice"})
    assert again.status_code == 409 and err(again) == "ALREADY_REVERSED"
    # The goods receipt record itself is kept (append-only), with the line total in paise
    assert count(super_engine, "SELECT total_cost_paise FROM goods_receipts WHERE transaction_id = "
                 ":t", t=receipt["transaction_id"]) == 50000  # fmt: skip
    invariant_holds(super_engine)


def test_rounding_half_up_and_unknown_cost(owner) -> None:
    c = owner["client"]
    p = prod(c, "Toor Dal")  # no default cost
    ok(post(c, "/opening-stock", {"lines": [{"product_id": p["id"], "quantity": "3"}]}))
    s = stock(c, p["id"])
    assert s["avg_cost_paise"] is None and s["stock_value_paise"] is None
    assert ok(c.get(f"{INV}/summary"), 200)["products_without_cost"] == 1
    # Existing stock with no known cost: the received cost becomes the average (D-12f)
    ok(post(c, "/receipts", {"lines": [{"product_id": p["id"], "quantity": "1",
                                        "unit_cost_paise": 1001}]}))  # fmt: skip
    assert stock(c, p["id"])["avg_cost_paise"] == 1001
    # (4 x 1001 + 2 x 1000) / 6 = 1000.667 -> 1001 (half-up)
    ok(post(c, "/receipts", {"lines": [{"product_id": p["id"], "quantity": "2",
                                        "unit_cost_paise": 1000}]}))  # fmt: skip
    assert stock(c, p["id"])["avg_cost_paise"] == 1001
    # Line total rounds half-up: 0.333 kg x 1500 = 499.5 -> 500
    r = ok(post(c, "/receipts", {"lines": [{"product_id": p["id"], "quantity": "0.333",
                                            "unit_cost_paise": 1500}]}))  # fmt: skip
    assert r["movements"][0]["quantity_delta"] == "0.333"


# ============================================================================ no negative stock
def test_adjustments_never_go_negative_and_reverse_cleanly(owner, super_engine) -> None:
    c = owner["client"]
    p = prod(c, "Atta", base_unit_code="packet")
    ok(post(c, "/opening-stock", {"lines": [{"product_id": p["id"], "quantity": "5",
                                             "unit_cost_paise": 30000}]}))  # fmt: skip
    too_much = post(c, "/adjustments", {"product_id": p["id"], "kind": "damage",
                                        "quantity": "6", "reason": "rats"})  # fmt: skip
    assert too_much.status_code == 409 and err(too_much) == "INSUFFICIENT_STOCK"
    assert too_much.json()["error"]["details"]["available"] == "5.000"
    no_reason = post(c, "/adjustments", {"product_id": p["id"], "kind": "damage",
                                         "quantity": "1", "reason": "  "})  # fmt: skip
    assert no_reason.status_code == 422
    adj = ok(post(c, "/adjustments", {"product_id": p["id"], "kind": "expiry",
                                      "quantity": "2", "reason": "expired"}))  # fmt: skip
    m = adj["movements"][0]
    assert m["movement_type"] == "adjustment_expiry" and m["quantity_delta"] == "-2.000"
    assert m["unit_cost_paise"] == 30000 and m["reason"] == "expired"
    assert stock(c, p["id"])["quantity_on_hand"] == "3.000"
    ok(post(c, f"/transactions/{adj['transaction_id']}/reverse", {"reason": "found them"}))
    s = stock(c, p["id"])
    assert s["quantity_on_hand"] == "5.000" and s["avg_cost_paise"] == 30000
    invariant_holds(super_engine)


def test_receipt_reversal_blocked_when_goods_already_used(owner, super_engine) -> None:
    c = owner["client"]
    p = prod(c, "Oil", base_unit_code="l")
    r = ok(post(c, "/receipts", {"lines": [{"product_id": p["id"], "quantity": "5",
                                            "unit_cost_paise": 15000}]}))  # fmt: skip
    ok(post(c, "/adjustments", {"product_id": p["id"], "kind": "loss",
                                "quantity": "4", "reason": "leak"}))  # fmt: skip
    before = count(super_engine, "SELECT count(*) FROM stock_movements WHERE product_id = :p",
                   p=p["id"])  # fmt: skip
    blocked = post(c, f"/transactions/{r['transaction_id']}/reverse", {"reason": "mistake"})
    assert blocked.status_code == 409 and err(blocked) == "INSUFFICIENT_STOCK"
    # Nothing was written: no reversal header, no movement, original still posted
    after = count(super_engine, "SELECT count(*) FROM stock_movements WHERE product_id = :p",
                  p=p["id"])  # fmt: skip
    assert after == before
    assert count(super_engine, "SELECT count(*) FROM business_transactions WHERE "
                 "reverses_transaction_id = :t", t=r["transaction_id"]) == 0  # fmt: skip
    assert stock(c, p["id"])["quantity_on_hand"] == "1.000"


# ============================================================================ counts
def test_stock_count_records_system_counted_difference(owner, super_engine) -> None:
    c = owner["client"]
    atta = prod(c, "Atta Loose", is_loose=True)
    ok(post(c, "/opening-stock", {"lines": [{"product_id": atta["id"], "quantity": "10",
                                             "unit_cost_paise": 4000}]}))  # fmt: skip
    stale = post(
        c,
        "/counts",
        {
            "note": "monthly",
            "lines": [
                {"product_id": atta["id"], "counted_quantity": "8", "expected_system_quantity": "9"}
            ],
        },
    )
    assert stale.status_code == 409 and err(stale) == "COUNT_STALE"
    assert stale.json()["error"]["details"]["products"][0]["current"] == "10.000"
    no_note = post(
        c,
        "/counts",
        {
            "note": "",
            "lines": [
                {
                    "product_id": atta["id"],
                    "counted_quantity": "8",
                    "expected_system_quantity": "10",
                }
            ],
        },
    )
    assert no_note.status_code == 422
    posted = ok(post(c, "/counts", {"note": "monthly count", "lines": [
        {"product_id": atta["id"], "counted_quantity": "8", "expected_system_quantity": "10",
         "reason": "count error"}]}))  # fmt: skip
    assert posted["txn_type"] == "stock_count"
    assert posted["movements"][0]["movement_type"] == "adjustment_count"
    assert posted["movements"][0]["quantity_delta"] == "-2.000"
    with super_engine.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(text(
            "SELECT i.system_quantity, i.counted_quantity, i.difference, c.status "
            "FROM stock_count_items i JOIN stock_counts c ON c.id = i.stock_count_id "
            "WHERE i.product_id = :p"), {"p": atta["id"]}).one()  # fmt: skip
    assert [str(v) for v in row[:3]] == ["10.000", "8.000", "-2.000"] and row[3] == "posted"
    s = stock(c, atta["id"])
    assert s["quantity_on_hand"] == "8.000" and s["avg_cost_paise"] == 4000
    invariant_holds(super_engine)


# ============================================================================ guards
def test_tracking_archive_and_unit_guards(owner) -> None:
    c = owner["client"]
    veg = prod(c, "Dhaniya", track_stock=False)
    r = post(c, "/receipts", {"lines": [{"product_id": veg["id"], "quantity": "1",
                                         "unit_cost_paise": 100}]})  # fmt: skip
    assert r.status_code == 409 and err(r) == "STOCK_NOT_TRACKED"
    rice = prod(c, "Rice")
    # Unit can change before any stock exists...
    upd = c.patch(f"{CAT}/products/{rice['id']}", headers=_key(),
                  json={"version": 1, "base_unit_code": "g"})  # fmt: skip
    assert upd.status_code == 200, upd.text
    ok(post(c, "/opening-stock", {"lines": [{"product_id": rice["id"], "quantity": "500"}]}))
    # ...but not after (UNIT_LOCKED), and tracking can't be switched off with stock (STOCK_NOT_ZERO)
    locked = c.patch(f"{CAT}/products/{rice['id']}", headers=_key(),
                     json={"version": 2, "base_unit_code": "kg"})  # fmt: skip
    assert locked.status_code == 409 and err(locked) == "UNIT_LOCKED"
    off = c.patch(f"{CAT}/products/{rice['id']}", headers=_key(),
                  json={"version": 2, "track_stock": False})  # fmt: skip
    assert off.status_code == 409 and err(off) == "STOCK_NOT_ZERO"
    ok(
        post(
            c,
            "/counts",
            {
                "note": "sold out",
                "lines": [
                    {
                        "product_id": rice["id"],
                        "counted_quantity": "0",
                        "expected_system_quantity": "500",
                    }
                ],
            },
        )
    )
    off = c.patch(f"{CAT}/products/{rice['id']}", headers=_key(),
                  json={"version": 2, "track_stock": False})  # fmt: skip
    assert off.status_code == 200, off.text
    soap = prod(c, "Soap", base_unit_code="piece")
    assert c.post(f"{CAT}/products/{soap['id']}/archive", headers=_key()).status_code == 200
    r = post(c, "/opening-stock", {"lines": [{"product_id": soap["id"], "quantity": "1"}]})
    assert r.status_code == 409 and err(r) == "PRODUCT_ARCHIVED"


def test_input_validation(owner) -> None:
    c = owner["client"]
    p = prod(c, "Salt", base_unit_code="packet")
    bad_bodies = [
        {"lines": [{"product_id": p["id"], "quantity": 1.5, "unit_cost_paise": 100}]},  # float
        {"lines": [{"product_id": p["id"], "quantity": "0", "unit_cost_paise": 100}]},
        {"lines": [{"product_id": p["id"], "quantity": "1.2345", "unit_cost_paise": 100}]},
        {"lines": [{"product_id": p["id"], "quantity": "1", "unit_cost_paise": -1}]},
        {"lines": [{"product_id": p["id"], "quantity": "1", "unit_cost_paise": "100"}]},
        {"lines": []},
        {"lines": [{"product_id": p["id"], "quantity": "1", "unit_cost_paise": 1}] * 2},
        {"lines": [{"product_id": p["id"], "quantity": "1", "unit_cost_paise": 1}], "shop_id": "x"},
    ]
    for body in bad_bodies:
        assert post(c, "/receipts", body).status_code == 422, body
    future = post(
        c,
        "/receipts",
        {
            "received_on": "2999-01-01",
            "lines": [{"product_id": p["id"], "quantity": "1", "unit_cost_paise": 1}],
        },
    )
    assert future.status_code == 422 and err(future) == "FUTURE_DATE"
    ghost = "00000000-0000-0000-0000-000000000001"
    missing = post(c, "/receipts", {"lines": [{"product_id": ghost, "quantity": "1",
                                               "unit_cost_paise": 1}]})  # fmt: skip
    assert missing.status_code == 404
    assert c.post(f"{INV}/receipts", json={"lines": []}).status_code in (400, 422)  # no key


# ============================================================================ roles / costs
def test_staff_quantities_only_and_restricted_writes(world) -> None:  # noqa: F811
    owner_c, staff, admin = world.a_owner, world.a_staff, world.a_admin
    p = prod(owner_c, "Ghee", default_cost_price_paise=SECRET_COST)
    ok(post(owner_c, "/opening-stock", {"lines": [{"product_id": p["id"], "quantity": "4",
                                                   "unit_cost_paise": SECRET_COST}]}))  # fmt: skip
    # Staff can view quantities and history, never costs or value
    bodies = []
    for path in ("/summary", f"/stock/{p['id']}", "/stock", f"/movements?product_id={p['id']}"):
        r = staff.get(f"{INV}{path}")
        assert r.status_code == 200, (path, r.text)
        bodies.append(r.text)
    s = staff.get(f"{INV}/stock/{p['id']}").json()
    assert s["quantity_on_hand"] == "4.000" and s["costs_visible"] is False
    assert s["avg_cost_paise"] is None and s["stock_value_paise"] is None
    # Staff can receive goods (SRS default); the response still hides costs
    rec = post(staff, "/receipts", {"lines": [{"product_id": p["id"], "quantity": "1",
                                               "unit_cost_paise": SECRET_COST}]})  # fmt: skip
    assert rec.status_code == 201, rec.text
    bodies.append(rec.text)
    for body in bodies:
        assert str(SECRET_COST) not in body
    # Staff cannot post opening stock, adjustments, counts or reversals
    for path, body in [
        ("/opening-stock", {"lines": [{"product_id": p["id"], "quantity": "1"}]}),
        ("/adjustments", {"product_id": p["id"], "kind": "loss", "quantity": "1", "reason": "x"}),
        (
            "/counts",
            {
                "note": "x",
                "lines": [
                    {
                        "product_id": p["id"],
                        "counted_quantity": "1",
                        "expected_system_quantity": "5",
                    }
                ],
            },
        ),
        (f"/transactions/{rec.json()['transaction_id']}/reverse", {"reason": "x"}),
    ]:
        r = post(staff, path, body)
        assert r.status_code == 403 and err(r) == "PERMISSION_DENIED", path
    # Admin = owner for inventory (D-10)
    ok(post(admin, "/adjustments", {"product_id": p["id"], "kind": "loss", "quantity": "1",
                                    "reason": "spill"}))  # fmt: skip
    assert admin.get(f"{INV}/stock/{p['id']}").json()["avg_cost_paise"] == SECRET_COST


def test_other_shops_see_nothing(world, super_engine) -> None:  # noqa: F811
    a, b = world.a_owner, world.b_owner
    p = prod(a, "Secret Basmati")
    txn = ok(post(a, "/opening-stock", {"lines": [{"product_id": p["id"], "quantity": "2"}]}))
    assert b.get(f"{INV}/stock/{p['id']}").status_code == 404
    assert b.get(f"{INV}/movements?product_id={p['id']}").json()["total"] == 0
    assert b.get(f"{INV}/stock").json()["total"] == 0
    r = post(b, "/receipts", {"lines": [{"product_id": p["id"], "quantity": "1",
                                         "unit_cost_paise": 1}]})  # fmt: skip
    assert r.status_code == 404
    r = post(b, f"/transactions/{txn['transaction_id']}/reverse", {"reason": "x"})
    assert r.status_code == 404
    assert "Secret Basmati" not in b.get(f"{INV}/movements").text
    assert stock(a, p["id"])["quantity_on_hand"] == "2.000"


# ============================================================================ idempotency / races
def test_retry_with_same_key_posts_once(owner, super_engine) -> None:
    c = owner["client"]
    p = prod(c, "Biscuit", base_unit_code="packet")
    key = _key()
    body = {"lines": [{"product_id": p["id"], "quantity": "12", "unit_cost_paise": 900}]}
    first = post(c, "/receipts", body, key)
    second = post(c, "/receipts", body, key)
    assert first.status_code == second.status_code == 201
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert first.json() == second.json()
    assert count(super_engine, "SELECT count(*) FROM stock_movements WHERE product_id = :p",
                 p=p["id"]) == 1  # fmt: skip
    changed = post(c, "/receipts", {**body, "invoice_number": "X"}, key)
    assert changed.status_code in (409, 422)
    assert stock(c, p["id"])["quantity_on_hand"] == "12.000"


@pytest.mark.parametrize("n", [4])
def test_concurrent_adjustments_never_oversell(owner, make_client, settings, super_engine, n):
    c = owner["client"]
    p = prod(c, "Maggi", base_unit_code="packet")
    ok(post(c, "/opening-stock", {"lines": [{"product_id": p["id"], "quantity": "5"}]}))
    cookie = c.cookies.get(settings.session_cookie_name)
    barrier, results, lock = threading.Barrier(n), [], threading.Lock()

    def worker() -> None:
        client = make_client()
        client.cookies.set(settings.session_cookie_name, cookie)
        barrier.wait()
        r = post(client, "/adjustments", {"product_id": p["id"], "kind": "loss",
                                          "quantity": "2", "reason": "race"})  # fmt: skip
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert sorted(results) == [201, 201, 409, 409]
    assert stock(c, p["id"])["quantity_on_hand"] == "1.000"
    invariant_holds(super_engine)


def test_lists_filters_and_history(owner) -> None:
    c = owner["client"]
    low = prod(c, "Low Item", base_unit_code="piece", reorder_level="5")
    out = prod(c, "Out Item", base_unit_code="piece", reorder_level="2")
    fine = prod(c, "Fine Item", base_unit_code="piece", reorder_level="1")
    lines = [
        {"product_id": low["id"], "quantity": "3"},
        {"product_id": fine["id"], "quantity": "9"},
    ]
    ok(post(c, "/opening-stock", {"lines": lines}))

    def names(status: str) -> list[str]:
        return [i["name"] for i in c.get(f"{INV}/stock?status={status}").json()["items"]]

    assert names("low") == ["Low Item"]
    assert names("out") == ["Out Item"]
    assert names("all") == ["Fine Item", "Low Item", "Out Item"]
    assert [i["name"] for i in c.get(f"{INV}/stock?q=fine").json()["items"]] == ["Fine Item"]
    s = ok(c.get(f"{INV}/summary"), 200)
    assert (s["tracked_products"], s["low_stock"], s["out_of_stock"]) == (3, 1, 1)
    hist = c.get(f"{INV}/movements?limit=1").json()
    assert hist["total"] == 2 and len(hist["items"]) == 1
    assert hist["items"][0]["initiated_by_name"] and hist["costs_visible"] is True
    assert out["id"]
