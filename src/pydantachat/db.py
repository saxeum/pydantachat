"""SQLite: customers and their orders.

One module owns the schema and the queries, so no route ever writes SQL. Nothing
here decides *who* the caller is: every read takes a customer id that came from a
verified token.
"""

import hashlib
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    placed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    total_cents INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_by_customer ON orders(customer_id);
"""

# Three orders per customer, so a demo answer has something to summarise.
DEMO_ORDERS = (
    ("2026-10-02", "shipped", 4999),
    ("2026-10-18", "processing", 1250),
    ("2026-11-01", "delivered", 8999),
)


@dataclass(frozen=True)
class Customer:
    id: str
    email: str
    name: str


@dataclass(frozen=True)
class Order:
    id: str
    customer_id: str
    placed_at: str
    status: str
    total_cents: int

    def as_dict(self) -> dict[str, str]:
        """What the model sees: no customer id, and the total already formatted."""
        return {
            "id": self.id,
            "placed_at": self.placed_at,
            "status": self.status,
            "total": f"{self.total_cents / 100:.2f} USD",
        }


def customer_id_for(email: str) -> str:
    """A stable, opaque id, so seeding twice does not create two customers."""
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"cus_{digest[:12]}"


class Database:
    """A file-backed SQLite database. Pass a real path (or `tmp_path` in tests).

    Each call opens its own connection: FastAPI runs synchronous handlers in a
    thread pool, and `sqlite3` connections are bound to the thread that opened
    them. At demo scale that is cheaper than a pool.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def ensure_customers(self, emails: Iterable[str]) -> None:
        """Create a row per email, once. Ids are derived, so re-running is safe."""
        rows = [
            (customer_id_for(email), email, email.split("@")[0])
            for email in sorted({raw.strip().lower() for raw in emails if raw.strip()})
        ]
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO customers (id, email, name) VALUES (?, ?, ?)",
                rows,
            )

    def add_orders(self, orders: Iterable[Order]) -> int:
        """Insert orders idempotently; return how many were new.

        `INSERT OR IGNORE` plus stable ids means a second run adds nothing and
        never rewrites existing rows.
        """
        with self._connect() as conn:
            cursor = conn.executemany(
                "INSERT OR IGNORE INTO orders "
                "(id, customer_id, placed_at, status, total_cents) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (o.id, o.customer_id, o.placed_at, o.status, o.total_cents)
                    for o in orders
                ],
            )
            return max(cursor.rowcount, 0)

    def seed(self, emails: Iterable[str]) -> None:
        """Give every allowlisted email a customer row and three starter orders.

        Idempotent: ids are derived from the email and called out in the SQL, so
        restarting the app neither duplicates customers nor resets their orders.
        """
        emails = sorted({raw.strip().lower() for raw in emails if raw.strip()})
        self.ensure_customers(emails)
        self.add_orders(
            Order(
                id=f"{customer_id_for(email)}-{n:02d}",
                customer_id=customer_id_for(email),
                placed_at=placed_at,
                status=status,
                total_cents=cents,
            )
            for email in emails
            for n, (placed_at, status, cents) in enumerate(DEMO_ORDERS, start=1)
        )

    def customer_for_email(self, email: str) -> Customer | None:
        """The customer behind an authenticated email, or None. Fail closed."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, email, name FROM customers WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        return (
            Customer(id=row["id"], email=row["email"], name=row["name"])
            if row
            else None
        )

    def orders_for(self, customer_id: str) -> list[Order]:
        """This customer's orders, newest first. The id must come from a claim."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, customer_id, placed_at, status, total_cents "
                "FROM orders WHERE customer_id = ? ORDER BY placed_at DESC",
                (customer_id,),
            ).fetchall()
        return [
            Order(
                id=row["id"],
                customer_id=row["customer_id"],
                placed_at=row["placed_at"],
                status=row["status"],
                total_cents=row["total_cents"],
            )
            for row in rows
        ]
