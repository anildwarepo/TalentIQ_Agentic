"""Entry point: ``python -m talent_backend.mcp_server``

Initialises the PGAgeHelper connection pool, then starts the FastMCP
server with the chosen transport (stdio or streamable-http).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

# ── Windows compatibility ────────────────────────────────────
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        import psycopg.pq._pq_ctypes  # noqa: F401
        os.environ.setdefault("PSYCOPG_IMPL", "python")
    except (ImportError, OSError):
        pass

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from talent_backend.mcp_server import app, server  # noqa: F401 — server import triggers tool registration
from talent_backend.mcp_server.pg_age_helper import PGAgeHelper

# ── Logging ──────────────────────────────────────────────────
_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "mcp_server.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("talent_mcp")


def main() -> None:
    parser = argparse.ArgumentParser(description="TalentIQ Graph MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="streamable-http",
    )
    parser.add_argument("--port", type=int, default=3002)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    # ── Initialise PGAgeHelper (deferred — pool opens in server's event loop) ──
    app.pg_helper = PGAgeHelper.create_deferred()
    logger.info("PGAgeHelper created (deferred open)")

    # ── Pre-warm Azure OpenAI client (moves credential cost to startup) ──
    try:
        from .vector_tools import _get_openai_client
        _get_openai_client()
        logger.info("Azure OpenAI client pre-warmed")
    except Exception as exc:
        logger.warning("Azure OpenAI pre-warm failed (will retry on first use): %s", exc)

    # ── Run FastMCP ──────────────────────────────────────────
    logger.info(
        "Starting MCP server  transport=%s  host=%s  port=%d",
        args.transport,
        args.host,
        args.port,
    )

    app.mcp.run(
        transport=args.transport,
        host=args.host,
        port=args.port,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["Mcp-Session-Id"],
            ),
        ],
    )


if __name__ == "__main__":
    main()
