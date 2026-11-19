"""Unit tests for catalogue schemas (validation and staff-safe serialisation; no database).

Schemas are not the security boundary; these tests cover shape/value validation only.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.catalog.schemas import (
    MAX_PAISE,
    CategoryCreate,
    CategoryUpdate,
    ProductAliasCreate,
    ProductAliasRead,
    ProductCreate,
    ProductListParams,
    ProductPriceListResponse,
    ProductPriceUpdate,
    ProductRead,
    ProductUpdate,
)

NOW = datetime.now(UTC)
VALID_PRODUCT = {"name": "Chini (loose)", "base_unit_code": "kg", "selling_price_paise": 4400}


def _errors(exc: pytest.ExceptionInfo[ValidationError]) -> str:
    return str(exc.value)


# ----------------------------------------------------------------------------- categories
def test_category_create_valid_and_cleaned() -> None:
    c = CategoryCreate(name="  Staples   &  Grains ", name_hi=" अनाज ", sort_order=2)
    assert c.name == "Staples & Grains"
    assert c.name_hi == "अनाज"
    assert c.sort_order == 2


@pytest.mark.parametrize("name", ["", "   ", None, "x" * 81, "bad\x00name", 123])
def test_category_create_invalid_names(name) -> None:
    with pytest.raises(ValidationError):
        CategoryCreate(name=name)


def test_category_blank_hindi_name_becomes_none() -> None:
    assert CategoryCreate(name="Dairy", name_hi="   ").name_hi is None


def test_category_update_rules() -> None:
    assert CategoryUpdate(name="Dairy").name == "Dairy"
    assert CategoryUpdate(name_hi=None).name_hi is None  # clearing the Hindi name is allowed
    with pytest.raises(ValidationError):
        CategoryUpdate()  # nothing to change
    with pytest.raises(ValidationError):
        CategoryUpdate(name=None)  # name cannot be cleared
    with pytest.raises(ValidationError):
        CategoryUpdate(sort_order=None)
    with pytest.raises(ValidationError):
        CategoryUpdate(sort_order="3")  # strict integer


# ----------------------------------------------------------------------------- unknown fields
@pytest.mark.parametrize(
    ("model", "data"),
    [
        (CategoryCreate, {"name": "Dairy", "shop_id": str(uuid.uuid4())}),
        (CategoryUpdate, {"name": "Dairy", "shop_id": str(uuid.uuid4())}),
        (ProductCreate, {**VALID_PRODUCT, "shop_id": str(uuid.uuid4())}),
        (ProductUpdate, {"version": 1, "name": "X", "shop_id": str(uuid.uuid4())}),
        (ProductPriceUpdate, {"version": 1, "selling_price_paise": 1, "shop_id": "x"}),
        (ProductAliasCreate, {"alias_text": "chini", "shop_id": "x"}),
        (ProductCreate, {**VALID_PRODUCT, "archived_at": NOW.isoformat()}),
        (ProductCreate, {**VALID_PRODUCT, "version": 5}),
        (ProductAliasCreate, {"alias_text": "chini", "normalized_text": "x"}),
        (ProductAliasCreate, {"alias_text": "chini", "source": "seed"}),
    ],
)
def test_unknown_and_server_owned_fields_rejected(model, data) -> None:
    with pytest.raises(ValidationError) as exc:
        model(**data)
    assert "extra" in _errors(exc).lower()


# ----------------------------------------------------------------------------- products
def test_product_create_valid() -> None:
    p = ProductCreate(
        **VALID_PRODUCT,
        name_hi="चीनी",
        category_id=str(uuid.uuid4()),
        is_loose=True,
        default_cost_price_paise=4000,
        reorder_level="2.500",
        barcode=" 8901234567890 ",
    )
    assert p.base_unit_code == "kg"
    assert p.reorder_level == Decimal("2.500")
    assert p.barcode == "8901234567890"
    assert isinstance(p.selling_price_paise, int)


def test_product_unit_code_normalised() -> None:
    assert ProductCreate(**{**VALID_PRODUCT, "base_unit_code": " KG "}).base_unit_code == "kg"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("name", "   "),
        ("name", "x" * 121),
        ("base_unit_code", ""),
        ("base_unit_code", "x" * 17),
        ("base_unit_code", None),
        ("category_id", "not-a-uuid"),
        ("is_loose", "yes"),
        ("barcode", "890 123"),
        ("barcode", "x" * 65),
        ("reorder_level", -1),
        ("reorder_level", 1.5),  # floats rejected for quantities
        ("reorder_level", "1.2345"),  # more than 3 decimal places
        ("reorder_level", "NaN"),
    ],
)
def test_product_create_invalid_fields(field, value) -> None:
    with pytest.raises(ValidationError):
        ProductCreate(**{**VALID_PRODUCT, field: value})


@pytest.mark.parametrize(
    "value", [-1, 1.5, 100.0, "4400", True, None, MAX_PAISE + 1, Decimal("44.00")]
)
def test_paise_must_be_non_negative_integers(value) -> None:
    with pytest.raises(ValidationError):
        ProductCreate(**{**VALID_PRODUCT, "selling_price_paise": value})


def test_paise_bounds_accepted() -> None:
    assert ProductCreate(**{**VALID_PRODUCT, "selling_price_paise": 0}).selling_price_paise == 0
    assert ProductCreate(**{**VALID_PRODUCT, "selling_price_paise": MAX_PAISE}).selling_price_paise
    assert ProductCreate(**VALID_PRODUCT).default_cost_price_paise is None


def test_product_requires_selling_price() -> None:
    with pytest.raises(ValidationError):
        ProductCreate(name="Atta", base_unit_code="kg")


# ----------------------------------------------------------------------------- product update
def test_product_update_requires_version_and_a_change() -> None:
    assert ProductUpdate(version=3, name="Atta").version == 3
    with pytest.raises(ValidationError):
        ProductUpdate(name="Atta")  # version missing
    with pytest.raises(ValidationError):
        ProductUpdate(version=3)  # nothing to change


@pytest.mark.parametrize("version", [0, -1, "2", 1.0, True, None])
def test_product_update_invalid_version(version) -> None:
    with pytest.raises(ValidationError):
        ProductUpdate(version=version, name="Atta")


@pytest.mark.parametrize("field", ["selling_price_paise", "default_cost_price_paise"])
def test_product_update_rejects_price_fields(field) -> None:
    with pytest.raises(ValidationError) as exc:
        ProductUpdate.model_validate({"version": 1, "name": "Atta", field: 100})
    assert "/prices" in _errors(exc)


def test_product_update_nullability() -> None:
    cleared = ProductUpdate(
        version=1, name_hi=None, category_id=None, reorder_level=None, barcode=None
    )
    assert cleared.model_fields_set == {
        "version",
        "name_hi",
        "category_id",
        "reorder_level",
        "barcode",
    }
    for field in ("name", "base_unit_code", "is_loose"):
        with pytest.raises(ValidationError):
            ProductUpdate.model_validate({"version": 1, field: None})


# ----------------------------------------------------------------------------- prices
def test_price_update_accepts_prices() -> None:
    both = ProductPriceUpdate(version=2, selling_price_paise=4500, default_cost_price_paise=4100)
    assert (both.selling_price_paise, both.default_cost_price_paise) == (4500, 4100)
    only_selling = ProductPriceUpdate(version=2, selling_price_paise=0)
    assert only_selling.model_fields_set == {"version", "selling_price_paise"}


@pytest.mark.parametrize(
    "data",
    [
        {"version": 1},  # no price
        {"selling_price_paise": 100},  # no version
        {"version": 1, "selling_price_paise": None},  # null not allowed
        {"version": 1, "default_cost_price_paise": -5},
        {"version": 1, "selling_price_paise": 10.5},
        {"version": 1, "selling_price_paise": "100"},
    ],
)
def test_price_update_invalid(data) -> None:
    with pytest.raises(ValidationError):
        ProductPriceUpdate.model_validate(data)


# ----------------------------------------------------------------------------- aliases
def test_alias_valid_and_cleaned() -> None:
    a = ProductAliasCreate(alias_text="  cheeni   chini ", language="hinglish")
    assert a.alias_text == "cheeni chini"
    assert ProductAliasCreate(alias_text="शक्कर").language is None


@pytest.mark.parametrize("alias", ["", "   ", "!!!", "।", None, "x" * 121, "a\x07b"])
def test_alias_invalid(alias) -> None:
    with pytest.raises(ValidationError):
        ProductAliasCreate(alias_text=alias)


def test_alias_invalid_language() -> None:
    with pytest.raises(ValidationError):
        ProductAliasCreate(alias_text="chini", language="fr")


def test_alias_read_hides_internal_keys() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        alias_text="Chini",
        normalized_text="chini",
        phonetic_key="XN",
        language="hinglish",
        source="manual",
        created_at=NOW,
    )
    dumped = ProductAliasRead.model_validate(row).model_dump()
    assert "normalized_text" not in dumped and "phonetic_key" not in dumped


# ----------------------------------------------------------------------------- staff-safe output
def _product_row(**overrides):
    base = dict(
        id=uuid.uuid4(),
        name="Chini",
        name_hi=None,
        category_id=None,
        base_unit_code="kg",
        is_loose=True,
        selling_price_paise=4400,
        default_cost_price_paise=4000,
        reorder_level=Decimal("5.000"),
        barcode=None,
        archived_at=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return SimpleNamespace(**(base | overrides))


def test_product_read_hides_cost_for_staff() -> None:
    staff_view = ProductRead.from_model(_product_row(), include_costs=False)
    assert staff_view.default_cost_price_paise is None
    assert staff_view.costs_visible is False
    assert "4000" not in staff_view.model_dump_json()
    owner_view = ProductRead.from_model(_product_row(), include_costs=True)
    assert owner_view.default_cost_price_paise == 4000 and owner_view.costs_visible is True


def test_product_read_serialises_quantity_as_decimal_string() -> None:
    js = ProductRead.from_model(_product_row(), include_costs=True).model_dump(mode="json")
    assert js["reorder_level"] == "5.000"
    assert js["selling_price_paise"] == 4400


def _price_row(price_type: str, paise: int):
    return SimpleNamespace(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        price_type=price_type,
        price_paise=paise,
        effective_from=NOW,
        set_by_user_id=uuid.uuid4(),
        source="manual",
        created_at=NOW,
    )


def test_price_list_drops_cost_rows_for_staff() -> None:
    rows = [_price_row("selling", 4400), _price_row("cost", 4000), _price_row("selling", 4500)]
    staff = ProductPriceListResponse.from_models(
        rows, total=2, limit=50, offset=0, include_costs=False
    )
    assert [i.price_type for i in staff.items] == ["selling", "selling"]
    assert staff.costs_visible is False and "4000" not in staff.model_dump_json()
    owner = ProductPriceListResponse.from_models(
        rows, total=3, limit=50, offset=0, include_costs=True
    )
    assert len(owner.items) == 3 and owner.costs_visible is True


# ----------------------------------------------------------------------------- list params
def test_product_list_params() -> None:
    p = ProductListParams(q="  chini  ", limit=20)
    assert p.q == "chini" and p.offset == 0 and p.include_archived is False
    assert ProductListParams(q="   ").q is None
    for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 121}, {"shop_id": "x"}):
        with pytest.raises(ValidationError):
            ProductListParams(**bad)


@pytest.mark.parametrize(("raw", "expected"), [("30", "30.000"), (30, "30.000"), ("2.5", "2.500"),
                                               ("0.250", "0.250"), ("0", "0.000")])  # fmt: skip
def test_quantities_normalised_to_three_decimal_places(raw, expected) -> None:
    p = ProductCreate(**VALID_PRODUCT, reorder_level=raw)
    assert str(p.reorder_level) == expected
    assert (
        ProductUpdate(version=1, reorder_level=raw).model_dump(mode="json")["reorder_level"]
        == expected
    )
