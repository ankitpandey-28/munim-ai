"""Idempotency, concurrency, rollback and the business-transaction (ledger) framework."""

import os
import threading
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.database.session import set_tenant_context
from app.modules.audit.models import AuditLog
from app.modules.ledger import service as ledger
from app.modules.ledger.models import BusinessTransaction
from app.modules.shops.models import Shop
from tests.integration.conftest import register


def _shop_count(super_engine, user_id) -> int:
    with super_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM shops WHERE created_by_user_id = :u"), {"u": user_id}
        ).scalar_one()


# ----------------------------------------------------------------------------- idempotency
def test_duplicate_request_replays_original_response(make_client, super_engine) -> None:
    client = make_client()
    user_id = register(client)["body"]["user"]["id"]
    key = {"Idempotency-Key": os.urandom(12).hex()}
    first = client.post("/api/v1/shops", json={"name": "Once Only"}, headers=key)
    second = client.post("/api/v1/shops", json={"name": "Once Only"}, headers=key)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert _shop_count(super_engine, user_id) == 1


def test_same_key_different_body_is_rejected(make_client) -> None:
    client = make_client()
    register(client)
    key = {"Idempotency-Key": os.urandom(12).hex()}
    assert client.post("/api/v1/shops", json={"name": "A"}, headers=key).status_code == 201
    reused = client.post("/api/v1/shops", json={"name": "B"}, headers=key)
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_keys_are_scoped_per_user(make_client, super_engine) -> None:
    key = {"Idempotency-Key": "shared-key-0001"}
    a, b = make_client(), make_client()
    a_id = register(a)["body"]["user"]["id"]
    b_id = register(b)["body"]["user"]["id"]
    assert a.post("/api/v1/shops", json={"name": "Same"}, headers=key).status_code == 201
    assert b.post("/api/v1/shops", json={"name": "Same"}, headers=key).status_code == 201
    assert _shop_count(super_engine, a_id) == _shop_count(super_engine, b_id) == 1


def test_concurrent_duplicates_execute_once(make_client, super_engine, settings) -> None:
    """Two simultaneous identical requests: one executes, the other waits on the unique index
    and then replays the committed response."""
    client = make_client()
    user_id = register(client)["body"]["user"]["id"]
    cookie = client.cookies.get(settings.session_cookie_name)
    key = os.urandom(12).hex()
    results: list[tuple[int, dict]] = []
    barrier = threading.Barrier(4)

    def worker():
        c = make_client()
        c.cookies.set(settings.session_cookie_name, cookie)
        barrier.wait()
        r = c.post("/api/v1/shops", json={"name": "Race"}, headers={"Idempotency-Key": key})
        results.append((r.status_code, r.json()))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert [code for code, _ in results] == [201] * 4
    assert len({body["shop"]["id"] for _, body in results}) == 1
    assert _shop_count(super_engine, user_id) == 1


# ----------------------------------------------------------------------------- ledger framework
@pytest.fixture
def shop_session(owner, pg):
    """An ORM session as munim_app with the owner's verified tenant context."""
    from sqlalchemy import create_engine

    engine = create_engine(pg.app_url)
    session = Session(engine, expire_on_commit=False)
    user_id = uuid.UUID(owner["user_id"])
    shop_id = uuid.UUID(owner["shop_id"])
    set_tenant_context(session, user_id=user_id, shop_id=shop_id)
    yield session, ledger.Actor(user_id=user_id, shop_id=shop_id)
    session.rollback()
    session.close()
    engine.dispose()


@pytest.fixture
def reversible_opening_balance():
    calls = []
    ledger.register_reversal_handler(
        "opening_balance", lambda db, orig, rev: calls.append((orig.id, rev.id))
    )
    yield calls
    ledger.unregister_reversal_handler("opening_balance")


def test_post_transaction_records_actor_and_audit(shop_session) -> None:
    db, actor = shop_session
    txn = ledger.post_transaction(db, actor, "opening_balance", ledger.PostOptions(source="system"))
    db.commit()
    stored = db.get(BusinessTransaction, txn.id)
    assert stored.initiated_by_user_id == actor.user_id
    assert stored.shop_id == actor.shop_id
    assert stored.source == "system" and stored.request_id is None
    tz = db.execute(select(Shop.timezone).where(Shop.id == actor.shop_id)).scalar_one()
    assert tz == "Asia/Kolkata" and stored.business_date is not None
    audit_count = db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.transaction_id == txn.id)
    ).scalar_one()
    assert audit_count == 1


def test_reversal_is_linked_and_only_once(shop_session, reversible_opening_balance) -> None:
    db, actor = shop_session
    original = ledger.post_transaction(db, actor, "opening_balance")
    db.commit()
    reversal = ledger.reverse_transaction(db, actor, original.id, reason="entered twice")
    db.commit()
    db.refresh(original)
    assert original.status == "reversed"
    assert original.reversed_by_transaction_id == reversal.id
    assert reversal.reverses_transaction_id == original.id and reversal.txn_type == "reversal"
    assert reversible_opening_balance == [(original.id, reversal.id)]
    with pytest.raises(Conflict):
        ledger.reverse_transaction(db, actor, original.id, reason="again")
    db.rollback()
    with pytest.raises(ledger.LedgerError):
        ledger.reverse_transaction(db, actor, reversal.id, reason="undo the undo")
    db.rollback()


def test_reversal_requires_reason_and_registered_handler(shop_session) -> None:
    db, actor = shop_session
    txn = ledger.post_transaction(db, actor, "credit_given")
    db.commit()
    with pytest.raises(ledger.LedgerError):
        ledger.reverse_transaction(db, actor, txn.id, reason="  ")
    with pytest.raises(ledger.LedgerError) as exc_info:
        ledger.reverse_transaction(db, actor, txn.id, reason="mistake")
    assert exc_info.value.code == "REVERSAL_NOT_SUPPORTED"
    db.rollback()


def test_failed_operation_rolls_back_everything(shop_session) -> None:
    db, actor = shop_session
    before = db.execute(select(func.count()).select_from(BusinessTransaction)).scalar_one()
    txn = ledger.post_transaction(db, actor, "opening_balance")
    txn_id = txn.id
    db.rollback()  # e.g. a child-row insert failed
    assert db.get(BusinessTransaction, txn_id) is None
    after = db.execute(select(func.count()).select_from(BusinessTransaction)).scalar_one()
    assert after == before
    audit_rows = db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.transaction_id == txn_id)
    ).scalar_one()
    assert audit_rows == 0


def test_tenant_context_survives_commit(shop_session) -> None:
    """The after_begin hook re-applies the context in every new transaction."""
    db, actor = shop_session
    ledger.post_transaction(db, actor, "opening_balance")
    db.commit()
    ledger.post_transaction(db, actor, "opening_balance")
    db.commit()
    assert db.execute(text("SELECT app_current_shop_id()")).scalar_one() == actor.shop_id


def test_ledger_cannot_post_into_another_shop(shop_session, make_client) -> None:
    db, actor = shop_session
    other = make_client()
    register(other)
    from tests.integration.conftest import create_shop

    other_shop = uuid.UUID(create_shop(other, "Other")["shop"]["id"])
    with pytest.raises(Exception) as exc_info:
        ledger.post_transaction(
            db, ledger.Actor(user_id=actor.user_id, shop_id=other_shop), "opening_balance"
        )
        db.flush()
    db.rollback()
    assert (
        "row-level security" in str(exc_info.value)
        or "NoResultFound" in type(exc_info.value).__name__
    )
