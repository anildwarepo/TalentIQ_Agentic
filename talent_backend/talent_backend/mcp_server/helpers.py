"""Shared helpers for the MCP server tools.

Pure functions — no FastMCP or database dependencies.

Schema/ontology lives in `mcp_server.schema` (loaded live from the DB).
Nothing in this module hardcodes node labels, edge types, or enum sets.
"""

from __future__ import annotations


# ── Name / search helpers ────────────────────────────────────

NAME_SKIP_TITLES = frozenset({
    "dr", "mr", "mrs", "ms", "prof", "sir", "dame", "rev",
    "the", "of", "and", "for", "at", "in",
    "lead", "senior", "junior", "principal", "architect",
    "manager", "director", "engineer", "developer", "consultant",
})


def strip_agtype(val) -> str:
    """Strip AGE agtype formatting: '["Label"]' -> 'Label', '"rel"' -> 'rel'."""
    if not isinstance(val, str):
        return str(val)
    val = val.strip()
    if val.startswith('["') and val.endswith('"]'):
        val = val[2:-2]
    elif val.startswith('"') and val.endswith('"') and len(val) > 1:
        val = val[1:-1]
    return val


def extract_search_words(search_term: str) -> list[str]:
    """Extract significant words from a search term, skipping titles and short words."""
    return [
        w.lower().strip(".,;:")
        for w in search_term.split()
        if w.lower().strip(".,;:") not in NAME_SKIP_TITLES and len(w.strip(".,;:")) >= 2
    ]


def name_matches_search(name: str, search_words: list[str]) -> bool:
    """Check if a name contains ALL significant search words."""
    if not search_words or not name:
        return True
    name_lower = name.lower()
    return all(w in name_lower for w in search_words)


def strip_titles_for_search(search_term: str) -> str:
    """Strip known titles/honorifics from a search term to maximise FTS recall."""
    words = search_term.split()
    stripped = [w for w in words if w.lower().strip(".,;:") not in NAME_SKIP_TITLES]
    if len(stripped) < 2 and len(words) >= 2:
        return search_term
    if not stripped:
        return search_term
    return " ".join(stripped)
