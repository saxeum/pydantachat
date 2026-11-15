"""The orders API. It trusts the on-behalf-of token and nothing else.

The browser's session cookie and a Google ID token are both useless here: only
`Authorization: Bearer <orders token>` is read. That token names exactly one
customer, so the API derives the customer from the credential and never from the
path or anything the model produced.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from pydantachat.db import Database
from pydantachat.orders_auth import OrdersClaim, read_token
from pydantachat.settings import get_auth

router = APIRouter(prefix="/api", tags=["orders"])
BEARER_PREFIX = "bearer "


class OrderOut(BaseModel):
    id: str
    placed_at: str
    status: str
    total: str


class OrdersReply(BaseModel):
    customer_id: str
    orders: list[OrderOut]


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": 'Bearer realm="orders"'},
    )


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def orders_claim(request: Request) -> OrdersClaim:
    """Accept only our signed orders token; cookies and ID tokens are refused."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(BEARER_PREFIX):
        raise _unauthorised("orders token required")
    claim = read_token(get_auth().session_secret, header[len(BEARER_PREFIX) :].strip())
    if claim is None:
        raise _unauthorised("invalid orders token")
    return claim


Claim = Annotated[OrdersClaim, Depends(orders_claim)]
DbDep = Annotated[Database, Depends(get_db)]


def _reply(customer_id: str, db: Database) -> OrdersReply:
    return OrdersReply(
        customer_id=customer_id,
        orders=[OrderOut(**order.as_dict()) for order in db.orders_for(customer_id)],
    )


@router.get("/orders")
def my_orders(claim: Claim, db: DbDep) -> OrdersReply:
    """The token's customer. There is no id in the path to tamper with."""
    return _reply(claim.customer_id, db)


@router.get("/customers/{customer_id}/orders")
def customer_orders(customer_id: str, claim: Claim, db: DbDep) -> OrdersReply:
    """Kept so the cross-customer failure has a target; 403 on any mismatch."""
    if customer_id != claim.customer_id:
        raise HTTPException(status_code=403, detail="not your customer")
    return _reply(customer_id, db)
