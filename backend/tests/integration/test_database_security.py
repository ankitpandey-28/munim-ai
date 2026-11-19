"""Database-level guarantees on real PostgreSQL: migrations, roles, RLS, grants, immutability.

These run as the actual runtime role (munim_app) and owner role (munim_owner).
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from app.models.registry import (
    GLOBAL_TABLES,
    SPECIAL_RLS_TABLES,
    STANDARD_TENANT_TABLES,
    import_all_models,
)
from app.shared.ids import uuid7
from tests.integration.conftest import run_alembic


# ----------------------------------------------------------------------------- helpers
def _ctx(conn, user_id=None, shop_id=None) -> None:
    conn.execute(
        text(
            "SELECT set_config('app.current_user_id', :u, true), "
            "set_config('app.current_shop_id', :s, true)"
        ),
        {"u": str(user_id) if user_id else "", "s": str(shop_id) if shop_id else ""},
    )


def _make_user(conn) -> uuid.UUID:
    uid = uuid7()
    phone = "+9188" + str(uuid.uuid4().int)[:8]
    conn.execute(
        text("INSERT INTO users (id, phone, name, password_hash) VALUES (:i, :p, 'T', 'x')"),
        {"i": uid, "p": phone},
    )
    return uid


def _make_shop(app_engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    """Create user + shop + owner membership through RLS, exactly as the API does."""
    with app_engine.begin() as conn:
        uid = _make_user(conn)
        sid = uuid7()
        _ctx(conn, uid, sid)
        conn.execute(
            text("INSERT INTO shops (id, name, created_by_user_id) VALUES (:s, 'Shop', :u)"),
            {"s": sid, "u": uid},
        )
        conn.execute(
            text(
                "INSERT INTO shop_members (id, shop_id, user_id, role) VALUES (:i, :s, :u, 'owner')"
            ),
            {"i": uuid7(), "s": sid, "u": uid},
        )
    return uid, sid


def _post_txn(conn, shop_id, user_id, txn_type="opening_balance") -> uuid.UUID:
    tid = uuid7()
    conn.execute(
        text(
            "INSERT INTO business_transactions (id, shop_id, txn_type, business_date, occurred_at,"
            " initiated_by_user_id) VALUES (:t, :s, :ty, :d, :o, :u)"
        ),
        {
            "t": tid,
            "s": shop_id,
            "ty": txn_type,
            "d": date.today(),
            "o": datetime.now(UTC),
            "u": user_id,
        },
    )
    return tid


# ----------------------------------------------------------------------------- migrations
def test_migrations_match_models_and_are_at_head(pg) -> None:
    check = run_alembic(pg, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert "No new upgrade operations detected" in check.stdout + check.stderr
    current = run_alembic(pg, "current")
    assert "0004 (head)" in current.stdout + current.stderr


def test_every_model_table_exists(app_engine) -> None:
    Base = import_all_models()
    with app_engine.connect() as conn:
        existing = set(
            conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            ).scalars()
        )
    assert set(Base.metadata.tables) <= existing
    assert len(Base.metadata.tables) == 40


# ----------------------------------------------------------------------------- roles
def test_runtime_and_owner_role_attributes(app_engine, owner_engine) -> None:
    q = text(
        "SELECT session_user, current_database(), rolsuper, rolbypassrls, rolinherit,"
        " rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
    )
    with app_engine.connect() as conn:
        app = conn.execute(q).one()
    with owner_engine.connect() as conn:
        owner = conn.execute(q).one()
    assert app[:2] == ("munim_app", "munim_ai")
    assert app[2:] == (False, False, False, False, False)
    assert owner[:2] == ("munim_owner", "munim_ai")
    assert owner.rolsuper is False and owner.rolbypassrls is False


def test_runtime_role_owns_nothing_and_cannot_create(app_engine) -> None:
    with app_engine.connect() as conn:
        owned = conn.execute(
            text("SELECT count(*) FROM pg_class WHERE relowner = 'munim_app'::regrole")
        ).scalar_one()
        assert owned == 0
        assert (
            conn.execute(text("SELECT has_schema_privilege('public', 'CREATE')")).scalar_one()
            is False
        )
        assert (
            conn.execute(
                text("SELECT has_database_privilege(current_database(), 'TEMPORARY')")
            ).scalar_one()
            is False
        )
    with app_engine.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(text("CREATE TABLE should_fail (id int)"))


def test_tables_owned_by_migration_role(owner_engine) -> None:
    with owner_engine.connect() as conn:
        not_owned = (
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                    " AND tableowner <> 'munim_owner'"
                )
            )
            .scalars()
            .all()
        )
    assert not_owned == []


# ----------------------------------------------------------------------------- RLS catalogue
def test_rls_enabled_and_forced_on_every_tenant_table(app_engine) -> None:
    with app_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
                " WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
            )
        ).all()
    flags = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows}
    for table in STANDARD_TENANT_TABLES + SPECIAL_RLS_TABLES:
        assert flags[table] == (True, True), table
    for table in GLOBAL_TABLES:
        assert flags[table] == (False, False), table  # global tables are not tenant-scoped


def test_no_delete_on_financial_or_audit_tables(app_engine) -> None:
    with app_engine.connect() as conn:
        deletable = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.role_table_grants"
                    " WHERE grantee = 'munim_app' AND privilege_type = 'DELETE'"
                )
            ).scalars()
        )
        forbidden_privs = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.role_table_grants"
                " WHERE grantee='munim_app'"
                " AND privilege_type IN ('TRUNCATE', 'REFERENCES', 'TRIGGER')"
            )
        ).scalar_one()
    assert deletable == {
        "auth_sessions",
        "login_attempts",
        "product_aliases",
        "customer_aliases",
        "supplier_products",
    }
    assert forbidden_privs == 0


# ----------------------------------------------------------------------------- isolation
def test_missing_context_fails_closed(app_engine) -> None:
    _make_shop(app_engine)
    with app_engine.begin() as conn:
        for table in (
            "shops",
            "shop_members",
            "shop_settings",
            "business_transactions",
            "audit_logs",
        ):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
        _ctx(conn)  # explicitly empty settings must also fail closed (not error)
        assert conn.execute(text("SELECT count(*) FROM shops")).scalar_one() == 0


def test_cross_shop_reads_are_invisible(app_engine) -> None:
    user_a, shop_a = _make_shop(app_engine)
    user_b, shop_b = _make_shop(app_engine)
    with app_engine.begin() as conn:
        _ctx(conn, user_a, shop_a)
        _post_txn(conn, shop_a, user_a)
    with app_engine.begin() as conn:
        _ctx(conn, user_b, shop_b)
        assert (
            conn.execute(
                text("SELECT count(*) FROM business_transactions WHERE shop_id = :a"), {"a": shop_a}
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM shops WHERE id = :a"), {"a": shop_a}
            ).scalar_one()
            == 0
        )
        visible = conn.execute(text("SELECT id FROM shops")).scalars().all()
        assert visible == [shop_b]


def test_cross_shop_writes_are_rejected(app_engine) -> None:
    _user_a, shop_a = _make_shop(app_engine)
    user_b, shop_b = _make_shop(app_engine)
    # WITH CHECK: shop B's context cannot insert rows for shop A.
    with app_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        with conn.begin():
            _ctx(conn, user_b, shop_b)
            _post_txn(conn, shop_a, user_b)
    assert "row-level security" in str(exc_info.value.orig)
    # USING: shop B's context cannot update shop A's rows (0 rows affected).
    with app_engine.begin() as conn:
        _ctx(conn, user_b, shop_b)
        updated = conn.execute(
            text("UPDATE shops SET name = 'hacked' WHERE id = :a"), {"a": shop_a}
        )
        assert updated.rowcount == 0


def test_composite_tenant_fk_blocks_cross_shop_links(app_engine) -> None:
    user_a, shop_a = _make_shop(app_engine)
    user_b, shop_b = _make_shop(app_engine)
    with app_engine.begin() as conn:
        _ctx(conn, user_a, shop_a)
        txn_a = _post_txn(conn, shop_a, user_a)
    # Even with a valid shop B context, a shop B reversal cannot point at shop A's transaction.
    with app_engine.connect() as conn, pytest.raises(IntegrityError):
        with conn.begin():
            _ctx(conn, user_b, shop_b)
            conn.execute(
                text(
                    "INSERT INTO business_transactions (id, shop_id, txn_type,"
                    " reverses_transaction_id, business_date, occurred_at,"
                    " initiated_by_user_id, reason)"
                    " VALUES (:t, :s, 'reversal', :orig, :d, now(), :u, 'x')"
                ),
                {"t": uuid7(), "s": shop_b, "orig": txn_a, "d": date.today(), "u": user_b},
            )


def test_force_rls_binds_the_owner_role_too(app_engine, owner_engine) -> None:
    _make_shop(app_engine)
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM shops")).scalar_one() == 0


def test_membership_self_policy(app_engine) -> None:
    """A user sees their own memberships across shops, but not other members of other shops."""
    user_a, shop_a = _make_shop(app_engine)
    _user_b, shop_b = _make_shop(app_engine)
    with app_engine.begin() as conn:
        _ctx(conn, user_a, None)
        rows = conn.execute(text("SELECT shop_id FROM shop_members")).scalars().all()
        assert rows == [shop_a]
        assert shop_b not in rows


# ----------------------------------------------------------------------------- immutability
def test_financial_rows_cannot_be_deleted_or_amounts_changed(app_engine, owner_engine) -> None:
    user, shop = _make_shop(app_engine)
    with app_engine.begin() as conn:
        _ctx(conn, user, shop)
        txn = _post_txn(conn, shop, user)
    # Runtime role: no DELETE privilege, no UPDATE privilege on immutable columns.
    for stmt in (
        "DELETE FROM business_transactions WHERE id = :t",
        "UPDATE business_transactions SET txn_type = 'sale' WHERE id = :t",
        "UPDATE business_transactions SET business_date = business_date - 1 WHERE id = :t",
    ):
        with app_engine.connect() as conn, pytest.raises(ProgrammingError) as exc_info:
            with conn.begin():
                _ctx(conn, user, shop)
                conn.execute(text(stmt), {"t": txn})
        assert "permission denied" in str(exc_info.value.orig)
    # Owner role: triggers still forbid it (defence in depth).
    with owner_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        with conn.begin():
            _ctx(conn, user, shop)
            conn.execute(
                text("UPDATE business_transactions SET txn_type='sale' WHERE id=:t"), {"t": txn}
            )
    assert "immutable columns" in str(exc_info.value.orig)
    with owner_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        with conn.begin():
            _ctx(conn, user, shop)
            conn.execute(text("DELETE FROM business_transactions WHERE id = :t"), {"t": txn})
    assert "append-only" in str(exc_info.value.orig)


def test_transaction_can_only_be_reversed_once(app_engine) -> None:
    user, shop = _make_shop(app_engine)
    with app_engine.begin() as conn:
        _ctx(conn, user, shop)
        original = _post_txn(conn, shop, user)

    def reverse(conn):
        rid = uuid7()
        conn.execute(
            text(
                "INSERT INTO business_transactions (id, shop_id, txn_type, reverses_transaction_id,"
                " business_date, occurred_at, initiated_by_user_id, reason)"
                " VALUES (:r, :s, 'reversal', :o, :d, now(), :u, 'wrong entry')"
            ),
            {"r": rid, "s": shop, "o": original, "d": date.today(), "u": user},
        )
        conn.execute(
            text(
                "UPDATE business_transactions SET status='reversed', reversed_by_transaction_id=:r"
                " WHERE id=:o"
            ),
            {"r": rid, "o": original},
        )

    with app_engine.begin() as conn:
        _ctx(conn, user, shop)
        reverse(conn)
    with app_engine.connect() as conn, pytest.raises(DBAPIError):
        with conn.begin():
            _ctx(conn, user, shop)
            reverse(conn)  # unique index + status trigger both refuse


def test_audit_log_is_append_only(app_engine) -> None:
    user, shop = _make_shop(app_engine)
    with app_engine.begin() as conn:
        _ctx(conn, user, shop)
        aid = uuid7()
        conn.execute(
            text(
                "INSERT INTO audit_logs (id, shop_id, actor_user_id, actor_type, action)"
                " VALUES (:a, :s, :u, 'user', 'test.event')"
            ),
            {"a": aid, "s": shop, "u": user},
        )
    for stmt in (
        "UPDATE audit_logs SET action='x' WHERE id=:a",
        "DELETE FROM audit_logs WHERE id=:a",
    ):
        with app_engine.connect() as conn, pytest.raises(ProgrammingError):
            with conn.begin():
                _ctx(conn, user, shop)
                conn.execute(text(stmt), {"a": aid})


def test_shopless_audit_rows_are_write_only(app_engine) -> None:
    with app_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO audit_logs (id, actor_type, action) VALUES (:a, 'anonymous', 'x')"),
            {"a": uuid7()},
        )
        assert (
            conn.execute(text("SELECT count(*) FROM audit_logs WHERE shop_id IS NULL")).scalar_one()
            == 0
        )


def test_units_seeded_and_read_only(app_engine) -> None:
    with app_engine.connect() as conn:
        codes = set(conn.execute(text("SELECT code FROM units")).scalars())
    assert {"kg", "g", "l", "ml", "piece", "packet", "dozen", "box"} <= codes
    with app_engine.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(text("UPDATE units SET name_en = 'x' WHERE code = 'kg'"))


def test_money_and_quantity_column_types(app_engine) -> None:
    with app_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale"
                " FROM information_schema.columns WHERE table_schema='public'"
                " AND (column_name LIKE '%\\_paise' OR column_name IN ("
                "'quantity', 'quantity_delta', 'quantity_on_hand', 'ordered_quantity',"
                " 'received_quantity'))"
            )
        ).all()
    assert rows
    for r in rows:
        if r.column_name.endswith("_paise"):
            assert r.data_type == "bigint", r
        else:
            assert (r.data_type, r.numeric_precision, r.numeric_scale) == ("numeric", 14, 3), r


def test_primary_keys_default_to_uuidv7(app_engine) -> None:
    with app_engine.connect() as conn:
        version = conn.execute(text("SELECT uuid_extract_version(uuidv7())")).scalar_one()
    assert version == 7
    assert uuid7().version == 7
