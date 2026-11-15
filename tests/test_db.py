"""SQLite: stable ids, idempotent seeding, and per-customer reads."""

from pathlib import Path

from pydantachat.db import Database, customer_id_for

ALICE = "alice@example.com"
BOB = "bob@example.com"


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.db")
    db.seed([ALICE, BOB])
    return db


def test_customer_ids_are_stable_and_case_insensitive() -> None:
    assert customer_id_for(ALICE) == customer_id_for("Alice@Example.COM")
    assert customer_id_for(ALICE) != customer_id_for(BOB)


def test_seeding_twice_does_not_duplicate(tmp_path: Path) -> None:
    db = _db(tmp_path)

    db.seed([ALICE, BOB])

    alice = db.customer_for_email(ALICE)
    assert alice is not None
    assert len(db.orders_for(alice.id)) == 3


def test_orders_are_scoped_to_one_customer(tmp_path: Path) -> None:
    db = _db(tmp_path)
    alice = db.customer_for_email(ALICE)
    bob = db.customer_for_email(BOB)
    assert alice is not None and bob is not None

    alice_orders = db.orders_for(alice.id)
    bob_orders = db.orders_for(bob.id)

    assert {order.customer_id for order in alice_orders} == {alice.id}
    assert {order.id for order in alice_orders}.isdisjoint(
        {order.id for order in bob_orders}
    )


def test_an_unknown_email_has_no_customer(tmp_path: Path) -> None:
    assert _db(tmp_path).customer_for_email("nobody@example.com") is None


def test_orders_are_newest_first(tmp_path: Path) -> None:
    db = _db(tmp_path)
    alice = db.customer_for_email(ALICE)
    assert alice is not None

    dates = [order.placed_at for order in db.orders_for(alice.id)]

    assert dates == sorted(dates, reverse=True)


def test_the_model_sees_a_formatted_total_not_customer_ids(tmp_path: Path) -> None:
    db = _db(tmp_path)
    alice = db.customer_for_email(ALICE)
    assert alice is not None

    order = db.orders_for(alice.id)[0].as_dict()

    assert order["total"].endswith(" USD")
    assert "customer_id" not in order
