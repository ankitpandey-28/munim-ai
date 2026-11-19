"""Catalogue service layer against real PostgreSQL 18 (disposable cluster, RLS as munim_app).

The API layer (Stage 4) is not used here: functions are called with a verified ShopContext
built from real rows, and the test commits after each successful operation, as the API will.
Roles other than the owner are simulated by overriding the membership role; real staff/admin
accounts are exercised through HTTP in the Stage 5 API tests.
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, InvalidInput, NotFound, PermissionDenied
from app.database.session import set_tenant_context
from app.modules.audit.models import AuditLog
from app.modules.catalog import service as catalog
from app.modules.catalog.models import ProductAlias, ProductPrice
from app.modules.catalog.schemas import (
    CategoryCreate,
    CategoryUpdate,
    ProductAliasCreate,
    ProductCreate,
    ProductListParams,
    ProductPriceUpdate,
    ProductUpdate,
)
from app.modules.identity.models import User
from app.modules.shops.context import ShopContext
from app.modules.shops.models import Shop, ShopMember
from tests.integration.conftest import create_shop, register


@pytest.fixture(scope="module")
def engine(pg):
    eng = create_engine(pg.app_url, pool_size=4)
    yield eng
    eng.dispose()


@pytest.fixture
def make_ctx(engine):
    """Return (session, ShopContext) for a shop; optionally simulate another role."""
    sessions: list[Session] = []

    def factory(user_id: str, shop_id: str, role: str | None = None):
        db = Session(engine, expire_on_commit=False)
        sessions.append(db)
        uid, sid = uuid.UUID(user_id), uuid.UUID(shop_id)
        set_tenant_context(db, user_id=uid, shop_id=sid)
        user = db.get(User, uid)
        shop = db.get(Shop, sid)
        member = db.execute(
            select(ShopMember).where(ShopMember.shop_id == sid, ShopMember.user_id == uid)
        ).scalar_one()
        membership = member if role is None else SimpleNamespace(role=role)
        return db, ShopContext(user=user, session=None, membership=membership, shop=shop)

    yield factory
    for db in sessions:
        db.rollback()
        db.close()


@pytest.fixture
def shop(owner, make_ctx):
    db, ctx = make_ctx(owner["user_id"], owner["shop_id"])
    return SimpleNamespace(db=db, ctx=ctx, owner=owner)


def _product(db, ctx, name="Chini", **kw):
    data = {"name": name, "base_unit_code": "kg", "selling_price_paise": 4400} | kw
    result = catalog.create_product(db, ctx, ProductCreate(**data))
    db.commit()
    return result


def _category(db, ctx, name="Staples", **kw):
    result = catalog.create_category(db, ctx, CategoryCreate(name=name, **kw))
    db.commit()
    return result


def _expect(exc_type, code, fn, *args, db=None):
    with pytest.raises(exc_type) as exc:
        fn(*args)
    assert exc.value.code == code, exc.value.code
    if db is not None:
        db.rollback()


# ----------------------------------------------------------------------------- units
def test_units_listed_for_every_role(shop, make_ctx) -> None:
    units = catalog.list_units(shop.db, shop.ctx).items
    assert {"kg", "g", "l", "ml", "piece", "packet", "dozen", "box"} <= {u.code for u in units}
    kg = next(u for u in units if u.code == "kg")
    assert kg.allows_decimal is True and kg.factor_to_dimension_base == Decimal("1")
    db, staff = make_ctx(shop.owner["user_id"], shop.owner["shop_id"], role="staff")
    assert len(catalog.list_units(db, staff).items) == len(units)


# ----------------------------------------------------------------------------- categories
def test_category_create_list_get(shop) -> None:
    db, ctx = shop.db, shop.ctx
    b = _category(db, ctx, "Dairy", sort_order=2)
    a = _category(db, ctx, "Staples", name_hi="अनाज", sort_order=1)
    listed = catalog.list_categories(db, ctx)
    assert [c.name for c in listed.items] == ["Staples", "Dairy"] and listed.total == 2
    assert catalog.get_category(db, ctx, a.id).name_hi == "अनाज"
    assert catalog.get_category(db, ctx, b.id).sort_order == 2


def test_duplicate_active_category_name_case_insensitive(shop) -> None:
    db, ctx = shop.db, shop.ctx
    _category(db, ctx, "Dairy")
    _expect(Conflict, "CATEGORY_NAME_TAKEN", catalog.create_category, db, ctx,
            CategoryCreate(name="DAIRY"))  # fmt: skip
    other = _category(db, ctx, "Snacks")
    _expect(Conflict, "CATEGORY_NAME_TAKEN", catalog.update_category, db, ctx, other.id,
            CategoryUpdate(name="dairy"))  # fmt: skip


def test_category_archive_rules(shop) -> None:
    db, ctx = shop.db, shop.ctx
    cat = _category(db, ctx, "Oils")
    p = _product(db, ctx, "Mustard Oil", base_unit_code="l", category_id=cat.id)
    _expect(Conflict, "CATEGORY_IN_USE", catalog.archive_category, db, ctx, cat.id)
    catalog.archive_product(db, ctx, p.id)
    db.commit()
    archived = catalog.archive_category(db, ctx, cat.id)
    db.commit()
    assert archived.archived_at is not None
    assert catalog.get_category(db, ctx, cat.id).archived_at is not None  # never deleted
    assert cat.id not in {c.id for c in catalog.list_categories(db, ctx).items}
    assert cat.id in {c.id for c in catalog.list_categories(db, ctx, include_archived=True).items}
    _expect(Conflict, "ALREADY_ARCHIVED", catalog.archive_category, db, ctx, cat.id)
    _expect(Conflict, "CATEGORY_ARCHIVED", catalog.update_category, db, ctx, cat.id,
            CategoryUpdate(name="Edible Oils"))  # fmt: skip
    # the name of an archived category can be reused
    assert _category(db, ctx, "Oils").id != cat.id


# ----------------------------------------------------------------------------- products
def test_product_create_records_initial_price_history(shop) -> None:
    db, ctx = shop.db, shop.ctx
    p = _product(db, ctx, "Atta", default_cost_price_paise=3800, is_loose=True,
                 reorder_level="10.500")  # fmt: skip
    assert p.version == 1 and p.default_cost_price_paise == 3800 and p.costs_visible
    rows = db.execute(
        select(ProductPrice.price_type, ProductPrice.price_paise, ProductPrice.set_by_user_id,
               ProductPrice.source).where(ProductPrice.product_id == p.id)
    ).all()  # fmt: skip
    assert sorted((r[0], r[1]) for r in rows) == [("cost", 3800), ("selling", 4400)]
    assert all(r[2] == ctx.user_id and r[3] == "manual" for r in rows)


def test_product_without_cost_records_only_selling_history(shop) -> None:
    p = _product(shop.db, shop.ctx, "Salt")
    hist = catalog.list_price_history(shop.db, shop.ctx, p.id)
    assert [h.price_type for h in hist.items] == ["selling"] and hist.total == 1


def test_invalid_unit_and_category(shop, make_client, make_ctx) -> None:
    db, ctx = shop.db, shop.ctx
    _expect(InvalidInput, "INVALID_UNIT", catalog.create_product, db, ctx,
            ProductCreate(name="X", base_unit_code="tola", selling_price_paise=1))  # fmt: skip
    _expect(InvalidInput, "INVALID_CATEGORY", catalog.create_product, db, ctx,
            ProductCreate(name="X", base_unit_code="kg", selling_price_paise=1,
                          category_id=uuid.uuid4()))  # fmt: skip
    # another shop's category is reported exactly like a missing one
    other_client = make_client()
    other_user = register(other_client)["body"]["user"]["id"]
    other_shop = create_shop(other_client, "Other Store")["shop"]["id"]
    odb, octx = make_ctx(other_user, other_shop)
    foreign_cat = _category(odb, octx, "Foreign")
    _expect(InvalidInput, "INVALID_CATEGORY", catalog.create_product, db, ctx,
            ProductCreate(name="X", base_unit_code="kg", selling_price_paise=1,
                          category_id=foreign_cat.id))  # fmt: skip
    archived = _category(db, ctx, "Old")
    catalog.archive_category(db, ctx, archived.id)
    db.commit()
    _expect(InvalidInput, "CATEGORY_ARCHIVED", catalog.create_product, db, ctx,
            ProductCreate(name="X", base_unit_code="kg", selling_price_paise=1,
                          category_id=archived.id))  # fmt: skip


def test_decimal_unit_rules(shop) -> None:
    db, ctx = shop.db, shop.ctx
    _expect(InvalidInput, "LOOSE_REQUIRES_DECIMAL_UNIT", catalog.create_product, db, ctx,
            ProductCreate(name="Eggs", base_unit_code="piece", selling_price_paise=700,
                          is_loose=True))  # fmt: skip
    _expect(InvalidInput, "DECIMAL_NOT_ALLOWED_FOR_UNIT", catalog.create_product, db, ctx,
            ProductCreate(name="Eggs", base_unit_code="dozen", selling_price_paise=8400,
                          reorder_level="1.5"))  # fmt: skip
    ok = _product(db, ctx, "Eggs", base_unit_code="piece", selling_price_paise=700,
                  reorder_level="30.000")  # fmt: skip
    assert ok.reorder_level == Decimal("30.000")
    # changing to a counted unit must respect the existing is_loose flag
    loose = _product(db, ctx, "Rice", is_loose=True)
    _expect(InvalidInput, "LOOSE_REQUIRES_DECIMAL_UNIT", catalog.update_product, db, ctx,
            loose.id, ProductUpdate(version=1, base_unit_code="packet"))  # fmt: skip


def test_duplicate_names_and_barcodes(shop) -> None:
    db, ctx = shop.db, shop.ctx
    p = _product(db, ctx, "Tata Salt 1kg", base_unit_code="packet", barcode="8901058000017")
    _expect(Conflict, "PRODUCT_NAME_TAKEN", catalog.create_product, db, ctx,
            ProductCreate(name="TATA SALT 1KG", base_unit_code="packet",
                          selling_price_paise=2800))  # fmt: skip
    _expect(Conflict, "BARCODE_TAKEN", catalog.create_product, db, ctx,
            ProductCreate(name="Other Salt", base_unit_code="packet", selling_price_paise=2500,
                          barcode="8901058000017"))  # fmt: skip
    catalog.archive_product(db, ctx, p.id)
    db.commit()
    # name becomes reusable; the barcode stays reserved by the archived product
    reused = _product(db, ctx, "Tata Salt 1kg", base_unit_code="packet")
    assert reused.id != p.id
    _expect(Conflict, "BARCODE_RESERVED_BY_ARCHIVED", catalog.update_product, db, ctx,
            reused.id, ProductUpdate(version=reused.version, barcode="8901058000017"))  # fmt: skip


def test_unique_index_race_is_mapped_to_conflict(shop, monkeypatch) -> None:
    """If two requests pass the pre-check at once, the unique index still yields a clean 409
    and the transaction stays usable (savepoint rolled back)."""
    db, ctx = shop.db, shop.ctx
    _product(db, ctx, "Poha")
    monkeypatch.setattr(catalog, "_product_name_in_use", lambda *a, **k: False)
    _expect(Conflict, "PRODUCT_NAME_TAKEN", catalog.create_product, db, ctx,
            ProductCreate(name="poha", base_unit_code="kg", selling_price_paise=1))  # fmt: skip
    assert _product(db, ctx, "Besan").name == "Besan"  # session still works


def test_optimistic_concurrency_and_update(shop) -> None:
    db, ctx = shop.db, shop.ctx
    p = _product(db, ctx, "Sooji")
    updated = catalog.update_product(db, ctx, p.id, ProductUpdate(version=1, name_hi="सूजी"))
    db.commit()
    assert updated.version == 2 and updated.name_hi == "सूजी"
    _expect(Conflict, "VERSION_CONFLICT", catalog.update_product, db, ctx, p.id,
            ProductUpdate(version=1, name="Rava"))  # fmt: skip
    unchanged = catalog.update_product(db, ctx, p.id, ProductUpdate(version=2, name_hi="सूजी"))
    assert unchanged.version == 2  # a no-op update does not bump the version


def test_archived_product_behaviour(shop) -> None:
    db, ctx = shop.db, shop.ctx
    p = _product(db, ctx, "Old Biscuit", base_unit_code="packet")
    archived = catalog.archive_product(db, ctx, p.id)
    db.commit()
    assert archived.archived_at is not None and archived.version == 2
    assert catalog.get_product(db, ctx, p.id).archived_at is not None  # readable by id
    assert p.id not in {i.id for i in catalog.list_products(db, ctx, ProductListParams()).items}
    with_archived = catalog.list_products(db, ctx, ProductListParams(include_archived=True))
    assert p.id in {i.id for i in with_archived.items}
    for fn, args in (
        (catalog.update_product, (p.id, ProductUpdate(version=2, name="New"))),
        (catalog.update_prices, (p.id, ProductPriceUpdate(version=2, selling_price_paise=1))),
        (catalog.add_alias, (p.id, ProductAliasCreate(alias_text="parle"))),
    ):
        _expect(Conflict, "PRODUCT_ARCHIVED", fn, db, ctx, *args)
    _expect(Conflict, "ALREADY_ARCHIVED", catalog.archive_product, db, ctx, p.id)


def test_search_filter_and_pagination(shop) -> None:
    db, ctx = shop.db, shop.ctx
    dairy = _category(db, ctx, "Dairy")
    milk = _product(db, ctx, "Amul Gold Milk", base_unit_code="l", name_hi="दूध",
                    category_id=dairy.id, barcode="8901262010016")  # fmt: skip
    _product(db, ctx, "Amul Butter", base_unit_code="packet", category_id=dairy.id)
    sugar = _product(db, ctx, "Sugar")
    catalog.add_alias(db, ctx, sugar.id, ProductAliasCreate(alias_text="Cheeni"))
    db.commit()
    for name in ("Biscuit A", "Biscuit B", "Biscuit C"):
        _product(db, ctx, name, base_unit_code="packet")

    def search(**kw):
        return catalog.list_products(db, ctx, ProductListParams(**kw))

    assert {i.name for i in search(q="amul").items} == {"Amul Gold Milk", "Amul Butter"}
    assert [i.id for i in search(q="दूध").items] == [milk.id]  # Hindi name
    assert [i.id for i in search(q="CHEENI!").items] == [sugar.id]  # alias, normalised
    assert [i.id for i in search(q="8901262010016").items] == [milk.id]  # exact barcode
    assert search(q="89012620").total == 0  # barcode match is exact, not partial
    assert {i.name for i in search(category_id=dairy.id).items} == {"Amul Gold Milk", "Amul Butter"}
    assert search(q="%").total == 0 and search(q="_").total == 0  # wildcards are literal
    page1 = search(q="biscuit", limit=2, offset=0)
    page2 = search(q="biscuit", limit=2, offset=2)
    assert page1.total == page2.total == 3
    assert [i.name for i in page1.items + page2.items] == ["Biscuit A", "Biscuit B", "Biscuit C"]


# ----------------------------------------------------------------------------- aliases
def test_alias_normalisation_duplicates_and_removal(shop) -> None:
    db, ctx = shop.db, shop.ctx
    p = _product(db, ctx, "Sugar Loose", is_loose=True)
    a = catalog.add_alias(
        db, ctx, p.id, ProductAliasCreate(alias_text="  Cheeni ", language="hinglish")
    )
    h = catalog.add_alias(db, ctx, p.id, ProductAliasCreate(alias_text="शक्कर", language="hi"))
    db.commit()
    alias_rows = db.execute(select(ProductAlias).where(ProductAlias.product_id == p.id)).scalars()
    stored = {r.alias_text: (r.normalized_text, r.phonetic_key, r.source) for r in alias_rows}
    assert stored == {"Cheeni": ("cheeni", None, "manual"), "शक्कर": ("शक्कर", None, "manual")}
    _expect(Conflict, "ALIAS_EXISTS", catalog.add_alias, db, ctx, p.id,
            ProductAliasCreate(alias_text="CHEENI!!"))  # fmt: skip
    assert [x.alias_text for x in catalog.list_aliases(db, ctx, p.id).items] == ["Cheeni", "शक्कर"]
    catalog.remove_alias(db, ctx, p.id, a.id)
    db.commit()
    assert [x.id for x in catalog.list_aliases(db, ctx, p.id).items] == [h.id]
    _expect(NotFound, "NOT_FOUND", catalog.remove_alias, db, ctx, p.id, a.id)
    # the same alias may belong to two different products (disambiguation later)
    other = _product(db, ctx, "Sugar Cubes", base_unit_code="packet")
    catalog.add_alias(db, ctx, other.id, ProductAliasCreate(alias_text="cheeni"))
    db.commit()
    _expect(NotFound, "NOT_FOUND", catalog.remove_alias, db, ctx, other.id, h.id)  # wrong product


# ----------------------------------------------------------------------------- prices
def test_price_updates_and_history(shop) -> None:
    db, ctx = shop.db, shop.ctx
    p = _product(db, ctx, "Toor Dal", default_cost_price_paise=12000, selling_price_paise=14000)
    r = catalog.update_prices(
        db, ctx, p.id, ProductPriceUpdate(version=1, selling_price_paise=14500)
    )
    db.commit()
    assert r.selling_price_paise == 14500 and r.version == 2
    # unchanged price: no history row, version untouched
    same = catalog.update_prices(db, ctx, p.id, ProductPriceUpdate(
        version=2, selling_price_paise=14500, default_cost_price_paise=12000))  # fmt: skip
    db.commit()
    assert same.version == 2
    both = catalog.update_prices(db, ctx, p.id, ProductPriceUpdate(
        version=2, selling_price_paise=15000, default_cost_price_paise=12500))  # fmt: skip
    db.commit()
    assert both.version == 3 and both.default_cost_price_paise == 12500
    hist = catalog.list_price_history(db, ctx, p.id)
    assert hist.total == 5 and hist.costs_visible
    assert [(h.price_type, h.price_paise) for h in hist.items][:2] in (
        [("selling", 15000), ("cost", 12500)], [("cost", 12500), ("selling", 15000)])  # fmt: skip
    selling_only = catalog.list_price_history(db, ctx, p.id, price_type="selling")
    assert [h.price_paise for h in selling_only.items] == [15000, 14500, 14000]
    _expect(Conflict, "VERSION_CONFLICT", catalog.update_prices, db, ctx, p.id,
            ProductPriceUpdate(version=2, selling_price_paise=1))  # fmt: skip
    assert catalog.list_price_history(db, ctx, p.id, limit=2, offset=0).total == 5


# ----------------------------------------------------------------------------- roles
def test_staff_sees_no_costs_and_cannot_manage(shop, make_ctx) -> None:
    db, ctx = shop.db, shop.ctx
    cat = _category(db, ctx, "Pulses")
    p = _product(db, ctx, "Moong Dal", default_cost_price_paise=9000, category_id=cat.id)
    catalog.update_prices(
        db, ctx, p.id, ProductPriceUpdate(version=1, default_cost_price_paise=9200)
    )
    db.commit()
    sdb, staff = make_ctx(shop.owner["user_id"], shop.owner["shop_id"], role="staff")
    viewed = catalog.get_product(sdb, staff, p.id)
    assert viewed.default_cost_price_paise is None and viewed.costs_visible is False
    listed = catalog.list_products(sdb, staff, ProductListParams(q="moong")).items[0]
    assert listed.default_cost_price_paise is None
    hist = catalog.list_price_history(sdb, staff, p.id)
    assert {h.price_type for h in hist.items} == {"selling"} and hist.total == 1
    assert "9000" not in hist.model_dump_json() and "9200" not in hist.model_dump_json()
    with pytest.raises(PermissionDenied):
        catalog.list_price_history(sdb, staff, p.id, price_type="cost")
    denied = [
        (catalog.create_category, (CategoryCreate(name="X"),)),
        (catalog.update_category, (cat.id, CategoryUpdate(name="Y"))),
        (catalog.archive_category, (cat.id,)),
        (
            catalog.create_product,
            (ProductCreate(name="X", base_unit_code="kg", selling_price_paise=1),),
        ),
        (catalog.update_product, (p.id, ProductUpdate(version=2, name="Z"))),
        (catalog.archive_product, (p.id,)),
        (catalog.add_alias, (p.id, ProductAliasCreate(alias_text="mung"))),
        (catalog.update_prices, (p.id, ProductPriceUpdate(version=2, selling_price_paise=1))),
    ]
    for fn, args in denied:
        with pytest.raises(PermissionDenied):
            fn(sdb, staff, *args)
    # staff can still read categories, products, aliases and units
    assert catalog.list_categories(sdb, staff).total >= 1
    assert catalog.list_aliases(sdb, staff, p.id).items == []


def test_admin_has_full_catalog_access(shop, make_ctx) -> None:
    adb, admin = make_ctx(shop.owner["user_id"], shop.owner["shop_id"], role="admin")
    p = _product(adb, admin, "Jaggery", default_cost_price_paise=5000)
    assert p.costs_visible and p.default_cost_price_paise == 5000
    catalog.update_prices(
        adb, admin, p.id, ProductPriceUpdate(version=1, default_cost_price_paise=5100)
    )
    adb.commit()
    assert catalog.list_price_history(adb, admin, p.id, price_type="cost").total == 2


# ----------------------------------------------------------------------------- tenant isolation
def test_cross_shop_ids_are_not_found(shop, make_client, make_ctx) -> None:
    db, ctx = shop.db, shop.ctx
    cat = _category(db, ctx, "Private Category")
    p = _product(db, ctx, "Private Product", category_id=cat.id)
    alias = catalog.add_alias(db, ctx, p.id, ProductAliasCreate(alias_text="secret"))
    db.commit()
    intruder = make_client()
    uid = register(intruder)["body"]["user"]["id"]
    sid = create_shop(intruder, "Intruder Shop")["shop"]["id"]
    idb, ictx = make_ctx(uid, sid)
    attempts = [
        (catalog.get_category, (cat.id,)),
        (catalog.update_category, (cat.id, CategoryUpdate(name="Mine"))),
        (catalog.archive_category, (cat.id,)),
        (catalog.get_product, (p.id,)),
        (catalog.update_product, (p.id, ProductUpdate(version=1, name="Mine"))),
        (catalog.archive_product, (p.id,)),
        (catalog.list_aliases, (p.id,)),
        (catalog.add_alias, (p.id, ProductAliasCreate(alias_text="mine"))),
        (catalog.remove_alias, (p.id, alias.id)),
        (catalog.list_price_history, (p.id,)),
        (catalog.update_prices, (p.id, ProductPriceUpdate(version=1, selling_price_paise=1))),
    ]
    for fn, args in attempts:
        with pytest.raises(NotFound):
            fn(idb, ictx, *args)
        idb.rollback()
    assert catalog.list_products(idb, ictx, ProductListParams(q="private")).total == 0
    assert catalog.list_categories(idb, ictx).total == 0
    # the victim's data is untouched
    assert catalog.get_product(db, ctx, p.id).name == "Private Product"


# ----------------------------------------------------------------------------- audit
def test_audit_events_recorded(shop) -> None:
    db, ctx = shop.db, shop.ctx
    cat = _category(db, ctx, "Spices")
    catalog.update_category(db, ctx, cat.id, CategoryUpdate(sort_order=5))
    p = _product(db, ctx, "Haldi", category_id=cat.id, default_cost_price_paise=100)
    catalog.update_product(db, ctx, p.id, ProductUpdate(version=1, name_hi="हल्दी"))
    a = catalog.add_alias(db, ctx, p.id, ProductAliasCreate(alias_text="turmeric"))
    catalog.remove_alias(db, ctx, p.id, a.id)
    catalog.update_prices(db, ctx, p.id, ProductPriceUpdate(version=2, selling_price_paise=999))
    catalog.archive_product(db, ctx, p.id)
    catalog.archive_category(db, ctx, cat.id)
    db.commit()
    actions = db.execute(
        select(AuditLog.action, func.count()).where(AuditLog.shop_id == ctx.shop_id)
        .group_by(AuditLog.action)
    ).all()  # fmt: skip
    found = {a for a, _ in actions}
    assert {
        "category.created", "category.updated", "category.archived", "product.created",
        "product.updated", "product.alias_added", "product.alias_removed",
        "product.price_changed", "product.archived",
    } <= found  # fmt: skip
    price_event = db.execute(
        select(AuditLog).where(AuditLog.shop_id == ctx.shop_id,
                               AuditLog.action == "product.price_changed")
    ).scalar_one()  # fmt: skip
    assert price_event.actor_user_id == ctx.user_id and price_event.entity_id == p.id
    assert price_event.before["selling_price_paise"] == 4400
    assert price_event.after["selling_price_paise"] == 999
