"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from centralized app_config/.env
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _REPO_ROOT / "app_config" / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = field(default_factory=lambda: os.getenv("PGHOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("PGPORT", "5432")))
    database: str = field(default_factory=lambda: os.getenv("PGDATABASE", "postgres"))
    user: str = field(default_factory=lambda: os.getenv("PGUSER", ""))
    sslmode: str = field(default_factory=lambda: os.getenv("PGSSLMODE", "require"))
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
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536")))


# Singletons
db_config = DatabaseConfig()
pipeline_config = PipelineConfig()
