"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""

def _find_repo_env() -> Path:
    """Find repo-level app_config/.env from cwd or package location."""
    starts = [Path.cwd(), Path(__file__).resolve()]
    seen: set[Path] = set()
    for start in starts:
        for parent in (start, *start.parents):
            if parent in seen:
                continue
            seen.add(parent)
            candidate = parent / "app_config" / ".env"
            if candidate.exists():
                return candidate
    return Path(__file__).resolve().parent.parent / "app_config" / ".env"


# Load .env from centralized app_config/.env
_ENV_PATH = _find_repo_env()
_REPO_ROOT = _ENV_PATH.parent.parent
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH, override=False)


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = field(default_factory=lambda: os.getenv("PGHOST", "localhost"))
    hostaddr: str = field(default_factory=lambda: os.getenv("PGHOSTADDR", ""))
    port: int = field(default_factory=lambda: int(os.getenv("PGPORT", "5432")))
    database: str = field(default_factory=lambda: os.getenv("PGDATABASE", "postgres"))
    user: str = field(default_factory=lambda: os.getenv("PGUSER", ""))
    sslmode: str = field(default_factory=lambda: os.getenv("PGSSLMODE", "require"))
    connect_timeout: int = field(default_factory=lambda: int(os.getenv("PGCONNECT_TIMEOUT", "15")))
    pool_min: int = 2
    pool_max: int = 10

    @property
    def dsn(self) -> str:
        # NOTE: password intentionally omitted. Callers must use
        # ``pg_entra.pg_connect`` (or ``EntraThreadedConnectionPool``)
        # to attach a fresh Entra ID token at connect time.
        base = f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"
        if self.sslmode:
            base += f"?sslmode={self.sslmode}"
        return base

    @property
    def connection_dict(self) -> dict[str, str | int]:
        # NOTE: password intentionally omitted. ``pg_entra`` injects a fresh
        # OSSRDBMS bearer token immediately before each ``psycopg2.connect``.
        d: dict[str, str | int] = {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
        }
        if self.sslmode:
            d["sslmode"] = self.sslmode
        if self.hostaddr:
            d["hostaddr"] = self.hostaddr
        if self.connect_timeout:
            d["connect_timeout"] = self.connect_timeout
        return d


@dataclass(frozen=True)
class PipelineConfig:
    batch_size: int = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "1000")))
    employee_count: int = field(default_factory=lambda: int(os.getenv("EMPLOYEE_COUNT", "130000")))
    random_seed: int = field(default_factory=lambda: int(os.getenv("RANDOM_SEED", "42")))
    graph_name: str = field(default_factory=lambda: os.getenv("GRAPH_NAME", "talent_graph"))
    # Azure OpenAI Embeddings
    azure_openai_endpoint: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", ""))
    azure_openai_embedding_deployment: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002"))
    azure_openai_use_entra_auth: bool = field(default_factory=lambda: _env_bool("AZURE_OPENAI_USE_ENTRA_AUTH"))
    azure_openai_api_key: str = field(default_factory=lambda: _first_env("FOUNDRY_DEPLOYMENT_KEY", "AZURE_OPENAI_API_KEY", "FOUNDRY_API_KEY"))
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536")))


# Singletons
db_config = DatabaseConfig()
pipeline_config = PipelineConfig()
