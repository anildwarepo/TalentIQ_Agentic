"""Entra ID authentication helpers for PostgreSQL (psycopg2 / data pipeline).

Acquires short-lived bearer tokens for the Azure OSSRDBMS resource scope and
injects them as the libpq ``password`` parameter at every connect.

Three integration points are exposed:

- :func:`get_pg_token` — raw sync token acquisition (uses ``DefaultAzureCredential``).
- :func:`pg_connect` — drop-in replacement for ``psycopg2.connect(**db_config.connection_dict)``
  that attaches a fresh token before each call.
- :class:`EntraThreadedConnectionPool` — subclass of ``psycopg2.pool.ThreadedConnectionPool``
  that refreshes the token before every new physical connection (so long-running
  loads survive across the ~60 minute token lifetime, since the pool calls
  ``_connect`` again when it needs to add or replace a connection).

In Azure Container Apps the user-assigned managed identity (via the injected
``AZURE_CLIENT_ID`` env var) is picked up automatically by
``DefaultAzureCredential``. Locally, the ``az login`` credential is used.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg2
from psycopg2 import pool as _pool

OSSRDBMS_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def _is_azure_hosted() -> bool:
    """Detect whether the process is running on Azure-hosted compute."""
    return any(
        os.getenv(v)
        for v in (
            "WEBSITE_INSTANCE_ID",
            "CONTAINER_APP_NAME",
            "KUBERNETES_SERVICE_HOST",
            "IDENTITY_ENDPOINT",
            "MSI_ENDPOINT",
            "AZURE_CLIENT_ID_FEDERATED_TOKEN_FILE",
        )
    )


def _credential():
    """Return a ``DefaultAzureCredential`` tuned for the current environment.

    On Azure-hosted compute (Container Apps, App Service, AKS, etc.) the full
    credential chain runs, so the managed identity is discovered via IMDS.
    Locally, the IMDS / managed-identity probes are excluded so we don't pay a
    ~5 second timeout per token acquisition.
    """
    from azure.identity import DefaultAzureCredential

    if _is_azure_hosted() or os.getenv("AZURE_FORCE_FULL_CREDENTIAL_CHAIN") == "1":
        return DefaultAzureCredential()
    return DefaultAzureCredential(
        exclude_managed_identity_credential=True,
        exclude_workload_identity_credential=True,
    )


def get_pg_token() -> str:
    """Acquire a fresh Entra access token for PostgreSQL."""
    cred = _credential()
    try:
        return cred.get_token(OSSRDBMS_SCOPE).token
    finally:
        close = getattr(cred, "close", None)
        if close is not None:
            try:
                close()
            except Exception:  # noqa: BLE001
                pass


def _build_pguser_hint(pg_user: str, host: str, libpq_message: str) -> str:
    """Build a multi-line hint when libpq reports password-auth failure.

    On Azure PostgreSQL Flexible Server with Entra ID auth, libpq's ``user``
    parameter MUST be the exact Entra principal name bound to the bearer
    token — the full UPN for a human (``name@tenant.onmicrosoft.com``) or
    the User-Assigned Managed Identity's name for a UAMI. If PGUSER is empty
    or a short username, PG looks up a role that does not match the token's
    principal and replies with ``password authentication failed for user
    "<libpq-user>"`` even though no password was actually sent.
    """
    lines = [
        f"PostgreSQL rejected Entra ID authentication for libpq user "
        f"{pg_user!r} at host {host!r}.",
    ]
    if not pg_user:
        lines.append(
            "Hint: PGUSER is empty in app_config/.env, so libpq fell back to "
            "the operating-system user name. Set PGUSER to the full Entra "
            "principal bound to your PostgreSQL role — the UPN "
            "('name@tenant.onmicrosoft.com') for a human signed in via "
            "'az login', or the User-Assigned Managed Identity's name "
            "('<uami-name>') for app-hosted compute."
        )
    elif "@" not in pg_user:
        lines.append(
            f"Hint: PGUSER={pg_user!r} looks like a short username. "
            f"Azure PostgreSQL Flexible Server with Entra ID auth looks up "
            f"the role by the exact principal name bound to the bearer "
            f"token — for a human signed in via 'az login', that is the "
            f"full UPN ('{pg_user}@<tenant>.onmicrosoft.com'); for a UAMI, "
            f"it is the UAMI's name. Update PGUSER in app_config/.env."
        )
    lines.append(f"libpq message: {libpq_message.strip()}")
    return "\n  ".join(lines)


def pg_connect(**overrides: Any) -> psycopg2.extensions.connection:
    """Open a single ``psycopg2`` connection using an Entra token as password.

    ``overrides`` are merged on top of ``db_config.connection_dict`` so callers
    can selectively change a field (e.g. ``application_name``). The password is
    always replaced with a freshly acquired token.

    When libpq reports a password-authentication failure (which on this stack
    really means the Entra principal bound to the token does not match a
    PostgreSQL role of that exact name), the underlying ``OperationalError``
    is wrapped with a configuration hint to make the misdiagnosis obvious.
    """
    # Import here to avoid a circular import at module load time (``config``
    # imports nothing from this module, but keeping the dependency one-way
    # makes future refactors easier).
    from talent_data_pipeline.config import db_config

    kwargs: dict[str, Any] = {**db_config.connection_dict, **overrides}
    kwargs["password"] = get_pg_token()
    try:
        return psycopg2.connect(**kwargs)
    except psycopg2.OperationalError as exc:
        message = str(exc)
        if "password authentication failed" in message.lower():
            pg_user = str(kwargs.get("user") or "")
            host = str(kwargs.get("host") or "")
            raise psycopg2.OperationalError(
                _build_pguser_hint(pg_user, host, message)
            ) from exc
        raise


class EntraThreadedConnectionPool(_pool.ThreadedConnectionPool):
    """``ThreadedConnectionPool`` that injects a fresh Entra token per connect.

    psycopg2's pool calls ``_connect`` whenever it needs to open a new physical
    connection (initial fill, replacement after error, or when ``getconn`` is
    asked for a key not yet bound). Refreshing ``self._kwargs["password"]``
    immediately before delegating keeps every new connection within the
    ~60 minute token validity window.

    Password-authentication failures are wrapped with the same PGUSER hint
    used by :func:`pg_connect`, so a misconfigured ``PGUSER`` produces an
    actionable error whether the failure surfaces during the up-front
    connectivity test or later during pool-driven loading.
    """

    def _connect(self, key: Any = None) -> psycopg2.extensions.connection:  # type: ignore[override]
        self._kwargs["password"] = get_pg_token()
        try:
            return super()._connect(key)
        except psycopg2.OperationalError as exc:
            message = str(exc)
            if "password authentication failed" in message.lower():
                pg_user = str(self._kwargs.get("user") or "")
                host = str(self._kwargs.get("host") or "")
                raise psycopg2.OperationalError(
                    _build_pguser_hint(pg_user, host, message)
                ) from exc
            raise
