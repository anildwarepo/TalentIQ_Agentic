"""Centralized configuration loaded from app_config/.env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load from app_config/.env (centralized config).
# Walk up the parent chain looking for app_config/.env. This handles both
# local dev (repo root has app_config/) and containers (where the file
# typically isn't present and env vars are injected by the platform).
def _find_env_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "app_config" / ".env"
        if candidate.exists():
            return candidate
    return None


_env_path = _find_env_file()
if _env_path is not None:
    load_dotenv(_env_path)

# ── PostgreSQL / AGE ────────────────────────────────────────
PGHOST: str = os.getenv("PGHOST", "localhost")
PGPORT: int = int(os.getenv("PGPORT", "5432"))
PGDATABASE: str = os.getenv("PGDATABASE", "postgres")
PGUSER: str = os.getenv("PGUSER", "")
PGPASSWORD: str = os.getenv("PGPASSWORD", "")
PGSSLMODE: str = os.getenv("PGSSLMODE", "require")
GRAPH_NAME: str = os.getenv("GRAPH_NAME", "talent_graph")

# ── MCP / Backend ───────────────────────────────────────────
MCP_ENDPOINT: str = os.getenv("MCP_ENDPOINT", "http://localhost:3002/mcp")
BACKEND_HOST: str = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))

# ── Azure OpenAI ────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME: str = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")
AZURE_OPENAI_EMBEDDING_DIMENSIONS: int = int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))

# ── Entra ID (Azure AD) auth ──────────────────────────────────
AZURE_TENANT_ID: str = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID: str = os.getenv("ENTRA_SPA_CLIENT_ID", "")
AZURE_TOKEN_AUDIENCE: str = os.getenv("AZURE_TOKEN_AUDIENCE", "https://ai.azure.com")

# ── Cosmos DB (chat history) ─────────────────────────────────
COSMOS_CHAT_ENDPOINT: str = os.getenv("COSMOS_CHAT_ENDPOINT", "")
COSMOS_CHAT_DATABASE: str = os.getenv("COSMOS_CHAT_DATABASE", "talent_db")
COSMOS_CHAT_CONTAINER: str = os.getenv("COSMOS_CHAT_CONTAINER", "chat_history_db")


def pg_conninfo() -> str:
    """Build a libpq connection string from env vars."""
    base = f"host={PGHOST} port={PGPORT} dbname={PGDATABASE} user={PGUSER} password={PGPASSWORD}"
    if PGSSLMODE:
        base += f" sslmode={PGSSLMODE}"
    return base


# ── Azure credential helper ──────────────────────────────────

def _is_azure_hosted() -> bool:
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


def get_azure_credential(*, aio: bool = False):
    """Return an Azure credential tuned for the current environment.

    On Azure-hosted compute → full DefaultAzureCredential.
    Locally → DefaultAzureCredential with IMDS / managed-identity probes
    excluded so we don't pay a ~5s timeout per token acquisition.
    """
    if aio:
        from azure.identity.aio import DefaultAzureCredential as _Cred
    else:
        from azure.identity import DefaultAzureCredential as _Cred

    if _is_azure_hosted() or os.getenv("AZURE_FORCE_FULL_CREDENTIAL_CHAIN") == "1":
        return _Cred()
    return _Cred(
        exclude_managed_identity_credential=True,
        exclude_workload_identity_credential=True,
    )
