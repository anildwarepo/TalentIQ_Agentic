"""Centralized configuration loaded from app_config/.env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load from app_config/.env (centralized config)
_env_path = Path(__file__).resolve().parents[2] / "app_config" / ".env"
if not _env_path.exists():
    _env_path = Path(__file__).resolve().parents[3] / "app_config" / ".env"
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
