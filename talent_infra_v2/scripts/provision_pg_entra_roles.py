"""Provision Entra ID principals as PostgreSQL roles via ``pgaadauth_create_principal_with_oid``.

Called from the azd postprovision hook *after* the container apps (and therefore
their user-assigned managed identities) have been deployed. Connects to the
PostgreSQL Flexible Server with an OSSRDBMS bearer token (deployer's identity),
then idempotently creates a role for each principal and grants it the
permissions needed for the application to work.

Usage::

    python provision_pg_entra_roles.py \
        --host tiqpgsql66lb.postgres.database.azure.com \
        --database postgres \
        --admin-upn anildwa@MngEnvMCAP347541.onmicrosoft.com \
        --graph-name talent_graph_66lb \
        --principals '[{"name":"backend-66lb-identity","oid":"<guid>","type":"service"}, ...]'

The ``--admin-upn`` value MUST be the principal name of an existing Entra
PostgreSQL administrator (registered via the Bicep ``administrators`` child
resource in the preceding provision phase). The script aborts if it cannot
authenticate, with a diagnostic SQL snippet suggesting the manual remediation.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

import psycopg2
from azure.identity import DefaultAzureCredential

OSSRDBMS_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

# Grants applied to every Entra-mapped application role. We keep this list
# narrow — only what the backend / MCP server / data pipeline need.
PUBLIC_SCHEMA_GRANTS = [
    'GRANT CONNECT ON DATABASE "{db}" TO "{role}";',
    'GRANT USAGE ON SCHEMA public TO "{role}";',
    'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}";',
    'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}";',
    'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}";',
    'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{role}";',
]

AG_CATALOG_GRANTS = [
    'GRANT USAGE ON SCHEMA ag_catalog TO "{role}";',
    'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ag_catalog TO "{role}";',
    'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ag_catalog TO "{role}";',
]

GRAPH_SCHEMA_GRANTS = [
    'GRANT USAGE ON SCHEMA "{graph}" TO "{role}";',
    'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{graph}" TO "{role}";',
    'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{graph}" TO "{role}";',
    'ALTER DEFAULT PRIVILEGES IN SCHEMA "{graph}" GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}";',
]


def _get_token() -> str:
    cred = DefaultAzureCredential()
    try:
        return cred.get_token(OSSRDBMS_SCOPE).token
    finally:
        close = getattr(cred, "close", None)
        if close is not None:
            try:
                close()
            except Exception:  # noqa: BLE001
                pass


def _connect(host: str, database: str, user: str, sslmode: str = "require", hostaddr: str = ""):
    token = _get_token()
    kwargs = dict(
        host=host,
        port=5432,
        dbname=database,
        user=user,
        password=token,
        sslmode=sslmode,
    )
    # `hostaddr` lets the caller skip DNS while still using `host` for TLS
    # SNI / certificate validation. Useful when /etc/hosts (or Windows hosts)
    # has been overridden to point the PG FQDN at a private endpoint IP that
    # is unreachable from the current network path.
    if hostaddr:
        kwargs["hostaddr"] = hostaddr
    return psycopg2.connect(**kwargs)


def _create_principal(cur, name: str, oid: str, principal_type: str) -> bool:
    """Create the Entra-mapped PG role idempotently. Returns True if newly created."""
    is_admin = "false"
    is_mfa = "false"
    sql = (
        f"SELECT * FROM pgaadauth_create_principal_with_oid("
        f"'{name}', '{oid}', '{principal_type}', {is_admin}, {is_mfa});"
    )
    try:
        cur.execute(sql)
        return True
    except psycopg2.Error as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "duplicate" in msg or "role" in msg and "exists" in msg:
            return False
        raise


def _apply_grants(cur, statements: Sequence[str], **fmt: str) -> None:
    for tmpl in statements:
        cur.execute(tmpl.format(**fmt))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument(
        "--hostaddr",
        default="",
        help="Explicit IPv4/IPv6 address to connect to, bypassing DNS. Hostname is still used for TLS validation.",
    )
    parser.add_argument("--database", default="postgres")
    parser.add_argument("--sslmode", default="require")
    parser.add_argument(
        "--admin-upn",
        required=True,
        help="UPN of an existing Entra PG administrator (used as PGUSER)",
    )
    parser.add_argument(
        "--graph-name",
        default="",
        help="AGE graph schema name. When set, GRANTs are applied to that schema as well.",
    )
    parser.add_argument(
        "--principals",
        required=True,
        help='JSON list of {"name":..., "oid":..., "type":"service|user|group"}',
    )
    args = parser.parse_args()

    try:
        principals = json.loads(args.principals)
    except json.JSONDecodeError as exc:
        print(f"ERROR: --principals is not valid JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(principals, list) or not principals:
        print("ERROR: --principals must be a non-empty JSON list", file=sys.stderr)
        return 2

    addr_suffix = f" [hostaddr={args.hostaddr}]" if args.hostaddr else ""
    print(f"Connecting to {args.host}/{args.database} as {args.admin_upn} (Entra token){addr_suffix}...")
    try:
        conn = _connect(args.host, args.database, args.admin_upn, args.sslmode, args.hostaddr)
    except psycopg2.Error as exc:
        print(f"ERROR: could not connect: {exc}", file=sys.stderr)
        print(
            "Hint: ensure the admin UPN is registered as a PostgreSQL Entra "
            "administrator and the deploying credential has access.",
            file=sys.stderr,
        )
        return 1

    conn.autocommit = True
    cur = conn.cursor()

    exit_code = 0
    for entry in principals:
        name = entry.get("name", "").strip()
        oid = entry.get("oid", "").strip()
        ptype = (entry.get("type") or "service").strip()
        if not (name and oid):
            print(f"  SKIP: missing name or oid in entry {entry!r}")
            continue

        print(f"\n  Principal '{name}' ({ptype}, oid={oid}):")
        try:
            created = _create_principal(cur, name, oid, ptype)
            print(f"    role: {'created' if created else 'already exists'}")
            _apply_grants(
                cur,
                PUBLIC_SCHEMA_GRANTS,
                db=args.database,
                role=name,
            )
            print(f"    granted: public schema (CONNECT, SELECT/INSERT/UPDATE/DELETE)")

            _apply_grants(cur, AG_CATALOG_GRANTS, role=name)
            print(f"    granted: ag_catalog schema")

            if args.graph_name:
                # AGE creates a schema named after the graph; grant access too.
                try:
                    _apply_grants(
                        cur, GRAPH_SCHEMA_GRANTS, graph=args.graph_name, role=name,
                    )
                    print(f"    granted: graph schema '{args.graph_name}'")
                except psycopg2.Error as exc:
                    # Graph schema might not exist yet on first run — non-fatal.
                    print(
                        f"    WARNING: could not grant on graph schema "
                        f"'{args.graph_name}': {exc}"
                    )
        except psycopg2.Error as exc:
            print(f"    ERROR: {exc}", file=sys.stderr)
            exit_code = 1

    cur.close()
    conn.close()

    if exit_code == 0:
        print("\nAll Entra principals provisioned successfully.")
    else:
        print("\nOne or more principals failed — see errors above.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
