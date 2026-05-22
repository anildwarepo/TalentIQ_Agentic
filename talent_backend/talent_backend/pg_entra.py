"""Entra ID (Azure AD) authentication helpers for PostgreSQL.

Uses the Azure OSSRDBMS resource scope to acquire short-lived bearer tokens
that are used in place of a password when connecting to Azure Database for
PostgreSQL Flexible Server with `activeDirectoryAuth=Enabled`.

The token (~60 min TTL) is acquired fresh for every new pooled connection
via a subclass of `psycopg_pool.AsyncConnectionPool` that mutates
`self.kwargs["password"]` immediately before each connect.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from talent_backend.config import get_azure_credential

logger = logging.getLogger("talent_backend.pg_entra")

# Azure-wide OSSRDBMS resource. Tokens issued for this scope are accepted by
# Azure Database for PostgreSQL Flexible Server when Entra auth is enabled.
OSSRDBMS_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


async def get_pg_token_async() -> str:
    """Acquire a fresh Entra ID access token for PostgreSQL.

    Uses an async `DefaultAzureCredential` so the call doesn't block the
    event loop. The credential picks up the container app's user-assigned
    managed identity automatically (via the `AZURE_CLIENT_ID` env var that
    Bicep injects), and falls back to `az login` for local dev.
    """
    cred = get_azure_credential(aio=True)
    try:
        token = await cred.get_token(OSSRDBMS_SCOPE)
        return token.token
    finally:
        # The async credential holds an aiohttp/httpx session that must be
        # closed to avoid "Unclosed client session" warnings on shutdown.
        close = getattr(cred, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001
                pass


class EntraTokenAsyncConnectionPool(AsyncConnectionPool):
    """`AsyncConnectionPool` that refreshes the Entra token before every connect.

    `psycopg_pool` calls `_connect` whenever it needs to open a new physical
    connection (initial fill, recycle after `max_lifetime`, or replace after
    a failed connection). Overriding here keeps each new connection using a
    valid, non-expired bearer token without touching call sites.

    The token is injected via `self.kwargs["password"]` which psycopg
    forwards to `psycopg.AsyncConnection.connect(...)`.
    """

    async def _connect(self, timeout: float | None = None, **kwargs: Any):
        # Mutate the kwargs dict that the parent class forwards to psycopg.
        # A fresh token is acquired on every new physical connection.
        self.kwargs["password"] = await get_pg_token_async()
        return await super()._connect(timeout=timeout, **kwargs)
