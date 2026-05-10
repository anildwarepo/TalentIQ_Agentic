"""TalentIQ Graph MCP Server — module aggregator.

Importing this module registers all MCP tools on the shared
``mcp`` instance from ``app.py``.  The ``__main__`` entry point
imports ``server`` to trigger registration, then runs the server.
"""

# Re-export the FastMCP app and pg_helper so __main__ can set state
from .app import mcp, pg_helper  # noqa: F401

# Import tool modules — their @mcp.tool decorators register on import
from . import graph_tools  # noqa: F401
from . import cv_generator  # noqa: F401
from . import vector_tools  # noqa: F401
