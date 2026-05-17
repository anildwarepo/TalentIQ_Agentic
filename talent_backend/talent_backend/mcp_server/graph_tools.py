"""MCP tools for graph query, search, and analytics.

Three tools — the agent already knows the ontology, so no discovery needed.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from typing import Annotated

from fastmcp import Context

from .app import mcp, _pg
from .cypher_rewriter import optimize_sql
from .helpers import (
    strip_agtype,
    strip_titles_for_search,
    extract_search_words,
    name_matches_search,
)
from .pg_age_helper import _sanitize_sql_string

logger = logging.getLogger("talent_mcp")


# ═════════════════════════════════════════════════════════════
# 1. query_using_sql_cypher — execute any SQL/Cypher query
# ═════════════════════════════════════════════════════════════

@mcp.tool
async def query_using_sql_cypher(
    sql_query: Annotated[str, "SQL Query (may wrap ag_catalog.cypher calls). Entity matching in Cypher MUST use exact code match (e.g. v.code = 'PMP') from resolve_entities — do NOT use regex on names."],
    graph_name: Annotated[str, "Graph name for AGE cypher calls"],
    ctx: Context = None,
) -> list[dict]:
    """Execute a SQL/Cypher query against PostgreSQL+AGE and return the result rows.

    IMPORTANT — Entity matching in Cypher:
    - Call resolve_entities FIRST to get canonical codes
    - Use exact code match: WHERE v.code = 'RESOLVED_CODE'
    - Do NOT use regex (~) or CONTAINS on entity names
    - Do NOT fall back to search_graph or vector_search for entity lookup
    """
    # ── Deterministic rewrite for known AGE perf anti-patterns ────────
    # Pushes ORDER BY+LIMIT before OPTIONAL MATCH enrichment when safe.
    try:
        rewritten_sql, rewrite_reason = optimize_sql(sql_query)
    except ValueError as exc:
        # Unsupported construct detected (e.g. count(CASE WHEN ...))
        logger.warning("[query] rejected: %s", exc)
        if ctx:
            await ctx.info(f"[REJECTED] {exc}")
        return [{"error": str(exc)}]
    if rewrite_reason:
        logger.info("[query] rewrite=%s applied", rewrite_reason)
        if ctx:
            await ctx.info(f"[REWRITE] {rewrite_reason}: optimized Cypher for AGE compatibility")
        sql_query = rewritten_sql

    # Detect query type from SQL content
    sql_lower = sql_query.lower()
    if "ag_catalog.cypher" in sql_lower:
        query_type = "CYPHER"
    elif "search_graph_nodes" in sql_lower:
        query_type = "FTS"
    elif "embedding" in sql_lower or "vector" in sql_lower:
        query_type = "VECTOR"
    else:
        query_type = "SQL"

    logger.info("[query] graph=%s type=%s sql=%s", graph_name, query_type, sql_query[:120])
    if ctx:
        await ctx.info(f"[QUERY] {query_type}: {sql_query}")

    query_start = time.perf_counter()
    rows = await _pg().query_using_sql_cypher(sql_query, graph_name)
    query_ms = (time.perf_counter() - query_start) * 1000

    logger.info("[query] %d rows in %.0fms", len(rows), query_ms)
    if ctx:
        await ctx.info(f"[RESULT] {query_type} returned {len(rows)} rows ({query_ms:.0f}ms)")
    return rows


# ═════════════════════════════════════════════════════════════
# 2. search_graph — full-text search across graph nodes
# ═════════════════════════════════════════════════════════════

@mcp.tool
async def search_graph(
    search_term: Annotated[str, "Person name to search for (e.g. 'Jane Smith'). For entity lookups (skills, certs, etc.) use resolve_entities instead."],
    graph_name: Annotated[str, "Graph name"],
    label_filter: Annotated[str, "Optional: filter to a specific node label (typically 'Employee'). Empty string for all."] = "",
    max_results: Annotated[int, "Maximum results to return (default 10)"] = 10,
    ctx: Context = None,
) -> dict:
    """Full-text search for finding employees by name in the graph.

    Use ONLY for looking up a specific person by name (e.g. 'Jane Smith').
    Do NOT use for entity resolution (skills, certifications, countries, etc.)
    — use resolve_entities for that instead.
    """
    logger.info("[search] term=%s label=%s max=%d", search_term, label_filter or "(all)", max_results)
    if ctx:
        await ctx.info(f"[QUERY] FTS: Searching for '{search_term}' (label: {label_filter or 'all'})")

    fts_term = strip_titles_for_search(search_term)
    if fts_term != search_term:
        logger.info("[search] Stripped titles: '%s' → '%s'", search_term, fts_term)

    label_clause = (
        f"WHERE node_label = '{_sanitize_sql_string(label_filter)}'" if label_filter else ""
    )

    sql = f"""
        SELECT props->'payload'->>'id' AS entity_id,
               node_label,
               props->'payload'->>'name' AS name,
               props->'payload' AS payload,
               rank
        FROM public.search_graph_nodes('{_sanitize_sql_string(fts_term)}')
        {label_clause}
        ORDER BY rank DESC
        LIMIT {int(max_results)};
    """

    rows = await _pg().query_using_sql_cypher(sql, None)
    logger.info("[search] Found %d results", len(rows))

    # Retry with progressively shorter terms if nothing found
    if not rows and len(fts_term.split()) > 1:
        words = fts_term.split()
        for trim in range(1, min(4, len(words))):
            shorter = " ".join(words[: len(words) - trim])
            if len(shorter) < 3:
                break
            retry_sql = f"""
                SELECT props->'payload'->>'id' AS entity_id,
                       node_label,
                       props->'payload'->>'name' AS name,
                       props->'payload' AS payload,
                       rank
                FROM public.search_graph_nodes('{_sanitize_sql_string(shorter)}')
                {label_clause}
                ORDER BY rank DESC
                LIMIT {int(max_results)};
            """
            rows = await _pg().query_using_sql_cypher(retry_sql, None)
            if rows:
                logger.info("[search] Retry with '%s' found %d results", shorter, len(rows))
                break

    label_counts = Counter(r.get("node_label", "") for r in rows)

    compact_results: list[dict] = []
    for r in rows:
        entry: dict = {
            "entity_id": r.get("entity_id"),
            "node_label": r.get("node_label"),
            "name": r.get("name"),
        }
        if len(compact_results) < 3:
            try:
                payload = r.get("payload")
                if isinstance(payload, str):
                    payload = json.loads(payload)
                entry["payload"] = payload
            except Exception:
                pass
        compact_results.append(entry)

    # Name verification
    search_words = extract_search_words(search_term)
    if search_words and len(compact_results) > 1:
        for entry in compact_results:
            entry["name_match"] = name_matches_search(entry.get("name", ""), search_words)
        verified = [r for r in compact_results if r.get("name_match")]
        if verified:
            logger.info("[search] Name verification: %d FTS → %d verified", len(compact_results), len(verified))
            compact_results = verified
            label_counts = Counter(r.get("node_label", "") for r in compact_results)

    if ctx:
        await ctx.info(f"[RESULT] FTS returned {len(compact_results)} results")

    return {
        "results": compact_results,
        "label_summary": dict(label_counts),
        "search_term": search_term,
        "total_found": len(compact_results),
    }


# ═════════════════════════════════════════════════════════════
# 3. analyze_graph_statistics — node/edge counts
# ═════════════════════════════════════════════════════════════

@mcp.tool
async def analyze_graph_statistics(
    graph_name: Annotated[str, "Graph name to analyze"],
    ctx: Context = None,
) -> dict:
    """Count nodes per label, edges per relationship type, and total connectivity."""
    logger.info("[stats] graph=%s", graph_name)
    if ctx:
        await ctx.info(f"[QUERY] STATS: Analyzing '{graph_name}'")

    stats: dict = {
        "graph_name": graph_name,
        "node_counts": {},
        "edge_counts": {},
        "total_nodes": 0,
        "total_edges": 0,
    }

    # Nodes per label
    node_sql = f"""SELECT * FROM ag_catalog.cypher('{_sanitize_sql_string(graph_name)}', $$
  MATCH (n) RETURN labels(n) AS label, count(*) AS cnt
$$) AS (label ag_catalog.agtype, cnt ag_catalog.agtype);"""
    try:
        node_rows = await _pg().query_using_sql_cypher(node_sql, graph_name)
        for r in node_rows:
            lbl = strip_agtype(r["label"])
            cnt = int(str(r["cnt"]).strip('"'))
            stats["node_counts"][lbl] = cnt
            stats["total_nodes"] += cnt
    except Exception as e:
        logger.warning("[stats] Node count error: %s", e)

    # Edges per relationship type
    edge_sql = f"""SELECT * FROM ag_catalog.cypher('{_sanitize_sql_string(graph_name)}', $$
  MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt
$$) AS (rel ag_catalog.agtype, cnt ag_catalog.agtype);"""
    try:
        edge_rows = await _pg().query_using_sql_cypher(edge_sql, graph_name)
        for r in edge_rows:
            rel = strip_agtype(r["rel"])
            cnt = int(str(r["cnt"]).strip('"'))
            stats["edge_counts"][rel] = cnt
            stats["total_edges"] += cnt
    except Exception as e:
        logger.warning("[stats] Edge count error: %s", e)

    logger.info("[stats] Done: %d nodes, %d edges", stats["total_nodes"], stats["total_edges"])
    if ctx:
        await ctx.info(
            f"[RESULT] STATS: {stats['total_nodes']:,} nodes, {stats['total_edges']:,} edges"
        )
    return stats
