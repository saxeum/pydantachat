"""The demo seeder: deterministic, idempotent, and scoped per customer."""

from datetime import date, timedelta
from pathlib import Path

from pydantachat.db import Database, customer_id_for
from pydantachat.seed import (
    MAX_TOTAL_CENTS,
    MIN_TOTAL_CENTS,
    STATUSES,
    demo_emails,
    generate_orders,
    split_orders,
)

TODAY = date(2026, 11, 15)


def _shape(orders: list) -> list[tuple[str, str, int]]:
    return [(order.placed_at, order.status, order.total_cents) for order in orders]


def test_demo_emails_use_allowlisted_addresses_first() -> None:
    emails = demo_emails(4, ["me@example.com"])

    assert emails == [
        "me@example.com",
        "demo01@example.com",
        "demo02@example.com",
        "demo03@example.com",
    ]


def test_demo_emails_are_unique() -> None:
    emails = demo_emails(12, ["me@example.com", "ME@example.com"])

    assert len(emails) == 12
    assert len(set(emails)) == 12
    assert emails[0] == "me@example.com"


def test_split_orders_adds_up() -> None:
    counts = split_orders(500, 12)

    assert len(counts) == 12
    assert sum(counts) == 500
    assert max(counts) - min(counts) <= 1


def test_split_orders_can_leave_customers_empty() -> None:
    counts = split_orders(5, 12)

    assert sum(counts) == 5
    assert counts.count(0) == 7


def test_orders_are_deterministic() -> None:
    first = generate_orders("cus_test", 6, today=TODAY)
    second = generate_orders("cus_test", 6, today=TODAY)

    assert first == second


def test_different_customers_get_different_history() -> None:
    alice = generate_orders("cus_alice", 10, today=TODAY)
    bob = generate_orders("cus_bob", 10, today=TODAY)

    assert _shape(alice) != _shape(bob)


def test_order_fields_are_plausible() -> None:
    orders = generate_orders("cus_test", 50, today=TODAY, days=30)

    assert len({order.id for order in orders}) == 50
    assert all(order.id.startswith("cus_test-syn-") for order in orders)
    assert {order.status for order in orders} <= set(STATUSES)
    assert all(
        MIN_TOTAL_CENTS <= order.total_cents <= MAX_TOTAL_CENTS for order in orders
    )
    assert all(
        timedelta(0) <= TODAY - date.fromisoformat(order.placed_at) <= timedelta(30)
        for order in orders
    )


def test_seeding_twice_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "seed.db")
    emails = demo_emails(3, [])
    db.ensure_customers(emails)
    rows = [
        order
        for email, count in zip(emails, split_orders(30, 3), strict=True)
        for order in generate_orders(customer_id_for(email), count, today=TODAY)
    ]

    assert db.add_orders(rows) == 30
    assert db.add_orders(rows) == 0
    assert sum(len(db.orders_for(customer_id_for(email))) for email in emails) == 30


def test_seeded_emails_map_to_their_customer_ids(tmp_path: Path) -> None:
    db = Database(tmp_path / "seed.db")
    emails = demo_emails(3, ["me@example.com"])

    db.ensure_customers(emails)

    for email in emails:
        customer = db.customer_for_email(email)
        assert customer is not None
        assert customer.id == customer_id_for(email)
