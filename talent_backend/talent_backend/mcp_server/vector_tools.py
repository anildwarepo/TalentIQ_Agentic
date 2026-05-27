"""MCP tool for vector similarity search over employee embeddings."""

from __future__ import annotations

import logging
import time
from typing import Annotated

from azure.identity import get_bearer_token_provider
from fastmcp import Context
from openai import AzureOpenAI
from psycopg.rows import dict_row

from talent_backend.config import (
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    AZURE_OPENAI_EMBEDDING_DIMENSIONS,
    AZURE_OPENAI_ENDPOINT,
    get_azure_credential,
)

from .app import _pg, mcp

logger = logging.getLogger("talent_mcp")

# ── Lazy singleton for Azure OpenAI embedding client ─────────
_openai_client: AzureOpenAI | None = None


def _get_openai_client() -> AzureOpenAI:
    global _openai_client
    if _openai_client is None:
        t0 = time.time()
        credential = get_azure_credential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        # Force token acquisition NOW so the credential chain is warmed.
        # Without this, the first API call pays the full AzureCliCredential
        # cost (~20s on Windows).
        try:
            _token = token_provider()
            logger.info("[openai] credential warmed in %.0fms", (time.time() - t0) * 1000)
        except Exception as exc:
            logger.warning("[openai] credential pre-warm failed: %s", exc)
        _openai_client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version="2024-06-01",
        )
    return _openai_client


# ── Column whitelist to prevent injection ────────────────────
_VALID_COLUMNS = {
    "resume": "resume_embedding",
    "skills": "skills_embedding",
}


@mcp.tool
async def vector_search(
    search_text: Annotated[str, "Natural language description of desired qualifications or role profiles. Combine multiple roles into ONE search string separated by ' | '. NEVER call this tool multiple times — always combine into a single call."],
    search_type: Annotated[str, "'resume' or 'skills' — which embedding column to search"] = "resume",
    limit: Annotated[int, "Maximum number of results to return (use 25 for multi-role searches)"] = 10,
    countries: Annotated[list[str] | None, "Optional list of country names to filter results (e.g. ['Spain', 'Mexico', 'Colombia']). When provided, returns ONLY candidates in these countries. Use this for RFP matching with geographic constraints."] = None,
    ctx: Context = None,
) -> list[dict]:
    """Semantic similarity search over employee resumes or skills using vector embeddings.

    Use ONLY for natural language matching against employee resumes or skill profiles:
    - RFP role matching (e.g. 'experienced financial risk modeler with Python')
    - Finding people with a described capability (e.g. 'someone good with cloud migration')
    - Multi-role searches: combine into ONE call separated by ' | ', set limit=25
    - Geographic filtering: pass countries=['Spain', 'Mexico'] to restrict results

    Returns candidate details suitable for display: workday_id, name, email,
    job_title, seniority, years of experience, location, bench status, skills,
    certifications, resume summary, and similarity.

    Do NOT use for entity lookups (skills, certifications, countries, etc.)
    — use resolve_entities instead.
    Do NOT use when you already have resolved entity codes from resolve_entities
    — build Cypher with exact code matches instead.
    """
    column = _VALID_COLUMNS.get(search_type)
    if column is None:
        return [{"error": f"Invalid search_type '{search_type}'. Use 'resume' or 'skills'."}]

    if limit < 1 or limit > 100:
        limit = min(max(limit, 1), 100)

    search_preview = search_text[:60].replace('\n', ' ')
    country_filter = [c.strip() for c in countries if c.strip()] if countries else []
    # When filtering by country, over-fetch to ensure enough in-scope results
    fetch_limit = limit * 5 if country_filter else limit
    fetch_limit = min(fetch_limit, 500)

    logger.info(
        "[vector_search] type=%s limit=%d countries=%s text=%s",
        search_type, limit, country_filter or "all", search_text[:80],
    )
    if ctx:
        geo_note = f" countries={country_filter}" if country_filter else ""
        await ctx.info(f"[QUERY] VECTOR ({search_type}{geo_note}): {search_preview}...")

    # ── Generate embedding ───────────────────────────────────
    embed_start = time.perf_counter()
    client = _get_openai_client()

    # Run sync OpenAI call in executor to avoid blocking the event loop
    import asyncio
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.embeddings.create(
            input=search_text,
            model=AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        ),
    )
    embedding = response.data[0].embedding
    embed_ms = (time.perf_counter() - embed_start) * 1000
    logger.info("[vector_search] embedding generated in %.0fms", embed_ms)

    # ── Build parameterised vector query ─────────────────────
    # Column name is from a fixed whitelist, safe to interpolate.
    sql = f"""
        SELECT ee.workday_id,
               ef.name,
               ef.job_title,
               ef.resume_summary,
               ef.skills_text,
               ef.certs_text,
               1 - (ee.{column} <=> %s::vector) AS similarity
          FROM employee_embeddings ee
          JOIN employee_fts ef ON ee.workday_id = ef.workday_id
         WHERE ee.{column} IS NOT NULL
         ORDER BY ee.{column} <=> %s::vector
         LIMIT %s
    """

    # ── Execute via raw pool connection (parameterised) ──────
    query_start = time.perf_counter()
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

    pg = _pg()
    await pg._ensure_open()
    async with pg._pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, [embedding_str, embedding_str, fetch_limit])
            rows = await cur.fetchall()

    query_ms = (time.perf_counter() - query_start) * 1000
    logger.info("[vector_search] %d rows in %.0fms", len(rows), query_ms)
    if ctx:
        await ctx.info(
            f"[RESULT] VECTOR: {len(rows)} results (embed {embed_ms:.0f}ms + query {query_ms:.0f}ms)"
        )

    # ── Enrich with graph data (location, country, seniority) ─
    enrich_start = time.perf_counter()
    workday_ids = [row["workday_id"] for row in rows]
    enrichment = await _enrich_from_graph(pg, workday_ids)
    enrich_ms = (time.perf_counter() - enrich_start) * 1000
    if enrichment:
        logger.info("[vector_search] enriched %d profiles in %.0fms", len(enrichment), enrich_ms)

    # ── Format results (compact — truncate resume to reduce LLM tokens) ──
    # Normalize country filter for case-insensitive matching
    country_set = {c.lower() for c in country_filter} if country_filter else None

    results = []
    for row in rows:
        wid = row["workday_id"]
        extra = enrichment.get(wid, {}) if enrichment else {}

        # Apply country filter if specified
        if country_set:
            emp_country = (extra.get("country") or "").lower()
            if emp_country not in country_set:
                continue

        # Truncate resume_summary to 200 chars — the LLM doesn't need the full text
        # for role matching; skills_text and certs_text are more useful
        resume = row.get("resume_summary") or ""
        if len(resume) > 200:
            resume = resume[:200] + "…"
        results.append({
            "workday_id": wid,
            "name": row["name"],
            "email": extra.get("email"),
            "job_title": row["job_title"],
            "skill_level": extra.get("skill_level"),
            "years_of_experience": extra.get("years_of_experience"),
            "city": extra.get("city"),
            "country": extra.get("country"),
            "is_bench": extra.get("is_bench"),
            "resume_summary": resume,
            "skills_text": row["skills_text"],
            "certs_text": row["certs_text"],
            "similarity": round(float(row["similarity"]), 4),
        })
        if len(results) >= limit:
            break

    if country_set and ctx:
        await ctx.info(
            f"[RESULT] VECTOR: {len(results)} in-scope results "
            f"(filtered from {len(rows)} by country: {country_filter})"
        )

    return results


async def _enrich_from_graph(pg, workday_ids: list[str]) -> dict[str, dict] | None:
    """Batch-fetch location, country, seniority from the graph for given workday_ids.

    Returns a dict keyed by workday_id with enrichment fields, or None on failure.
    Uses a plain SQL query against AGE's internal tables for speed (avoids Cypher overhead).
    """
    if not workday_ids:
        return {}
    try:
        from talent_backend.config import GRAPH_NAME
        # Use a SQL query against the AGE vertex/edge tables.
        # This is faster than Cypher for batch lookups.
        # Fall back to a simpler approach: use the graph's Employee properties
        # which include skill_level, years_of_experience, is_bench, and traverse
        # LOCATED_IN → Location → IN_COUNTRY → Country for location.
        placeholders = ",".join(["%s"] * len(workday_ids))
        sql = f"""
            SELECT * FROM ag_catalog.cypher('{GRAPH_NAME}', $$
              MATCH (e:Employee)
              WHERE e.workday_id IN [{','.join("'" + wid.replace("'", "") + "'" for wid in workday_ids)}]
              OPTIONAL MATCH (e)-[:LOCATED_IN]->(l:Location)-[:IN_COUNTRY]->(c:Country)
              WITH e.workday_id AS wid,
                                     e.email AS email,
                   e.skill_level AS skill_level,
                   e.years_of_experience AS yoe,
                   e.is_bench AS is_bench,
                   l.city AS city,
                   c.name AS country
                            RETURN wid, email, skill_level, yoe, is_bench, city, country
                        $$) AS (wid ag_catalog.agtype, email ag_catalog.agtype, skill_level ag_catalog.agtype,
                    yoe ag_catalog.agtype, is_bench ag_catalog.agtype,
                    city ag_catalog.agtype, country ag_catalog.agtype)
        """
        await pg._ensure_open()
        async with pg._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SET search_path = ag_catalog, \"$user\", public;")
                await cur.execute(sql)
                rows = await cur.fetchall()

        result = {}
        for row in rows:
            # AGE returns agtype values — strip quotes for strings
            wid = str(row["wid"]).strip('"')
            result[wid] = {
                "email": _agtype_str(row.get("email")),
                "skill_level": _agtype_str(row.get("skill_level")),
                "years_of_experience": _agtype_int(row.get("yoe")),
                "is_bench": _agtype_bool(row.get("is_bench")),
                "city": _agtype_str(row.get("city")),
                "country": _agtype_str(row.get("country")),
            }
        return result
    except Exception as exc:
        logger.warning("[vector_search] graph enrichment failed: %s", exc)
        return None


def _agtype_str(val) -> str | None:
    """Extract a string from an AGE agtype value."""
    if val is None:
        return None
    s = str(val).strip('"')
    return s if s and s != "null" else None


def _agtype_int(val) -> int | None:
    """Extract an int from an AGE agtype value."""
    if val is None:
        return None
    s = str(val).strip('"')
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _agtype_bool(val) -> bool | None:
    """Extract a bool from an AGE agtype value."""
    if val is None:
        return None
    s = str(val).strip('"').lower()
    if s in ("true", "1"):
        return True
    if s in ("false", "0"):
        return False
    return None
