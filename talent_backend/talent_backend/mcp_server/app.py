"""FastMCP application instance and shared state.

All tool modules import ``mcp`` from here to register their
``@mcp.tool`` decorators.  ``pg_helper`` is set by ``__main__``
before the server starts accepting requests.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from .pg_age_helper import PGAgeHelper

logger = logging.getLogger("talent_mcp")

# ── FastMCP instance ─────────────────────────────────────────
mcp = FastMCP("TalentIQ Graph MCP Server")

# ── Global PG helper (set by __main__ before server starts) ──
pg_helper: PGAgeHelper | None = None


def _pg() -> PGAgeHelper:
    """Return the initialised PGAgeHelper or raise."""
    if pg_helper is None:
        raise RuntimeError("PGAgeHelper not initialised — run via __main__")
    return pg_helper
