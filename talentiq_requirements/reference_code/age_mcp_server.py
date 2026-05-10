import sys, asyncio
import os
import logging
import time

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # Force pure-python psycopg on Windows if libpq is available —
    # the binary backend's bundled libpq has SSL issues with Azure PostgreSQL on Python 3.13+
    try:
        import psycopg.pq._pq_ctypes  # noqa: F401 — test if libpq is importable
        os.environ.setdefault("PSYCOPG_IMPL", "python")
    except (ImportError, OSError):
        pass  # no system libpq — keep using binary backend
from typing import Annotated
from fastmcp import FastMCP, Context
from fastmcp.server.context import AcceptedElicitation, DeclinedElicitation, CancelledElicitation
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pg_age_helper import PGAgeHelper
from telemetry import (
    configure_mcp_telemetry, record_server_init, record_tool_call,
    record_cypher_query, record_error, record_pg_connect,
    tool_span, cypher_span, get_tracer,
)

# --- File logging ---
_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "age_mcp_server.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),  # keep console output too
    ],
)
logger = logging.getLogger("age_mcp")
logger.info(f"Logging to {_log_file}")


load_dotenv()

# ── Telemetry ────────────────────────────────────────────────
configure_mcp_telemetry("talentiq-mcp-graph-server")

mcp = FastMCP("TalentIQ Graph MCP Server")


def _strip_agtype(val) -> str:
    """Strip AGE agtype formatting: '["Label"]' -> 'Label', '"rel"' -> 'rel'."""
    if not isinstance(val, str):
        return str(val)
    val = val.strip()
    if val.startswith('["') and val.endswith('"]'):
        val = val[2:-2]
    elif val.startswith('"') and val.endswith('"') and len(val) > 1:
        val = val[1:-1]
    return val

GRAPH_NAME = os.getenv("GRAPH_NAME", "talent_graph")
_ONTOLOGY_MEMORY: dict[str, str] = {}

# Pre-load talent_graph ontology so agents skip discovery
_TALENT_GRAPH_ONTOLOGY = """
Graph: talent_graph (130,000 DXC employees)

NODE LABELS (14):
  Employee (130,000) — payload: name, first_name, last_name, email, phone, workday_id, job_title, job_level (int 3-14), skill_level (Junior/Mid/Senior/Lead/Principal/Architect), hire_date, years_of_experience (int), employment_status (Active/Bench/Notice Period/Long-term Leave), is_bench (bool), bench_start_date, bench_duration_days (int), availability_date, current_project, fte_current_month (int %), fte_next_month, fte_next2_month, hourly_cost_usd (float), bill_rate_usd (float), cv_last_updated, cv_freshness_days (int), cv_source, impressiveness_score (float 0-100), data_source, delivery_model (onshore/nearshore/offshore), eqf_level (int 5-8), meces_level (int 1-4), eqf_mapping_status, education_degree, education_field, resume_summary (free text)
  Location (46) — payload: city, country, country_code, region, subregion, zip, address, timezone, delivery_model
  Country (19) — payload: name, code, region
  Subregion (15) — payload: name, region
  Skill (96) — payload: name
  SkillDomain (13) — payload: name (Python, Java, C#/.NET, JavaScript/TS, Cloud (Azure), Cloud (AWS), DevOps/SRE, Data Engineering, AI/ML, SAP, Salesforce, Cybersecurity, ServiceNow)
  Certification (39) — payload: name
  Language (18) — payload: name
  ServiceLine (8) — payload: name
  Offering (8) — payload: name
  Manager (80) — payload: name, email, employee_id
  University (75) — payload: name
  Client (36) — payload: name
  Project (22) — payload: name

EDGE LABELS (12):
  LOCATED_IN: Employee -> Location (no props)
  IN_COUNTRY: Location -> Country (no props)
  SPECIALIZES_IN: Employee -> SkillDomain (no props)
  HAS_SKILL: Employee -> Skill (payload: level, years_of_experience, active, is_primary)
  HOLDS_CERT: Employee -> Certification (payload: issue_date, expiry_date, status [Valid/Expiring/Expired], credential_id, has_evidence)
  SPEAKS: Employee -> Language (payload: level [CEFR: A1-C2], is_native)
  BELONGS_TO_SL: Employee -> ServiceLine (no props)
  WORKS_IN_OFFERING: Employee -> Offering (no props)
  REPORTS_TO: Employee -> Manager (no props)
  STUDIED_AT: Employee -> University (payload: degree, field, graduation_year, eqf_level, meces_level)
  WORKED_FOR: Employee -> Client (payload: role, project, start_date, end_date, is_current)
  WORKED_ON: Employee -> Project (payload: role, start_date, end_date)

AGE QUERY PATTERN (use WITH for aggregation ORDER BY):
  WRONG:  RETURN c.payload.name AS country, count(e) AS cnt ORDER BY cnt DESC
  CORRECT: WITH c.payload.name AS country, count(e) AS cnt RETURN country, cnt ORDER BY cnt DESC

PROPERTY ACCESS: All via payload.* (e.g., e.payload.name, hs.payload.level)
""".strip()

_ONTOLOGY_MEMORY["talent_graph"] = _TALENT_GRAPH_ONTOLOGY
# Track which graph names have been confirmed via elicitation per user session.
# Key: session_id, Value: set of confirmed graph names.
_CONFIRMED_GRAPHS: dict[str, set[str]] = {}
_ELICITATION_LOCK = asyncio.Lock()
# Pre-confirm the primary graph name so elicitation is never attempted for it
_PRECONFIRMED_GRAPH = GRAPH_NAME

# --- Name verification helpers (shared across search tools) ---
# Common honorifics, titles, and connectors to skip when extracting name keywords.
_NAME_SKIP_TITLES = frozenset({
    # Honorifics
    "dr", "mr", "mrs", "ms", "prof", "sir", "dame", "rev",
    # Connectors / articles
    "the", "of", "and", "for", "at", "in",
    # DXC-specific titles that may prefix employee names
    "lead", "senior", "junior", "principal", "architect",
    "manager", "director", "engineer", "developer", "consultant",
})

def _extract_search_words(search_term: str) -> list[str]:
    """Extract significant words from a search term, skipping titles/particles and short words."""
    return [w.lower().strip(".,;:") for w in search_term.split()
            if w.lower().strip(".,;:") not in _NAME_SKIP_TITLES and len(w.strip(".,;:")) >= 2]

def _name_matches_search(name: str, search_words: list[str]) -> bool:
    """Check if a name contains ALL significant search words."""
    if not search_words or not name:
        return True  # no filtering if no search words or no name
    name_lower = name.lower()
    return all(w in name_lower for w in search_words)

def _strip_titles_for_search(search_term: str) -> str:
    """Strip known titles/honorifics from a search term to maximize FTS recall.

    FTS (websearch_to_tsquery) requires ALL words to match.  Titles like
    'Mayor' or 'Dr.' that don't appear in the stored entity name reduce
    recall and cause non-deterministic results.  Name verification later
    filters any false positives introduced by the broader search.

    Domain-agnostic: only strips generic English titles/particles from
    _NAME_SKIP_TITLES.  Preserves the original term if stripping would
    leave fewer than 2 meaningful words (to avoid over-broad searches
    in domains where a "title" word is actually part of the entity name).
    """
    words = search_term.split()
    stripped = [w for w in words if w.lower().strip(".,;:") not in _NAME_SKIP_TITLES]
    # Keep original if stripping would leave fewer than 2 words —
    # prevents over-broad FTS when most of the term consists of title words
    if len(stripped) < 2 and len(words) >= 2:
        return search_term
    if not stripped:
        return search_term
    return " ".join(stripped)


@mcp.tool
async def save_ontology(
    ontology: Annotated[str, "Generated ontology content to store in memory"],
    graph_name: Annotated[str | None, "Graph name for ontology cache key"] = None,
    ctx: Context = None,
) -> dict:
    """
    Save the generated ontology in process memory.
    Args:
        ontology: The ontology content as text.
    Returns:
        Status indicating ontology was saved.
    """
    graph_key = (graph_name or GRAPH_NAME or "default").strip()
    if ctx: await ctx.info(f"[save_ontology] Saving ontology for graph '{graph_key}' ({len(ontology)} chars)")
    _ONTOLOGY_MEMORY[graph_key] = ontology

    print("Ontology saved in memory for graph:", graph_key, "length:", len(ontology))
    if ctx: await ctx.info(f"[save_ontology] Ontology saved successfully for graph '{graph_key}'")
    return {
        "status": "saved",
        "has_ontology": True,
        "graph_name": graph_key,
        "length": len(ontology),
    }


@mcp.tool
async def fetch_ontology(
    graph_name: Annotated[str | None, "Graph name for ontology cache lookup"] = None,
    ctx: Context = None,
) -> dict:
    """
    Fetch the ontology previously saved in process memory.
    Returns:
        The saved ontology content, if any.
    """
    graph_key = (graph_name or GRAPH_NAME or "default").strip()
    ontology = _ONTOLOGY_MEMORY.get(graph_key)
    if ctx: await ctx.info(f"[fetch_ontology] Fetching ontology for graph '{graph_key}': {'found' if ontology else 'not found'}")
    print("Fetching ontology from memory for graph:", graph_key, "has ontology:", ontology is not None)
    return {
        "has_ontology": ontology is not None,
        "graph_name": graph_key,
        "ontology": ontology,
    }

@mcp.tool
async def resolve_entity_ids(
    search_term: Annotated[str, "The search term to find entities (e.g., a person name, topic)"],
    graph_name: Annotated[str, "Graph name to query for edges (e.g., 'meetings_graph_v2')"],
    node_label: Annotated[str, "The node label to filter results to (case-sensitive). Use empty string '' to search ALL labels."] = "",
    id_property: Annotated[str, "Dot-separated path to the ID property. Default: payload.id"] = "payload.id",
    ctx: Context = None,
) -> dict:
    """
    Find entities matching a search term, then discover their edges and related node types.
    Returns entity IDs grouped by label PLUS outbound/inbound edge types for the top-ranked label.
    This gives the agent everything needed to build a query in one call.

    Args:
        search_term: The search term to look up via full-text search.
        graph_name: The graph to query for edge discovery.
        node_label: Exact node label to filter to. Empty string = search all labels.
        id_property: Dot-separated path to the ID field (default: payload.id).
    Returns:
        A dict with:
        - ids_by_label: dict mapping label -> list of entity IDs
        - anchor_label: the best-matching label (most IDs)
        - anchor_ids: the IDs for the anchor label
        - outbound_edges: list of {rel, target_label, count} from anchor nodes
        - inbound_edges: list of {source_label, rel, count} into anchor nodes
        - search_term: the original search term
    """
    # Normalize node_label in case it arrives in agtype format: ["Label"] -> Label
    if node_label:
        node_label = _strip_agtype(node_label)

    # Build the JSON extraction chain from the dot-separated path
    parts = id_property.split(".")
    json_path = "props"
    for part in parts[:-1]:
        json_path += f"->'{part}'"
    json_path += f"->>'{parts[-1]}'"

    # Strip titles/honorifics before FTS to ensure consistent recall
    # regardless of whether the agent includes titles like "Mayor" or "Dr."
    fts_term = _strip_titles_for_search(search_term)
    if fts_term != search_term:
        print(f"[resolve_entity_ids] Stripped titles for FTS: '{search_term}' → '{fts_term}'")
        if ctx: await ctx.info(f"[resolve_entity_ids] Stripped titles for FTS: '{search_term}' → '{fts_term}'")

    sql = f"""
        SELECT {json_path} AS entity_id, node_label
        FROM public.search_graph_nodes('{fts_term.replace("'", "''")}')
        {"WHERE node_label = '" + node_label.replace("'", "''") + "'" if node_label else ""}
        ORDER BY rank DESC;
    """
    print(f"[resolve_entity_ids] search_term={search_term}, fts_term={fts_term}, node_label={node_label or '(all)'}")
    print(f"[resolve_entity_ids] SQL: {sql}")
    if ctx: await ctx.info(f"[resolve_entity_ids] Searching for '{fts_term}' (label: {node_label or 'all'})")

    rows = await pg_helper.query_using_sql_cypher(sql, None)

    # Fallback: retry with shorter terms if nothing found
    if not rows:
        words = fts_term.split()
        retry_terms = []
        for trim_count in range(1, min(3, len(words))):
            shorter = " ".join(words[: len(words) - trim_count])
            if len(shorter.split()) >= 2 and shorter not in retry_terms:
                retry_terms.append(shorter)
        for trim_count in range(1, min(3, len(words))):
            shorter = " ".join(words[trim_count:])
            if len(shorter.split()) >= 2 and shorter not in retry_terms:
                retry_terms.append(shorter)
        if len(words) >= 2:
            for w in words:
                if len(w) >= 3 and w not in retry_terms:
                    retry_terms.append(w)

        for shorter in retry_terms:
            sql_retry = f"""
                SELECT {json_path} AS entity_id, node_label
                FROM public.search_graph_nodes('{shorter.replace("'", "''")}')
                {"WHERE node_label = '" + node_label.replace("'", "''") + "'" if node_label else ""}
                ORDER BY rank DESC;
            """
            print(f"[resolve_entity_ids] Retry with shorter term: {shorter}")
            if ctx: await ctx.info(f"[resolve_entity_ids] Retrying with shorter term: '{shorter}'")
            rows = await pg_helper.query_using_sql_cypher(sql_retry, None)
            if rows:
                break

    # Group IDs by label — cap at 10 IDs per label to save context
    ids_by_label: dict[str, list[str]] = {}
    for row in rows:
        eid = row.get("entity_id")
        lbl = row.get("node_label")
        if eid is not None and lbl is not None:
            ids_by_label.setdefault(lbl, [])
            if eid not in ids_by_label[lbl] and len(ids_by_label[lbl]) < 10:
                ids_by_label[lbl].append(eid)

    if not ids_by_label:
        return {
            "ids_by_label": {},
            "anchor_label": None,
            "anchor_ids": [],
            "outbound_edges": [],
            "inbound_edges": [],
            "search_term": search_term,
            "hint": "No entities found. Try a different search term or drop titles (Mayor, Dr., etc.)",
        }

    # If no node_label specified, return compact summary — label counts only, not all IDs
    if not node_label:
        label_summary = {_strip_agtype(lbl): len(ids) for lbl, ids in ids_by_label.items()}
        return {
            "labels_found": label_summary,
            "anchor_label": None,
            "anchor_ids": [],
            "outbound_edges": [],
            "inbound_edges": [],
            "search_term": search_term,
            "hint": "ERROR: node_label is required. Call discover_nodes first to find the correct label, then call resolve_entity_ids again with node_label set.",
        }

    # node_label was specified — use it as anchor and discover edges
    anchor_label = node_label
    anchor_ids = ids_by_label.get(anchor_label, [])

    if not anchor_ids:
        return {
            "ids_by_label": ids_by_label,
            "anchor_label": anchor_label,
            "anchor_ids": [],
            "outbound_edges": [],
            "inbound_edges": [],
            "search_term": search_term,
            "hint": f"No IDs found for label '{anchor_label}'. Available labels: {list(ids_by_label.keys())}",
        }

    # --- Name verification: filter FTS false positives ---
    # FTS weight-C matches nodes whose description/attributes MENTION the search
    # term, not just nodes NAMED that term. Verify actual names to avoid
    # inflated entity counts that produce wrong aggregation results.
    cypher_id_path = ".".join(id_property.split("."))
    _name_verified = False
    _safe_verify = ", ".join(f"'{eid.replace(chr(39), chr(39)+chr(39))}'" for eid in anchor_ids)
    verify_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (n:{anchor_label})
  WHERE n.{cypher_id_path} IN [{_safe_verify}]
  RETURN n.{cypher_id_path} AS id, n.payload.name AS name
$$) AS (id ag_catalog.agtype, name ag_catalog.agtype);"""
    try:
        verify_rows = await pg_helper.query_using_sql_cypher(verify_sql, graph_name)
        search_words = _extract_search_words(search_term)
        if search_words and verify_rows:
            verified_ids = []
            for row in verify_rows:
                name_val = _strip_agtype(row.get("name", ""))
                if _name_matches_search(name_val, search_words):
                    verified_ids.append(_strip_agtype(row.get("id")))
            if verified_ids:
                _name_verified = True
                if len(verified_ids) != len(anchor_ids):
                    print(f"[resolve_entity_ids] Name verification: {len(anchor_ids)} FTS hits → {len(verified_ids)} verified")
                    if ctx: await ctx.info(f"[resolve_entity_ids] Name verification: {len(anchor_ids)} FTS hits → {len(verified_ids)} name-verified")
                else:
                    print(f"[resolve_entity_ids] Name verification: all {len(anchor_ids)} FTS hits confirmed")
                    if ctx: await ctx.info(f"[resolve_entity_ids] Name verification: all {len(anchor_ids)} IDs confirmed")
                anchor_ids = verified_ids
                ids_by_label[anchor_label] = verified_ids
            else:
                # If nothing matched strictly, keep the best FTS result (rank-ordered)
                print(f"[resolve_entity_ids] Name verification: strict match failed, keeping top FTS result")
                if ctx: await ctx.info(f"[resolve_entity_ids] Name verification: no strict match, keeping top FTS result")
                anchor_ids = anchor_ids[:1]
                ids_by_label[anchor_label] = anchor_ids
    except Exception as e:
        print(f"[resolve_entity_ids] Name verification query failed (non-fatal): {e}")
    # --- End name verification ---

    # Use up to 5 IDs for edge discovery to keep it fast
    sample_ids = anchor_ids[:5]
    safe_ids = ", ".join(f"'{eid.replace(chr(39), chr(39)+chr(39))}'" for eid in sample_ids)

    # Discover outbound edges
    outbound_edges = []
    try:
        out_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (a:{anchor_label})-[r]->(b)
  WHERE a.{cypher_id_path} IN [{safe_ids}]
  RETURN type(r) AS rel, labels(b) AS tgt, count(*) AS cnt
$$) AS (rel ag_catalog.agtype, tgt ag_catalog.agtype, cnt ag_catalog.agtype);"""
        print(f"[resolve_entity_ids] Discovering outbound edges...")
        if ctx: await ctx.info(f"[resolve_entity_ids] Discovering outbound edges for {anchor_label}...")
        out_rows = await pg_helper.query_using_sql_cypher(out_sql, graph_name)
        outbound_edges = [{"rel": _strip_agtype(r["rel"]), "target_label": _strip_agtype(r["tgt"]), "count": r["cnt"]} for r in out_rows]
    except Exception as e:
        print(f"[resolve_entity_ids] Outbound edge discovery failed: {e}")

    # Discover inbound edges
    inbound_edges = []
    try:
        in_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (a)-[r]->(b:{anchor_label})
  WHERE b.{cypher_id_path} IN [{safe_ids}]
  RETURN labels(a) AS src, type(r) AS rel, count(*) AS cnt
$$) AS (src ag_catalog.agtype, rel ag_catalog.agtype, cnt ag_catalog.agtype);"""
        print(f"[resolve_entity_ids] Discovering inbound edges...")
        if ctx: await ctx.info(f"[resolve_entity_ids] Discovering inbound edges for {anchor_label}...")
        in_rows = await pg_helper.query_using_sql_cypher(in_sql, graph_name)
        inbound_edges = [{"source_label": _strip_agtype(r["src"]), "rel": _strip_agtype(r["rel"]), "count": r["cnt"]} for r in in_rows]
    except Exception as e:
        print(f"[resolve_entity_ids] Inbound edge discovery failed: {e}")

    result = {
        "ids_by_label": ids_by_label,
        "anchor_label": anchor_label,
        "anchor_ids": anchor_ids,
        "name_verified": _name_verified,
        "outbound_edges": outbound_edges,
        "inbound_edges": inbound_edges,
        "search_term": search_term,
        "IMPORTANT": "These anchor_ids are name-verified and AUTHORITATIVE. Use ONLY these IDs in your query. Do NOT run additional entity searches via query_using_sql_cypher.",
    }
    print(f"[resolve_entity_ids] anchor_label={anchor_label}, anchor_ids={len(anchor_ids)}, outbound={len(outbound_edges)}, inbound={len(inbound_edges)}")
    if ctx: await ctx.info(f"[resolve_entity_ids] Done. anchor={anchor_label}, ids={len(anchor_ids)}, outbound_edges={len(outbound_edges)}, inbound_edges={len(inbound_edges)}")
    return result


# @mcp.tool
async def find_related_nodes(
    entity_ids: Annotated[list[str], "List of anchor entity IDs to find related nodes for"],
    anchor_label: Annotated[str, "The node label of the anchor entities (e.g., 'Product', 'Event')"],
    target_label: Annotated[str, "The node label to search for related nodes (e.g., 'Person', 'Organization')"],
    graph_name: Annotated[str, "Graph name to query"],
    id_property: Annotated[str, "Dot-separated path to the ID property (default: payload.id)"] = "payload.id",
) -> dict:
    """
    Find nodes of a target label that share source documents with the given anchor entities.
    Uses source-based co-occurrence: two nodes sharing a payload.sources entry means they
    participated in the same document/event context.

    Use this AFTER resolve_entity_ids when the user's question implies a related entity
    (e.g., "Who is the contact person for X?", "Who presented Y?", "What staff worked on Z?").

    Args:
        entity_ids: The anchor entity IDs (from resolve_entity_ids).
        anchor_label: Node label of the anchor (e.g., Product, Event).
        target_label: Node label to search for related nodes (e.g., Person, Organization).
        graph_name: The graph to query.
        id_property: Dot-separated path to the entity ID field.
    Returns:
        A dict with related_nodes (list of {id, name, properties}), count, and the query used.
    """
    # Build the Cypher property access from dot-separated path
    cypher_id_path = ".".join(f"{p}" for p in id_property.split("."))

    # Sanitize entity IDs to prevent injection
    safe_ids = ", ".join(f"'{eid.replace(chr(39), chr(39)+chr(39))}'" for eid in entity_ids)

    sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (anchor:{anchor_label}) WHERE anchor.{cypher_id_path} IN [{safe_ids}]
  UNWIND coalesce(anchor.payload.sources, []) AS src
  WITH DISTINCT src
  MATCH (related:{target_label}) WHERE related.payload.sources IS NOT NULL
  UNWIND coalesce(related.payload.sources, []) AS rsrc
  WITH related, rsrc, src WHERE rsrc = src
  RETURN DISTINCT related.{cypher_id_path} AS id, related.payload.name AS name, related.payload.attributes AS properties
$$) AS (id ag_catalog.agtype, name ag_catalog.agtype, properties ag_catalog.agtype);"""

    print(f"[find_related_nodes] anchor_label={anchor_label}, target_label={target_label}, entity_ids_count={len(entity_ids)}")
    print(f"[find_related_nodes] SQL: {sql}")

    try:
        rows = await pg_helper.query_using_sql_cypher(sql, graph_name)
    except Exception as e:
        return {
            "related_nodes": [],
            "count": 0,
            "error": str(e),
            "query": sql,
        }

    print(f"[find_related_nodes] Found {len(rows)} related nodes")
    return {
        "related_nodes": rows,
        "count": len(rows),
        "anchor_label": anchor_label,
        "target_label": target_label,
        "query": sql,
    }


@mcp.tool
async def discover_nodes(
    graph_name: Annotated[str, "Graph name to query (e.g., 'meetings_graph_v2')"],
    ctx: Context = None,
) -> list[dict]:
    """
    Discover all distinct node labels and their property structure.
    Returns a compact summary: label name + key property paths (not full payloads).
    Uses MCP elicitation to confirm the graph name with the user before running.
    Args:
        graph_name: The graph to query.
    Returns:
        A list of dicts with 'label' and 'property_paths' for each distinct node type.
    """
    # --- Elicitation: confirm graph name with the user ---
    if ctx and graph_name != _PRECONFIRMED_GRAPH:
        try:
            confirmed = await _confirm_graph_name(graph_name, ctx)
            if confirmed is None:
                return [{"status": "cancelled", "message": "Discovery cancelled by user."}]
            if confirmed != graph_name:
                await ctx.info(f"Graph name changed from '{graph_name}' to '{confirmed}'")
                graph_name = confirmed
        except Exception as e:
            logger.info(f"Elicitation not available ({e}), proceeding with '{graph_name}'")

    sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (n) WHERE n.payload IS NOT NULL
  RETURN labels(n) AS label, head(collect(n.payload)) AS sample_payload
$$) AS (label ag_catalog.agtype, sample_payload ag_catalog.agtype);"""

    print(f"[discover_nodes] graph_name={graph_name}")
    if ctx: await ctx.info(f"[discover_nodes] Discovering node labels in graph '{graph_name}'...")
    rows = await pg_helper.query_using_sql_cypher(sql, graph_name)
    print(f"[discover_nodes] Found {len(rows)} distinct node labels")
    if ctx: await ctx.info(f"[discover_nodes] Found {len(rows)} distinct node labels")

    # Extract compact summaries — just label + key property paths
    import json
    compact = []
    for row in rows:
        label = row.get("label", "")
        sample = row.get("sample_payload", "{}")
        # Parse the sample payload to extract property paths
        try:
            if isinstance(sample, str):
                payload = json.loads(sample)
            else:
                payload = sample
        except (json.JSONDecodeError, TypeError):
            payload = {}

        # Extract top-level keys and attributes keys — show as FULL CYPHER PATHS
        top_keys = list(payload.keys()) if isinstance(payload, dict) else []
        property_paths = [f"n.payload.{k}" for k in top_keys]

        attr_keys = []
        if isinstance(payload, dict) and "attributes" in payload and isinstance(payload["attributes"], dict):
            attr_keys = list(payload["attributes"].keys())
            property_paths.extend([f"n.payload.attributes.{k}" for k in attr_keys])

        has_sources = "sources" in top_keys
        sample_name = payload.get("name", "") if isinstance(payload, dict) else ""
        # Truncate name to 60 chars
        if len(sample_name) > 60:
            sample_name = sample_name[:60] + "..."

        compact.append({
            "label": _strip_agtype(label),
            "sample_name": sample_name,
            "property_paths": property_paths,
            "has_sources": has_sources,
        })

    return compact


@mcp.tool
async def search_graph(
    search_term: Annotated[str, "The text to search for (person name, agenda item title, meeting name, etc.)"],
    graph_name: Annotated[str, "Graph name (e.g., 'meetings_graph_v2')"],
    label_filter: Annotated[str, "Optional: filter results to a specific node label (e.g., 'Councilmember', 'City_Council_Meeting'). Empty string for all labels."] = "",
    max_results: Annotated[int, "Maximum number of results to return (default 10)"] = 10,
    ctx: Context = None,
) -> dict:
    """
    Search graph nodes using full-text search. Returns matching nodes with their labels, names, IDs, and properties.
    Use this to find entities mentioned in the user's question before writing a Cypher query.

    Args:
        search_term: The text to search for.
        graph_name: The graph name.
        label_filter: Optional node label to filter results.
        max_results: Max results to return.
    Returns:
        A dict with:
        - results: list of {node_label, entity_id, name, properties} for each match
        - search_term: the original search term
    """
    print(f"[search_graph] search_term={search_term}, label_filter={label_filter or '(all)'}, max_results={max_results}")
    if ctx: await ctx.info(f"[search_graph] Searching for '{search_term}' (label: {label_filter or 'all'}, max: {max_results})")

    # Strip titles/honorifics before FTS for consistent recall
    fts_term = _strip_titles_for_search(search_term)
    if fts_term != search_term:
        print(f"[search_graph] Stripped titles for FTS: '{search_term}' → '{fts_term}'")
        if ctx: await ctx.info(f"[search_graph] Stripped titles for FTS: '{search_term}' → '{fts_term}'")

    label_clause = f"WHERE node_label = '{label_filter.replace(chr(39), chr(39)+chr(39))}'" if label_filter else ""

    sql = f"""
        SELECT props->'payload'->>'id' AS entity_id,
               node_label,
               props->'payload'->>'name' AS name,
               props->'payload' AS payload,
               rank
        FROM public.search_graph_nodes('{fts_term.replace(chr(39), chr(39)+chr(39))}')
        {label_clause}
        ORDER BY rank DESC
        LIMIT {max_results};
    """

    rows = await pg_helper.query_using_sql_cypher(sql, None)
    print(f"[search_graph] Found {len(rows)} results")
    if ctx: await ctx.info(f"[search_graph] Found {len(rows)} results")

    # If no results, try progressively shorter search terms
    if not rows and len(fts_term.split()) > 1:
        words = fts_term.split()
        for trim in range(1, min(4, len(words))):
            shorter = " ".join(words[:len(words) - trim])
            if len(shorter) < 3:
                break
            retry_sql = f"""
                SELECT props->'payload'->>'id' AS entity_id,
                       node_label,
                       props->'payload'->>'name' AS name,
                       props->'payload' AS payload,
                       rank
                FROM public.search_graph_nodes('{shorter.replace(chr(39), chr(39)+chr(39))}')
                {label_clause}
                ORDER BY rank DESC
                LIMIT {max_results};
            """
            rows = await pg_helper.query_using_sql_cypher(retry_sql, None)
            if rows:
                print(f"[search_graph] Retry with '{shorter}' found {len(rows)} results")
                break

    # Group by label for summary
    from collections import Counter
    label_counts = Counter(r.get("node_label", "") for r in rows)

    # Compact results — include payload for top results only to save context
    compact_results = []
    for r in rows:
        entry = {
            "entity_id": r.get("entity_id"),
            "node_label": r.get("node_label"),
            "name": r.get("name"),
        }
        # Include full payload only for top 3 results
        if len(compact_results) < 3:
            import json as _json
            try:
                payload = r.get("payload")
                if isinstance(payload, str):
                    payload = _json.loads(payload)
                entry["payload"] = payload
            except Exception:
                pass
        compact_results.append(entry)

    # --- Name verification: mark which results are true name matches ---
    search_words = _extract_search_words(search_term)
    if search_words and len(compact_results) > 1:
        for entry in compact_results:
            entry["name_match"] = _name_matches_search(entry.get("name", ""), search_words)
        name_verified_results = [r for r in compact_results if r.get("name_match")]
        if name_verified_results:
            print(f"[search_graph] Name verification: {len(compact_results)} FTS hits → {len(name_verified_results)} name-verified")
            if ctx: await ctx.info(f"[search_graph] Name verification: {len(compact_results)} FTS hits → {len(name_verified_results)} name matches")
            compact_results = name_verified_results
            label_counts = Counter(r.get("node_label", "") for r in compact_results)

    return {
        "results": compact_results,
        "label_summary": dict(label_counts),
        "search_term": search_term,
        "total_found": len(compact_results),
    }


@mcp.tool
async def query_using_sql_cypher(
    sql_query: Annotated[str, "SQL Query"],
    graph_name: Annotated[str, "Graph name to use for ag_catalog.cypher(...)"]
    , ctx: Context = None,
) -> list[dict]:
    """
    Execute the sql statement against a PostgreSQL database with the AGE extension.
    The sql query is generated by another agent. This tool simply executes the query and returns the result.
    Args:
        sql_query: The SQL query to execute.
        graph_name: Graph name to use when executing AGE cypher calls.
    Returns:
        The query result as a list of dictionaries.
    """
    if ctx: await ctx.info(f"[query_using_sql_cypher] Executing query against graph '{graph_name}'...")
    # --- Elicitation: confirm graph name (once per session per graph name, serialized) ---
    # Skip elicitation for talent_graph — it's the primary graph and elicitation
    # is not supported by the agent framework client, saving ~0.4s per call.
    _sid = ctx.session_id if ctx else None
    _confirmed_for_session = _CONFIRMED_GRAPHS.get(_sid, set()) if _sid else set()
    if ctx and graph_name and graph_name not in _confirmed_for_session and graph_name != GRAPH_NAME:
        async with _ELICITATION_LOCK:
            # Double-check after acquiring lock
            _confirmed_for_session = _CONFIRMED_GRAPHS.get(_sid, set())
            if graph_name not in _confirmed_for_session:
                try:
                    await ctx.info(f"[elicitation] Requesting graph confirmation for '{graph_name}'...")
                    confirmed = await _confirm_graph_name(graph_name, ctx)
                    if confirmed is None:
                        return [{"error": "Query cancelled by user."}]
                    _CONFIRMED_GRAPHS.setdefault(_sid, set()).add(confirmed)
                    if confirmed != graph_name:
                        await ctx.info(f"[elicitation] Graph name changed from '{graph_name}' to '{confirmed}'")
                        graph_name = confirmed
                    else:
                        await ctx.info(f"[elicitation] Graph '{graph_name}' confirmed.")
                except Exception as e:
                    await ctx.info(f"[elicitation] Not available: {type(e).__name__}: {e}")
                    _CONFIRMED_GRAPHS.setdefault(_sid, set()).add(graph_name)
    if ctx: await ctx.info(f"[query_using_sql_cypher] SQL: {sql_query[:200]}{'...' if len(sql_query) > 200 else ''}")

    with cypher_span(sql_query) as span:
        query_start = time.perf_counter()
        rows = await pg_helper.query_using_sql_cypher(sql_query, graph_name)
        query_ms = (time.perf_counter() - query_start) * 1000

        # Serialize results for telemetry (cap at 8KB)
        import json as _json
        try:
            _result_json = _json.dumps(rows, default=str, ensure_ascii=False)
        except Exception:
            _result_json = str(rows)

        record_cypher_query(sql_query, len(rows), query_ms, result_data=_result_json)
        span.set_attribute("cypher.result_count", len(rows))
        span.set_attribute("cypher.graph_name", graph_name or "default")
        span.set_attribute("cypher.result_data", _result_json[:8192])

    print("Query executed, result:\n", rows)
    if ctx: await ctx.info(f"[query_using_sql_cypher] Query returned {len(rows)} rows")
    return rows



@mcp.tool
async def build_query_context(
    search_term: Annotated[str, "The entity name to search for (e.g., 'Larry Klein'). Drop titles like Mayor, Dr., etc."],
    target_concept: Annotated[str, "What the user is asking about — one word (e.g., 'meetings', 'votes', 'agenda items')"],
    graph_name: Annotated[str, "Graph name (e.g., 'meetings_graph_v2')"],
    year: Annotated[str, "Year filter if mentioned in the question (e.g., '2022'). Empty string if no year."] = "",
    ctx: Context = None,
) -> dict:
    """
    One-shot pipeline: discovers schema, finds entity, discovers edges, and builds a ready-to-use SQL query.
    Call this ONCE with the extracted parameters, then emit the suggested_query as your FINAL_SQL.

    Returns:
        - anchor_label, anchor_ids: the entity found
        - matching_edges: edges connecting the entity to the target concept
        - suggested_query: a complete, ready-to-use SQL+Cypher query (emit this as FINAL_SQL)
        - error: if something went wrong
    """
    import json as _json
    print(f"[build_query_context] search_term={search_term}, target_concept={target_concept}, graph_name={graph_name}, year={year}")
    if ctx: await ctx.info(f"[build_query_context] Building context for '{search_term}' → '{target_concept}' in graph '{graph_name}'{f' (year: {year})' if year else ''}")

    # --- Elicitation: confirm graph name with the user ---
    if ctx and graph_name != _PRECONFIRMED_GRAPH:
        try:
            confirmed = await _confirm_graph_name(graph_name, ctx)
            if confirmed is None:
                return {"error": "Query cancelled by user.", "suggested_query": None}
            if confirmed != graph_name:
                await ctx.info(f"Graph name changed from '{graph_name}' to '{confirmed}'")
                graph_name = confirmed
        except Exception as e:
            logger.info(f"Elicitation not available ({e}), proceeding with '{graph_name}'")

    # --- Step 1: Discover node labels ---
    discover_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (n) WHERE n.payload IS NOT NULL
  RETURN labels(n) AS label, head(collect(n.payload)) AS sample_payload
$$) AS (label ag_catalog.agtype, sample_payload ag_catalog.agtype);"""

    try:
        disc_rows = await pg_helper.query_using_sql_cypher(discover_sql, graph_name)
    except Exception as e:
        return {"error": f"Schema discovery failed: {e}"}

    # Parse labels and find date field
    all_labels = []
    date_field = "date"  # default
    for row in disc_rows:
        lbl = _strip_agtype(row.get("label", ""))
        all_labels.append(lbl)
        sample = row.get("sample_payload", "{}")
        try:
            payload = _json.loads(sample) if isinstance(sample, str) else sample
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            attrs = payload.get("attributes", {})
            if isinstance(attrs, dict) and "date" in attrs:
                date_field = "date"

    print(f"[build_query_context] Found labels: {all_labels}")
    if ctx: await ctx.info(f"[build_query_context] Schema discovery: found {len(all_labels)} labels: {', '.join(all_labels)}")

    # --- Step 2: Find entity — search all labels first, then narrow ---
    anchor_label = None
    anchor_ids = []

    # Determine if the question is about a person/employee
    _person_concepts = {"skill", "bench", "available", "certif", "team", "report", "manage",
                        "speaks", "language", "located", "work", "project", "client", "cost",
                        "score", "cv", "resume", "hire", "experience", "education", "university"}
    _is_person_query = any(kw in target_concept.lower() for kw in _person_concepts)
    _person_labels = {"Employee"}

    # First try: search all labels at once
    fts_term = _strip_titles_for_search(search_term)
    if fts_term != search_term:
        print(f"[build_query_context] Stripped titles for FTS: '{search_term}' → '{fts_term}'")
        if ctx: await ctx.info(f"[build_query_context] Stripped titles for FTS: '{search_term}' → '{fts_term}'")
    search_sql_all = f"""
        SELECT props->'payload'->>'id' AS entity_id, node_label
        FROM public.search_graph_nodes('{fts_term.replace("'", "''")}')
        ORDER BY rank DESC;
    """
    rows_all = await pg_helper.query_using_sql_cypher(search_sql_all, None)

    if rows_all:
        from collections import Counter
        label_counts = Counter(r.get("node_label", "") for r in rows_all)

        # For person-related queries, prefer person labels even if they have fewer matches
        if _is_person_query:
            person_matches = {lbl: cnt for lbl, cnt in label_counts.items() if lbl in _person_labels}
            if person_matches:
                anchor_label = max(person_matches, key=person_matches.get)
                print(f"[build_query_context] Person query detected, preferring '{anchor_label}' ({person_matches[anchor_label]} matches) over raw top '{label_counts.most_common(1)[0][0]}' ({label_counts.most_common(1)[0][1]} matches)")
            else:
                anchor_label = label_counts.most_common(1)[0][0]
        else:
            anchor_label = label_counts.most_common(1)[0][0]

        anchor_ids = list(dict.fromkeys(
            r["entity_id"] for r in rows_all
            if r.get("node_label") == anchor_label and r.get("entity_id")
        ))[:10]

    # --- Name verification for build_query_context ---
    if anchor_ids and anchor_label and len(anchor_ids) > 1:
        _bqc_search_words = _extract_search_words(search_term)
        if _bqc_search_words:
            # FTS results include entity_id but not name — need to query graph
            _bqc_safe = ", ".join(f"'{eid.replace(chr(39), chr(39)+chr(39))}'" for eid in anchor_ids)
            _bqc_verify_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (n:{anchor_label})
  WHERE n.payload.id IN [{_bqc_safe}]
  RETURN n.payload.id AS id, n.payload.name AS name
$$) AS (id ag_catalog.agtype, name ag_catalog.agtype);"""
            try:
                _bqc_rows = await pg_helper.query_using_sql_cypher(_bqc_verify_sql, graph_name)
                _bqc_verified = [
                    _strip_agtype(r.get("id"))
                    for r in _bqc_rows
                    if _name_matches_search(_strip_agtype(r.get("name", "")), _bqc_search_words)
                ]
                if _bqc_verified:
                    print(f"[build_query_context] Name verification: {len(anchor_ids)} FTS → {len(_bqc_verified)} verified")
                    if ctx: await ctx.info(f"[build_query_context] Name verification: {len(anchor_ids)} FTS → {len(_bqc_verified)} name-verified")
                    anchor_ids = _bqc_verified
                else:
                    print(f"[build_query_context] Name verification: no strict match, keeping top FTS result")
                    anchor_ids = anchor_ids[:1]
            except Exception as e:
                print(f"[build_query_context] Name verification failed (non-fatal): {e}")

    # If search with full term failed, retry with progressively shorter terms
    if not anchor_ids:
        words = fts_term.split()
        for trim in range(1, min(4, len(words))):
            shorter = " ".join(words[:len(words) - trim])
            if len(shorter) < 3:
                break
            retry_sql = f"""
                SELECT props->'payload'->>'id' AS entity_id, node_label
                FROM public.search_graph_nodes('{shorter.replace("'", "''")}')
                ORDER BY rank DESC;
            """
            retry_rows = await pg_helper.query_using_sql_cypher(retry_sql, None)
            if retry_rows:
                from collections import Counter
                label_counts = Counter(r.get("node_label", "") for r in retry_rows)
                if _is_person_query:
                    person_matches = {lbl: cnt for lbl, cnt in label_counts.items() if lbl in _person_labels}
                    anchor_label = max(person_matches, key=person_matches.get) if person_matches else label_counts.most_common(1)[0][0]
                else:
                    anchor_label = label_counts.most_common(1)[0][0]
                anchor_ids = list(dict.fromkeys(
                    r["entity_id"] for r in retry_rows
                    if r.get("node_label") == anchor_label and r.get("entity_id")
                ))[:10]
                break

    if not anchor_ids:
        return {
            "error": f"Entity '{search_term}' not found in any label.",
            "all_labels": all_labels,
            "suggested_query": None,
        }

    print(f"[build_query_context] anchor_label={anchor_label}, anchor_ids={anchor_ids}")
    if ctx: await ctx.info(f"[build_query_context] Entity found: {anchor_label} with {len(anchor_ids)} IDs")
    if ctx: await ctx.info(f"[build_query_context] Discovering edges for {anchor_label}...")

    # --- Step 3: Discover edges ---
    safe_ids = ", ".join(f"'{eid}'" for eid in anchor_ids[:5])

    out_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (a:{anchor_label})-[r]->(b)
  WHERE a.payload.id IN [{safe_ids}]
  RETURN type(r) AS rel, labels(b) AS tgt, count(*) AS cnt
$$) AS (rel ag_catalog.agtype, tgt ag_catalog.agtype, cnt ag_catalog.agtype);"""

    in_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (a)-[r]->(b:{anchor_label})
  WHERE b.payload.id IN [{safe_ids}]
  RETURN labels(a) AS src, type(r) AS rel, count(*) AS cnt
$$) AS (src ag_catalog.agtype, rel ag_catalog.agtype, cnt ag_catalog.agtype);"""

    outbound = []
    inbound = []
    try:
        out_rows = await pg_helper.query_using_sql_cypher(out_sql, graph_name)
        outbound = [{"rel": _strip_agtype(r["rel"]), "target_label": _strip_agtype(r["tgt"]), "count": r["cnt"]} for r in out_rows]
    except Exception as e:
        print(f"[build_query_context] Outbound edge discovery failed: {e}")
    try:
        in_rows = await pg_helper.query_using_sql_cypher(in_sql, graph_name)
        inbound = [{"source_label": _strip_agtype(r["src"]), "rel": _strip_agtype(r["rel"]), "count": r["cnt"]} for r in in_rows]
    except Exception as e:
        print(f"[build_query_context] Inbound edge discovery failed: {e}")

    # --- Step 4: Build schema summary for the LLM ---
    # Instead of building a query server-side, give the LLM all the context it needs
    # to generate its own Cypher query.

    # Compact schema: just label names (LLM already knows property paths from instructions)
    schema_summary = {
        "node_labels": all_labels,
        "date_property_path": f"payload.attributes.{date_field}",
    }

    # Compact edge summary
    edge_summary = {
        "outbound": [f"(:{anchor_label})-[:{e['rel']}]->(:{e['target_label']})" for e in outbound],
        "inbound": [f"(:{e['source_label']})-[:{e['rel']}]->(:{anchor_label})" for e in inbound],
    }

    safe_id_list = ", ".join(f"'{eid}'" for eid in anchor_ids)

    result = {
        "anchor_label": anchor_label,
        "anchor_ids": anchor_ids,
        "anchor_id_cypher_filter": f"a.payload.id IN [{safe_id_list}]",
        "schema": schema_summary,
        "edges": edge_summary,
        "outbound_edges_raw": outbound,
        "inbound_edges_raw": inbound,
        "graph_name": graph_name,
        "year": year,
    }
    print(f"[build_query_context] Done. anchor={anchor_label}, ids={len(anchor_ids)}, outbound={len(outbound)}, inbound={len(inbound)}")
    if ctx: await ctx.info(f"[build_query_context] Done. {len(outbound)} outbound edges, {len(inbound)} inbound edges found")
    return result


async def _confirm_graph_name(
    graph_name: str,
    ctx: Context,
) -> str | None:
    """
    Use MCP elicitation to confirm the graph name with the user.
    Lists available graphs from ag_catalog.ag_graph and asks the user
    to pick one or confirm the provided name.
    Returns the confirmed graph name, or None if the user declined/cancelled.
    """
    # Fetch available graphs from the database
    available_graphs: list[str] = []
    try:
        rows = await pg_helper.query_using_sql_cypher(
            "SELECT name FROM ag_catalog.ag_graph WHERE name != 'ag_graph' ORDER BY name;",
            None,
        )
        available_graphs = [r["name"] for r in rows if r.get("name")]
    except Exception as e:
        logger.warning(f"Could not list graphs: {e}")

    if not available_graphs:
        # No graphs found — just confirm the provided name
        result = await ctx.elicit(
            f"No graphs discovered in the database. Proceed with graph name '{graph_name}'?",
        )
        if isinstance(result, AcceptedElicitation):
            return graph_name
        return None

    # Always ask user to confirm — show available graphs with the provided name highlighted
    result = await ctx.elicit(
        f"Please confirm the graph to use (provided: '{graph_name}')."
        f" Available graphs: {', '.join(available_graphs)}",
        response_type=available_graphs,  # list[str] → enum dropdown
    )

    if isinstance(result, AcceptedElicitation):
        confirmed = result.data
        # response_type=list[str] returns the selected string
        if isinstance(confirmed, str):
            return confirmed
        # If dict with "value" key (FastMCP wrapping)
        if isinstance(confirmed, dict) and "value" in confirmed:
            return confirmed["value"]
        return graph_name
    elif isinstance(result, DeclinedElicitation):
        await ctx.info("User declined graph selection.")
        return None
    else:  # CancelledElicitation
        await ctx.info("User cancelled graph selection.")
        return None


@mcp.tool
async def analyze_graph_statistics(
    graph_name: Annotated[str, "Graph name to analyze (e.g., 'meetings_graph_v2')"],
    ctx: Context = None,
) -> dict:
    """
    Analyze graph statistics: count nodes per label, edges per type, and total connectivity.
    Streams progress updates as each metric is computed.
    Uses MCP elicitation to confirm the graph name with the user before running.
    Args:
        graph_name: The graph to analyze.
    Returns:
        A dict with node_counts, edge_counts, total_nodes, total_edges.
    """
    # --- Elicitation: confirm graph name with the user ---
    if ctx and graph_name != _PRECONFIRMED_GRAPH:
        try:
            confirmed = await _confirm_graph_name(graph_name, ctx)
            if confirmed is None:
                return {"status": "cancelled", "message": "Graph analysis cancelled by user."}
            if confirmed != graph_name:
                await ctx.info(f"Graph name changed from '{graph_name}' to '{confirmed}'")
                graph_name = confirmed
        except Exception as e:
            # Elicitation not supported by client — proceed with provided name
            logger.info(f"Elicitation not available ({e}), proceeding with '{graph_name}'")

    if ctx: await ctx.info(f"Starting analysis of graph '{graph_name}'...")
    stats = {"graph_name": graph_name, "node_counts": {}, "edge_counts": {}, "total_nodes": 0, "total_edges": 0}

    # Step 1 — count nodes per label
    if ctx: await ctx.info("Step 1/3: Counting nodes per label...")
    node_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH (n) RETURN labels(n) AS label, count(*) AS cnt
$$) AS (label ag_catalog.agtype, cnt ag_catalog.agtype);"""
    try:
        node_rows = await pg_helper.query_using_sql_cypher(node_sql, graph_name)
        for r in node_rows:
            lbl = _strip_agtype(r["label"])
            cnt = int(str(r["cnt"]).strip('"'))
            stats["node_counts"][lbl] = cnt
            stats["total_nodes"] += cnt
            if ctx: await ctx.info(f"  → {lbl}: {cnt:,} nodes")
    except Exception as e:
        if ctx: await ctx.warning(f"Node count failed: {e}")
        print(f"[analyze_graph_statistics] Node count error: {e}")

    # Step 2 — count edges per relationship type
    if ctx: await ctx.info("Step 2/3: Counting edges per relationship type...")
    edge_sql = f"""SELECT * FROM ag_catalog.cypher('{graph_name}', $$
  MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt
$$) AS (rel ag_catalog.agtype, cnt ag_catalog.agtype);"""
    try:
        edge_rows = await pg_helper.query_using_sql_cypher(edge_sql, graph_name)
        for r in edge_rows:
            rel = _strip_agtype(r["rel"])
            cnt = int(str(r["cnt"]).strip('"'))
            stats["edge_counts"][rel] = cnt
            stats["total_edges"] += cnt
            if ctx: await ctx.info(f"  → {rel}: {cnt:,} edges")
    except Exception as e:
        if ctx: await ctx.warning(f"Edge count failed: {e}")
        print(f"[analyze_graph_statistics] Edge count error: {e}")

    # Step 3 — summary
    if ctx: await ctx.info(
        f"Step 3/3: Summary — {stats['total_nodes']:,} nodes, {stats['total_edges']:,} edges, "
        f"{len(stats['node_counts'])} labels, {len(stats['edge_counts'])} relationship types"
    )
    if ctx: await ctx.info("Analysis complete ✓")
    print(f"[analyze_graph_statistics] Done: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    return stats


if __name__ == "__main__":
    import selectors
    global pg_helper
    # Python 3.13+ on Windows: asyncio.run() ignores event loop policy,
    # must pass loop_factory explicitly for psycopg async to work.
    _loop_factory = None
    if sys.platform.startswith("win"):
        _loop_factory = asyncio.SelectorEventLoop
    _pg_init_start = time.perf_counter()
    pg_helper = asyncio.run(PGAgeHelper.create(), loop_factory=_loop_factory)
    _pg_init_ms = (time.perf_counter() - _pg_init_start) * 1000
    record_server_init(_pg_init_ms)
    record_pg_connect()
    logger.info("Graph MCP server PG init: %.0fms", _pg_init_ms)

    #test_query = """SELECT *
    #    FROM ag_catalog.cypher('customer_graph', $$
#
    #    MATCH (c:Customer)
    #    WHERE c.payload.name = 'Customer 002'
    #    OPTIONAL MATCH (c)-[:ADOPTED_PRODUCT]->(p:Product)
    #    RETURN c.payload.name AS customer_name, collect(DISTINCT p.payload.name) AS product_names
#
    #    $$) AS (
    #    customer_name ag_catalog.agtype,
    #    product_names ag_catalog.agtype
    #    );"""
    #
    #result = asyncio.run(query_using_sql_cypher(test_query))
    #print("Test query result:\n", result)

    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=3002,
        middleware=[
            Middleware(CORSMiddleware,
                       allow_origins=["*"],
                       allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                       allow_headers=["*"],
                       expose_headers=["Mcp-Session-Id"]),
        ],
    )