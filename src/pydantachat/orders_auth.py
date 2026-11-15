"""Short-lived tokens for the orders API.

The wrapper mints these; the model never sees one. A token names exactly one
customer and one chat session and expires in minutes, so a value leaked into a
log or a trace is dead before it is useful.

This is our own signed token, not an identity-provider "on-behalf-of" grant: the
secret is the app's session secret and the only consumer is this process.
"""

from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

AUDIENCE = "pydantachat-orders"
TOKEN_TTL_SECONDS = 120
SALT = "orders-token"


@dataclass(frozen=True)
class OrdersClaim:
    """Who the caller is, according to a verified token."""

    customer_id: str
    session_id: str


def _serializer(secret: str) -> URLSafeTimedSerializer:
    # The salt keeps these tokens from being interchangeable with the session
    # cookies signed by the same secret.
    return URLSafeTimedSerializer(secret, salt=SALT)


def mint_token(secret: str, customer_id: str, session_id: str) -> str:
    return _serializer(secret).dumps(
        {"aud": AUDIENCE, "sub": customer_id, "sid": session_id}
    )


def read_token(
    secret: str, token: str, *, max_age: int = TOKEN_TTL_SECONDS
) -> OrdersClaim | None:
    """Return the claim, or None for anything that does not verify."""
    try:
        data = _serializer(secret).loads(token, max_age=max_age)
    except BadSignature, SignatureExpired:
        return None

    if not isinstance(data, dict) or data.get("aud") != AUDIENCE:
        return None
    customer_id = data.get("sub")
    session_id = data.get("sid")
    if not isinstance(customer_id, str) or not customer_id:
        return None
    if not isinstance(session_id, str) or not session_id:
        return None
    return OrdersClaim(customer_id=customer_id, session_id=session_id)
