"""Scripted end-to-end catalogue checks through the Next.js proxy (same path as the browser).

Run against the disposable stack only (scripts/e2e_stack.py + `next start`), never production:
    .venv\\Scripts\\python -m scripts.e2e_catalog [--base http://127.0.0.1:3000]
Prints one PASS/FAIL line per check and exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import random
import secrets
import sys
import uuid

import httpx

# Fresh throwaway passwords per run (disposable stack only).
PASSWORD = f"Kirana-{secrets.token_urlsafe(12)}"
STAFF_TEMP = f"Temp-{secrets.token_urlsafe(12)}"
STAFF_NEW = f"Staff-{secrets.token_urlsafe(12)}"

results: list[tuple[bool, str]] = []


def check(ok: bool, name: str) -> None:
    results.append((bool(ok), name))
    print(f"{'PASS' if ok else 'FAIL'}  {name}", flush=True)


def phone() -> str:
    return f"9{random.randint(100000000, 999999999)}"  # noqa: S311 - test data


def key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=30, follow_redirects=False)


def register(c: httpx.Client, name: str) -> str:
    p = phone()
    r = c.post("/api/v1/auth/register", json={"phone": p, "name": name, "password": PASSWORD})
    r.raise_for_status()
    return p


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:3000")
    base = parser.parse_args().base
    api = "/api/v1/catalog"

    anon = client(base)
    r = anon.get("/catalog")
    check(
        r.status_code in (302, 307) and "/login" in r.headers.get("location", ""),
        "anonymous /catalog page redirects to login",
    )
    check(anon.get(f"{api}/products").status_code == 401, "anonymous catalogue API returns 401")

    owner = client(base)
    register(owner, "E2E Owner")
    r = owner.post("/api/v1/shops", json={"name": "E2E Kirana"}, headers=key())
    check(r.status_code == 201, "owner creates shop through proxy")
    for path in ("/catalog", "/catalog/categories", f"/catalog/{uuid.uuid4()}"):
        check(
            owner.get(path).status_code == 200, f"page {path.split('/')[-1] or 'catalog'} renders"
        )

    units = owner.get(f"{api}/units").json()["items"]
    codes = {u["code"] for u in units}
    check({"kg", "piece"} <= codes, "units list includes kg and piece")

    r = owner.post(
        f"{api}/categories", json={"name": "Grocery", "name_hi": "किराना"}, headers=key()
    )
    check(r.status_code == 201, "create category")
    cat = r.json()
    r = owner.post(f"{api}/categories", json={"name": "grocery"}, headers=key())
    check(
        r.status_code == 409 and r.json()["error"]["code"] == "CATEGORY_NAME_TAKEN",
        "duplicate category name (case-insensitive) rejected",
    )

    body = {
        "name": "Sugar",
        "name_hi": "चीनी",
        "category_id": cat["id"],
        "base_unit_code": "kg",
        "is_loose": True,
        "selling_price_paise": 4400,
        "default_cost_price_paise": 3900,
        "reorder_level": "5",
        "barcode": "8901000000017",
    }
    k = key()
    r = owner.post(f"{api}/products", json=body, headers=k)
    check(r.status_code == 201 and r.json()["version"] == 1, "create loose product with cost")
    sugar = r.json()
    r2 = owner.post(f"{api}/products", json=body, headers=k)
    check(
        r2.status_code == 201 and r2.json()["id"] == sugar["id"],
        "retry with the same Idempotency-Key replays (no duplicate)",
    )
    total = owner.get(f"{api}/products").json()["total"]
    check(total == 1, "exactly one product exists after retry")

    r = owner.post(
        f"{api}/products",
        json={**body, "name": "Rice", "barcode": None, "base_unit_code": "piece"},
        headers=key(),
    )
    check(
        r.status_code == 422 and r.json()["error"]["code"] == "LOOSE_REQUIRES_DECIMAL_UNIT",
        "loose product with a count unit rejected",
    )
    r = owner.post(
        f"{api}/products",
        json={"name": "Soap", "base_unit_code": "piece", "selling_price_paise": 44.5},
        headers=key(),
    )
    check(r.status_code == 422, "float money rejected")
    r = owner.post(
        f"{api}/products",
        json={"name": "Soap", "base_unit_code": "piece", "selling_price_paise": 3500},
        headers=key(),
    )
    check(r.status_code == 201, "create packaged product")
    soap = r.json()

    r = owner.post(
        f"{api}/products/{sugar['id']}/aliases", json={"alias_text": "Cheeni"}, headers=key()
    )
    check(r.status_code == 201, "add alias")
    q = owner.get(f"{api}/products", params={"q": "CHEENI!"}).json()
    check([p["id"] for p in q["items"]] == [sugar["id"]], "search by alias (normalised)")
    q = owner.get(f"{api}/products", params={"q": "8901000000017"}).json()
    check([p["id"] for p in q["items"]] == [sugar["id"]], "search by exact barcode")
    q = owner.get(f"{api}/products", params={"q": "89010"}).json()
    check(q["total"] == 0, "partial barcode does not match")
    q = owner.get(f"{api}/products", params={"category_id": cat["id"]}).json()
    check([p["id"] for p in q["items"]] == [sugar["id"]], "category filter")

    r = owner.patch(
        f"{api}/products/{sugar['id']}",
        json={"version": 1, "selling_price_paise": 1},
        headers=key(),
    )
    check(r.status_code == 422, "PATCH rejects price fields")
    r = owner.post(
        f"{api}/products/{sugar['id']}/prices",
        json={"version": 1, "selling_price_paise": 4600},
        headers=key(),
    )
    check(
        r.status_code == 200
        and r.json()["version"] == 2
        and r.json()["selling_price_paise"] == 4600,
        "price update bumps version",
    )
    r = owner.post(
        f"{api}/products/{sugar['id']}/prices",
        json={"version": 1, "selling_price_paise": 4700},
        headers=key(),
    )
    check(
        r.status_code == 409 and r.json()["error"]["code"] == "VERSION_CONFLICT",
        "stale version rejected",
    )
    hist = owner.get(f"{api}/products/{sugar['id']}/prices").json()
    check(hist["total"] == 3 and hist["costs_visible"], "price history: 2 initial rows + 1 change")

    # Staff: view only, never cost data.
    staff_phone = phone()
    r = owner.post(
        "/api/v1/shops/current/members",
        headers=key(),
        json={
            "phone": staff_phone,
            "role": "staff",
            "name": "E2E Staff",
            "temporary_password": STAFF_TEMP,
        },
    )
    check(r.status_code == 201, "owner adds staff member")
    staff = client(base)
    staff.post("/api/v1/auth/login", json={"phone": staff_phone, "password": STAFF_TEMP})
    r = staff.post(
        "/api/v1/auth/change-password",
        json={"current_password": STAFF_TEMP, "new_password": STAFF_NEW},
    )
    check(r.status_code in (200, 204), "staff changes temporary password")
    r = staff.get(f"{api}/products/{sugar['id']}")
    sp = r.json()
    check(
        r.status_code == 200
        and sp["default_cost_price_paise"] is None
        and sp["costs_visible"] is False
        and "3900" not in r.text,
        "staff sees no cost price",
    )
    r = staff.get(f"{api}/products/{sugar['id']}/prices")
    check(
        all(x["price_type"] == "selling" for x in r.json()["items"]) and "3900" not in r.text,
        "staff price history has no cost rows",
    )
    r = staff.get(f"{api}/products/{sugar['id']}/prices", params={"price_type": "cost"})
    check(r.status_code == 403, "staff asking for cost history gets 403")
    r = staff.post(
        f"{api}/products",
        json={"name": "X", "base_unit_code": "piece", "selling_price_paise": 100},
        headers=key(),
    )
    check(r.status_code == 403, "staff cannot create products")
    r = staff.post(f"{api}/products/{soap['id']}/archive")
    check(r.status_code == 403, "staff cannot archive")

    # Another shop cannot see this shop's data.
    other = client(base)
    register(other, "Other Owner")
    other.post("/api/v1/shops", json={"name": "Other Shop"}, headers=key())
    r = other.get(f"{api}/products/{sugar['id']}")
    r_random = other.get(f"{api}/products/{uuid.uuid4()}")
    check(
        r.status_code == 404
        and r.json()["error"]["message"] == r_random.json()["error"]["message"],
        "other shop gets the same 404 as a random id",
    )
    check(
        other.get(f"{api}/products", params={"q": "Sugar"}).json()["total"] == 0,
        "other shop's search finds nothing",
    )
    r = other.get(f"{api}/products", params={"shop_id": str(uuid.uuid4())})
    check(r.status_code == 422, "shop_id query parameter rejected")

    # Archive.
    r = owner.post(f"{api}/categories/{cat['id']}/archive")
    check(
        r.status_code == 409 and r.json()["error"]["code"] == "CATEGORY_IN_USE",
        "category in use cannot be archived",
    )
    r = owner.post(f"{api}/products/{sugar['id']}/archive")
    check(r.status_code == 200 and r.json()["archived_at"], "archive product")
    check(owner.get(f"{api}/products").json()["total"] == 1, "archived product hidden from list")
    check(
        owner.get(f"{api}/products", params={"include_archived": "true"}).json()["total"] == 2,
        "include_archived shows it",
    )
    r = owner.patch(
        f"{api}/products/{sugar['id']}", json={"version": 3, "name": "Sugar 2"}, headers=key()
    )
    check(
        r.status_code == 409 and r.json()["error"]["code"] == "PRODUCT_ARCHIVED",
        "archived product cannot be edited",
    )
    check(
        owner.post(f"{api}/categories/{cat['id']}/archive").status_code == 200,
        "category archivable once unused",
    )

    failed = [n for ok, n in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
