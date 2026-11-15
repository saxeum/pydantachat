"""Synthesize a demo order history for the local database.

    make seed-demo
    uv run python -m pydantachat.seed --customers 12 --orders 500

Deterministic and idempotent: an order's id and fields derive from its customer
id and position, so a second run adds nothing and never rewrites a row. The
allowlisted addresses (ALLOWED_EMAILS) are used first, so whoever signs in to
the demo has a real history; the rest get demo addresses.
"""

import argparse
import hashlib
import os
import random
from datetime import date, timedelta
from pathlib import Path

from pydantachat.db import Database, Order, customer_id_for
from pydantachat.settings import ConfigError, Settings

STATUSES = ("delivered", "shipped", "processing", "cancelled", "returned")
DEMO_DOMAIN = "example.com"
MIN_TOTAL_CENTS = 499
MAX_TOTAL_CENTS = 49_999


def _rng_for(customer_id: str) -> random.Random:
    """A per-customer stream: same id, same orders, in any process."""
    digest = hashlib.sha256(customer_id.encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def demo_emails(count: int, allowlisted: list[str]) -> list[str]:
    """Real addresses first, then `demo01@example.com` and so on."""
    emails: list[str] = []
    for email in allowlisted:
        cleaned = email.strip().lower()
        if cleaned and cleaned not in emails and len(emails) < count:
            emails.append(cleaned)
    n = 1
    while len(emails) < count:
        email = f"demo{n:02d}@{DEMO_DOMAIN}"
        if email not in emails:
            emails.append(email)
        n += 1
    return emails


def split_orders(total: int, customers: int) -> list[int]:
    """Spread `total` orders over `customers` as evenly as possible."""
    base, extra = divmod(total, customers)
    return [base + (1 if index < extra else 0) for index in range(customers)]


def status_for(age_days: int, rng: random.Random) -> str:
    """Plausible status for an order placed `age_days` ago."""
    roll = rng.random()
    if roll < 0.04:
        return "cancelled"
    if roll < 0.07 and age_days <= 120:
        return "returned"
    if age_days < 3:
        return "processing"
    if age_days < 14:
        return "shipped"
    return "delivered"


def generate_orders(
    customer_id: str,
    count: int,
    *,
    today: date | None = None,
    days: int = 540,
) -> list[Order]:
    """`count` deterministic orders, spread over the last `days` days."""
    today = today or date.today()
    rng = _rng_for(customer_id)
    orders: list[Order] = []
    for n in range(1, count + 1):
        age = rng.randint(0, days)
        orders.append(
            Order(
                id=f"{customer_id}-syn-{n:04d}",
                customer_id=customer_id,
                placed_at=(today - timedelta(days=age)).isoformat(),
                status=status_for(age, rng),
                total_cents=rng.randint(MIN_TOTAL_CENTS, MAX_TOTAL_CENTS),
            )
        )
    return orders


def _allowlisted() -> list[str]:
    raw = os.getenv("ALLOWED_EMAILS", "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, help="database file (default: config.json db_path)"
    )
    parser.add_argument("--customers", type=int, default=12)
    parser.add_argument("--orders", type=int, default=500)
    parser.add_argument("--days", type=int, default=540, help="history window in days")
    args = parser.parse_args()

    if args.customers < 1 or args.orders < 0 or args.days < 1:
        raise SystemExit("--customers and --days must be positive, --orders >= 0")

    try:
        path = args.db or Path(Settings.from_file().db_path)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc

    db = Database(path)
    emails = demo_emails(args.customers, _allowlisted())
    db.ensure_customers(emails)

    today = date.today()
    counts = split_orders(args.orders, len(emails))
    added = sum(
        db.add_orders(
            generate_orders(customer_id_for(email), count, today=today, days=args.days)
        )
        for email, count in zip(emails, counts, strict=True)
    )

    print(f"{len(emails)} customers, {args.orders} synthetic orders ({added} new)")
    print(f"database: {path}")
    for email, count in zip(emails, counts, strict=True):
        print(f"  {customer_id_for(email)}  {email:<28} {count}")


if __name__ == "__main__":
    main()
