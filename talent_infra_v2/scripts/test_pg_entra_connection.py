"""
Test PostgreSQL connectivity using Microsoft Entra ID authentication.

Acquires a Microsoft Entra access token (no passwords) and uses it as the
PostgreSQL password to connect to an Azure Database for PostgreSQL Flexible
Server. Supports both interactive sign-in (az CLI / VS Code) and
managed identities, by using `DefaultAzureCredential`.

References:
- https://learn.microsoft.com/azure/postgresql/security/security-entra-configure

Usage:
    # Use the current `az login` user (default)
    python test_pg_entra_connection.py

    # Override host / db / user
    python test_pg_entra_connection.py \\
        --host tiqpgsql66lb.postgres.database.azure.com \\
        --dbname postgres \\
        --user me@contoso.onmicrosoft.com

    # Use a specific user-assigned managed identity (UAMI)
    python test_pg_entra_connection.py \\
        --client-id <UAMI clientId> \\
        --user <MSI display name registered as Entra admin>

Exit codes:
    0  success
    1  connection / auth failure
    2  invalid arguments
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import psycopg2
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

# Microsoft Entra ID resource for Azure DB for PostgreSQL
OSSRDBMS_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

DEFAULT_HOST = os.getenv("PGHOST", "tiqpgsql66lb.postgres.database.azure.com")
DEFAULT_DB = os.getenv("PGDATABASE", "postgres")
DEFAULT_PORT = int(os.getenv("PGPORT", "5432"))


def _green(msg: str) -> str:
    return f"\033[92m{msg}\033[0m"


def _red(msg: str) -> str:
    return f"\033[91m{msg}\033[0m"


def _cyan(msg: str) -> str:
    return f"\033[96m{msg}\033[0m"


def _resolve_user_from_az_cli() -> str | None:
    """Best-effort lookup of the signed-in az CLI user's UPN."""
    try:
        out = subprocess.run(
            ["az", "ad", "signed-in-user", "show", "-o", "json"],
            capture_output=True,
            text=True,
            check=True,
            shell=(os.name == "nt"),
        )
        return json.loads(out.stdout).get("userPrincipalName")
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return None


def acquire_token(client_id: str | None) -> tuple[str, datetime]:
    """Acquire an Entra access token for Azure DB for PostgreSQL.

    If `client_id` is provided, use ManagedIdentityCredential against that
    specific UAMI. Otherwise use DefaultAzureCredential, which tries (in order):
      env vars, workload identity, managed identity, Azure CLI, VS Code,
      Azure PowerShell, interactive browser.
    """
    if client_id:
        print(_cyan(f"==> Acquiring token via ManagedIdentityCredential (clientId={client_id})"))
        cred = ManagedIdentityCredential(client_id=client_id)
    else:
        print(_cyan("==> Acquiring token via DefaultAzureCredential"))
        cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)

    token = cred.get_token(OSSRDBMS_SCOPE)
    expires = datetime.fromtimestamp(token.expires_on, tz=timezone.utc)
    ttl_min = (expires - datetime.now(tz=timezone.utc)).total_seconds() / 60
    print(f"    Token acquired. Expires in ~{ttl_min:.1f} min ({expires.isoformat()})")
    return token.token, expires


def test_connection(
    host: str,
    port: int,
    dbname: str,
    user: str,
    token: str,
    sslmode: str = "require",
) -> int:
    """Open a connection and run a few sanity queries. Returns exit code."""
    print(_cyan(f"==> Connecting to {host}:{port}/{dbname} as '{user}' (sslmode={sslmode})"))
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=token,  # Entra access token used as password
            sslmode=sslmode,
            connect_timeout=15,
            application_name="talentiq-entra-test",
        )
    except psycopg2.OperationalError as exc:
        print(_red(f"    FAILED: {exc}"))
        _diagnose(str(exc), user)
        return 1

    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT version();")
            print(f"    PostgreSQL: {cur.fetchone()[0].split(',')[0]}")

            cur.execute(
                "SELECT current_user, session_user, current_database(), inet_server_addr();"
            )
            cu, su, db, addr = cur.fetchone()
            print(f"    current_user     : {cu}")
            print(f"    session_user     : {su}")
            print(f"    current_database : {db}")
            print(f"    server_addr      : {addr}")

            cur.execute(
                "SELECT extname, extversion FROM pg_extension ORDER BY extname;"
            )
            exts = cur.fetchall()
            print(f"    extensions ({len(exts)}):")
            for name, ver in exts:
                print(f"      - {name} v{ver}")

            cur.execute("SELECT NOW();")
            print(f"    server time      : {cur.fetchone()[0]}")
    finally:
        conn.close()

    print(_green("==> SUCCESS: Entra ID authentication works."))
    return 0


def _diagnose(err: str, user: str) -> None:
    """Print actionable hints based on the libpq error text."""
    e = err.lower()
    print()
    print(_cyan("    Diagnostic hints:"))
    if "password authentication failed" in e or "no pg_hba" in e:
        print(
            f"    * Role '{user}' may not exist in this database.\n"
            "      Connect as an Entra admin and run one of:\n"
            "        -- For a user (UPN):\n"
            f"        SELECT * FROM pgaadauth_create_principal('{user}', false, false);\n"
            "        -- For a managed identity / service principal (use objectId):\n"
            "        SELECT * FROM pgaadauth_create_principal_with_oid(\n"
            "            '<MSI display name>', '<MSI principalId>', 'service', false, false);"
        )
        print(
            "    * The username is CASE-SENSITIVE and must match the Entra display-name\n"
            "      (for users: the UPN; for MSI: the identity's resource name)."
        )
    if "could not translate host name" in e or "timeout" in e or "could not connect" in e:
        print(
            "    * Network: confirm the server FQDN is reachable and your client IP\n"
            "      is in the firewall (or you are on the vnet/private endpoint)."
        )
        print(
            "    * For private access, ensure outbound to the `AzureActiveDirectory`\n"
            "      service tag is allowed (needed for token validation by the server)."
        )
    if "ssl" in e:
        print("    * SSL is required. Make sure sslmode=require (or stronger).")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Test Azure PostgreSQL connectivity with Microsoft Entra ID auth."
    )
    p.add_argument("--host", default=DEFAULT_HOST, help=f"PG host FQDN (default: {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"PG port (default: {DEFAULT_PORT})")
    p.add_argument("--dbname", default=DEFAULT_DB, help=f"Database name (default: {DEFAULT_DB})")
    p.add_argument(
        "--user",
        default=os.getenv("PGUSER"),
        help="Entra principal username (UPN for users, display name for MSI/SP). "
             "Defaults to the az CLI signed-in user's UPN.",
    )
    p.add_argument(
        "--client-id",
        default=None,
        help="User-assigned managed identity clientId. If set, uses "
             "ManagedIdentityCredential instead of DefaultAzureCredential.",
    )
    p.add_argument("--sslmode", default=os.getenv("PGSSLMODE", "require"))
    args = p.parse_args(argv)

    # Resolve username if not supplied
    user = args.user or _resolve_user_from_az_cli()
    if not user:
        print(_red(
            "ERROR: Could not determine PostgreSQL username.\n"
            "       Pass --user <UPN-or-MSI-name> or sign in with `az login` first."
        ))
        return 2

    try:
        token, _ = acquire_token(args.client_id)
    except ClientAuthenticationError as exc:
        print(_red(f"ERROR: Failed to acquire Entra token: {exc}"))
        return 1

    return test_connection(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=user,
        token=token,
        sslmode=args.sslmode,
    )


if __name__ == "__main__":
    sys.exit(main())
