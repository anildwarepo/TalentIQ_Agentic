"""MCP tool for vector similarity search over employee embeddings."""

from __future__ import annotations

import logging
import time
from typing import Annotated

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from fastmcp import Context
from openai import AzureOpenAI
from psycopg.rows import dict_row

from talent_backend.config import (
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    AZURE_OPENAI_EMBEDDING_DIMENSIONS,
    AZURE_OPENAI_ENDPOINT,
)

from .app import _pg, mcp

logger = logging.getLogger("talent_mcp")

# ── Lazy singleton for Azure OpenAI embedding client ─────────
_openai_client: AzureOpenAI | None = None


def _get_openai_client() -> AzureOpenAI:
    global _openai_client
    if _openai_client is None:
        credential = DefaultAzureCredential()
        # Pre-warm: force one authentication so the credential caches its provider.
        # Without this, 10 parallel requests all probe IMDS (5s timeout each).
        credential.get_token("https://cognitiveservices.azure.com/.default")
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
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
    search_text: Annotated[str, "Natural language text describing ALL roles/skills to search for. Combine multiple roles into ONE search string separated by ' | ' (e.g., 'Python FastAPI developer | React TypeScript frontend | Azure cloud architect'). NEVER call this tool multiple times — always combine into a single call."],
    search_type: Annotated[str, "'resume' or 'skills' — which embedding column to search"] = "resume",
    limit: Annotated[int, "Maximum number of results to return (use 50 for multi-role searches)"] = 10,
    ctx: Context = None,
) -> list[dict]:
    """Semantic similarity search across employee resumes or skills using vector embeddings.
    
    IMPORTANT: For multi-role searches (e.g., RFP matching), combine ALL role descriptions into 
    a single search_text separated by ' | ' and set limit=50. Do NOT call this tool once per role.
    """
    column = _VALID_COLUMNS.get(search_type)
    if column is None:
        return [{"error": f"Invalid search_type '{search_type}'. Use 'resume' or 'skills'."}]

    if limit < 1 or limit > 100:
        limit = min(max(limit, 1), 100)

    search_preview = search_text[:60].replace('\n', ' ')
    logger.info("[vector_search] type=%s limit=%d text=%s", search_type, limit, search_text[:80])
    if ctx:
        await ctx.info(f"[QUERY] VECTOR ({search_type}): {search_preview}...")

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
            await cur.execute(sql, [embedding_str, embedding_str, limit])
            rows = await cur.fetchall()

    query_ms = (time.perf_counter() - query_start) * 1000
    logger.info("[vector_search] %d rows in %.0fms", len(rows), query_ms)
    if ctx:
        await ctx.info(
            f"[RESULT] VECTOR: {len(rows)} results (embed {embed_ms:.0f}ms + query {query_ms:.0f}ms)"
        )

    # ── Format results ───────────────────────────────────────
    results = []
    for row in rows:
        results.append({
            "workday_id": row["workday_id"],
            "name": row["name"],
            "job_title": row["job_title"],
            "resume_summary": row["resume_summary"],
            "skills_text": row["skills_text"],
            "certs_text": row["certs_text"],
            "similarity": round(float(row["similarity"]), 4),
        })

    return results
