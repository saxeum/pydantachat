"""The tool's side of the orders API: mint a token, call the API, return rows.

The token is minted per call and never stored, so nothing long-lived sits in the
process and nothing can leak into a trace or the transcript.
"""

import httpx

from pydantachat.orders_auth import mint_token


class HttpOrdersClient:
    """Call the orders API as one customer, over HTTP."""

    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        customer_id: str,
        session_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._secret = secret
        self._customer_id = customer_id
        self._session_id = session_id
        # Tests pass an ASGITransport so the real route and auth path run
        # without a network. Production leaves it None.
        self._transport = transport

    async def list_orders(self) -> list[dict[str, str]]:
        token = mint_token(self._secret, self._customer_id, self._session_id)
        async with httpx.AsyncClient(
            base_url=self._base_url, transport=self._transport, timeout=10.0
        ) as client:
            response = await client.get(
                "/api/orders", headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            orders: list[dict[str, str]] = response.json()["orders"]
            return orders
