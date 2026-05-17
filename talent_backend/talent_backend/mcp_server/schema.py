"""Live graph-schema discovery for the talent MCP server.

The DB is the single source of truth for:
  - node labels and their properties
  - edge types and their endpoints
  - low-cardinality enum-like value sets (skill_level, region, cert status, …)

Nothing in this codebase should hardcode any of those. Modules that need
them (the typed `find_employees` tool, agent prompts) call into the
cache here.

Schema is loaded once on first request and re-loaded on demand via
`refresh_graph_schema()`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, asdict

from .app import _pg
from .pg_age_helper import _sanitize_sql_string

logger = logging.getLogger("talent_mcp")


# ── Enum-like properties to sample ─────────────────────────────────────
# (label, property, max_distinct) — properties whose distinct value set
# is bounded and useful as an LLM-facing enum.  If a property has more
# than ``max_distinct`` distinct values it isn't surfaced as an enum.
_ENUM_SAMPLE_TARGETS: list[tuple[str, str, int]] = [
    ("Employee", "skill_level", 20),
    ("Employee", "employment_status", 20),
    ("Employee", "delivery_model", 20),
    ("Country", "region", 20),
    ("Country", "name", 50),
]

# (edge_type, property, max_distinct)
_EDGE_ENUM_TARGETS: list[tuple[str, str, int]] = [
    ("HOLDS_CERT", "status", 10),
    ("HAS_SKILL", "level", 20),
    ("SPEAKS", "level", 20),
]


@dataclass
class GraphSchema:
    graph_name: str
    nodes: dict[str, list[str]] = field(default_factory=dict)        # label → property names
    edges: dict[str, dict] = field(default_factory=dict)             # type → {start, end, properties}
    enums: dict[str, list[str]] = field(default_factory=dict)        # "Label.prop" → distinct values

    def to_dict(self) -> dict:
        return asdict(self)

    # ── enum lookup helpers ────────────────────────────────────────────
    def enum_values(self, label: str, prop: str) -> list[str]:
        return self.enums.get(f"{label}.{prop}", [])

    def edge_enum_values(self, edge_type: str, prop: str) -> list[str]:
        return self.enums.get(f"{edge_type}.{prop}", [])


# ── Module-level cache ─────────────────────────────────────────────────
_cache: dict[str, GraphSchema] = {}
_cache_lock = asyncio.Lock()


async def load_graph_schema(graph_name: str, force: bool = False) -> GraphSchema:
    """Return the cached schema, loading from the DB on first call."""
    if not force and graph_name in _cache:
        return _cache[graph_name]

    async with _cache_lock:
        if not force and graph_name in _cache:
            return _cache[graph_name]
        schema = await _discover(graph_name)
        _cache[graph_name] = schema
        return schema


async def refresh_graph_schema(graph_name: str) -> GraphSchema:
    """Force a re-discovery (drops the cached entry first)."""
    return await load_graph_schema(graph_name, force=True)


# ── Discovery ──────────────────────────────────────────────────────────
async def _discover(graph_name: str) -> GraphSchema:
    logger.info("[schema] discovering for graph=%s", graph_name)
    schema = GraphSchema(graph_name=graph_name)
    pg = _pg()
    g = _sanitize_sql_string(graph_name)

    # ── Node labels ────────────────────────────────────────────────────
    labels_sql = (
        f"SELECT * FROM ag_catalog.cypher('{g}', $$\n"
        f"  MATCH (n) RETURN DISTINCT labels(n) AS lbl\n"
        f"$$) AS (lbl ag_catalog.agtype);"
    )
    label_rows = await pg.query_using_sql_cypher(labels_sql, graph_name)
    labels: list[str] = []
    for r in label_rows:
        v = r.get("lbl")
        if isinstance(v, list) and v:
            labels.append(str(v[0]))
        elif isinstance(v, str):
            labels.append(v)
    labels = sorted(set(labels))

    # ── Sample one node per label for property keys ───────────────────
    for label in labels:
        keys_sql = (
            f"SELECT * FROM ag_catalog.cypher('{g}', $$\n"
            f"  MATCH (n:{label}) RETURN keys(n) AS k LIMIT 1\n"
            f"$$) AS (k ag_catalog.agtype);"
        )
        try:
            rows = await pg.query_using_sql_cypher(keys_sql, graph_name)
        except Exception as ex:
            logger.warning("[schema] keys lookup failed for %s: %s", label, ex)
            continue
        if not rows:
            schema.nodes[label] = []
            continue
        k = rows[0].get("k")
        if isinstance(k, list):
            schema.nodes[label] = [str(x) for x in k]
        else:
            schema.nodes[label] = []

    # ── Edge types and their endpoints + sample property keys ─────────
    edges_sql = (
        f"SELECT * FROM ag_catalog.cypher('{g}', $$\n"
        f"  MATCH (a)-[r]->(b)\n"
        f"  RETURN DISTINCT type(r) AS rel, labels(a) AS src, labels(b) AS dst\n"
        f"$$) AS (rel ag_catalog.agtype, src ag_catalog.agtype, dst ag_catalog.agtype);"
    )
    edge_rows = await pg.query_using_sql_cypher(edges_sql, graph_name)
    for r in edge_rows:
        rel = r.get("rel")
        src = r.get("src")
        dst = r.get("dst")
        if isinstance(rel, str):
            src_lbl = src[0] if isinstance(src, list) and src else (src if isinstance(src, str) else "")
            dst_lbl = dst[0] if isinstance(dst, list) and dst else (dst if isinstance(dst, str) else "")
            entry = schema.edges.setdefault(rel, {"start": set(), "end": set(), "properties": []})
            entry["start"].add(src_lbl)
            entry["end"].add(dst_lbl)

    # Convert sets to sorted lists for serialisation, and sample edge property keys.
    for rel, entry in list(schema.edges.items()):
        entry["start"] = sorted(entry["start"])
        entry["end"] = sorted(entry["end"])
        keys_sql = (
            f"SELECT * FROM ag_catalog.cypher('{g}', $$\n"
            f"  MATCH ()-[r:{rel}]->() RETURN keys(r) AS k LIMIT 1\n"
            f"$$) AS (k ag_catalog.agtype);"
        )
        try:
            rows = await pg.query_using_sql_cypher(keys_sql, graph_name)
        except Exception as ex:
            logger.warning("[schema] edge key lookup failed for %s: %s", rel, ex)
            continue
        if rows:
            k = rows[0].get("k")
            if isinstance(k, list):
                entry["properties"] = [str(x) for x in k]

    # ── Enum value sampling ───────────────────────────────────────────
    for label, prop, max_distinct in _ENUM_SAMPLE_TARGETS:
        if label not in schema.nodes or prop not in schema.nodes.get(label, []):
            continue
        await _sample_enum(schema, graph_name, label, prop, max_distinct, edge=False)

    for rel, prop, max_distinct in _EDGE_ENUM_TARGETS:
        if rel not in schema.edges or prop not in schema.edges[rel].get("properties", []):
            continue
        await _sample_enum(schema, graph_name, rel, prop, max_distinct, edge=True)

    logger.info(
        "[schema] loaded: %d nodes, %d edges, %d enums",
        len(schema.nodes),
        len(schema.edges),
        len(schema.enums),
    )
    return schema


async def _sample_enum(
    schema: GraphSchema,
    graph_name: str,
    label_or_rel: str,
    prop: str,
    max_distinct: int,
    edge: bool,
) -> None:
    g = _sanitize_sql_string(graph_name)
    if edge:
        cypher = (
            f"MATCH ()-[r:{label_or_rel}]->() "
            f"RETURN DISTINCT r.{prop} AS v LIMIT {max_distinct + 1}"
        )
    else:
        cypher = (
            f"MATCH (n:{label_or_rel}) "
            f"RETURN DISTINCT n.{prop} AS v LIMIT {max_distinct + 1}"
        )
    sql = (
        f"SELECT * FROM ag_catalog.cypher('{g}', $$\n  {cypher}\n$$) "
        f"AS (v ag_catalog.agtype);"
    )
    try:
        rows = await _pg().query_using_sql_cypher(sql, graph_name)
    except Exception as ex:
        logger.warning("[schema] enum sample failed for %s.%s: %s", label_or_rel, prop, ex)
        return
    values = [r.get("v") for r in rows if r.get("v") is not None]
    values = [str(v) for v in values if v != ""]
    if not values or len(values) > max_distinct:
        return
    key = f"{label_or_rel}.{prop}"
    schema.enums[key] = sorted(set(values))


# ── Validation helpers used by typed tools ─────────────────────────────
class SchemaValidationError(ValueError):
    """Raised when a typed-tool input doesn't match a DB-discovered enum."""


def validate_enum(
    schema: GraphSchema,
    label_or_rel: str,
    prop: str,
    value: str,
) -> None:
    """Raise SchemaValidationError if value is not in the cached enum set."""
    valid = schema.enums.get(f"{label_or_rel}.{prop}")
    if valid is None:
        return  # property isn't a tracked enum — skip
    if value not in valid:
        raise SchemaValidationError(
            f"{label_or_rel}.{prop}={value!r} is not valid. "
            f"Valid values (from DB): {valid}"
        )
