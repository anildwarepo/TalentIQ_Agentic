"""MCP tool for resolving user terms to canonical entity names/codes.

Uses the ``entity_search`` PostgreSQL table with a hybrid resolution
strategy: exact match first, then Reciprocal Rank Fusion (RRF) of
FTS + vector similarity search results.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastmcp import Context
from psycopg.rows import dict_row

from .app import _pg, mcp

logger = logging.getLogger("talent_mcp")

# RRF constant — standard value from the original RRF paper (Cormack et al.)
_RRF_K = 60

# Number of candidates to retrieve from each search method before merging
_RRF_CANDIDATES = 5

# Minimum confidence thresholds — below these, return "not found"
_MIN_FTS_AND_WORD_OVERLAP = 0.5   # FTS AND mode: at least half the query words must appear in the match
_MIN_VECTOR_SIMILARITY = 0.80     # Vector cosine similarity: must be reasonably close
_MIN_RRF_CONFIDENCE = 0.5         # Combined confidence: reject garbage matches

# Cached table existence check — verified once per process lifetime
_entity_table_verified: bool | None = None

# ── Valid entity types (whitelist) ───────────────────────────
_VALID_ENTITY_TYPES = frozenset({
    "Certification",
    "Skill",
    "Country",
    "SkillDomain",
    "ServiceLine",
    "Offering",
    "University",
    "Client",
    "Language",
    "Project",
})


def _not_found(term: str, entity_type: str) -> dict:
    """Return a not-found result dict."""
    return {
        "term": term,
        "entity_type": entity_type,
        "found": False,
        "name": None,
        "code": None,
        "match_type": "none",
        "confidence": 0.0,
    }


@mcp.tool
async def resolve_entities(
    queries: list[dict],
    ctx: Context = None,
) -> list[dict]:
    """Resolve user terms to canonical entity names, codes, and types.

    >>> CALL THIS FIRST before building any Cypher query that references
    >>> entities (skills, certifications, countries, service lines, etc.).

    Searches across ALL entity types to find the best match — the caller
    does NOT need to know whether "PMP" is a Certification or a Skill.

    Each query dict should have:
      - term: str — the user's input (e.g., "PMP", "k8s", "Google Cloud data")
      - entity_type: str (optional) — hint to narrow search scope.
        If omitted, searches ALL entity types and returns the best match.

    Returns a list of dicts, one per query, each containing:
      - term: str — the original search term
      - entity_type: str — the resolved entity type (discovered, not assumed)
      - found: bool — whether a match was found
      - name: str|null — canonical entity name
      - code: str|null — entity code (USE THIS in Cypher WHERE clauses)
      - match_type: str — how it matched
      - confidence: float — 0.0-1.0 confidence score

    After calling this tool:
      1. Use the returned 'code' in Cypher: WHERE v.code = 'RESOLVED_CODE'
      2. Do NOT fall back to regex on entity names
      3. Do NOT call search_graph or vector_search for entity lookup
      4. If resolution fails (found=false), tell the user the term wasn't recognized
    """
    if not queries:
        return []

    start = time.perf_counter()
    results: list[dict] = []

    pg = _pg()
    await pg._ensure_open()

    try:
        async with pg._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Check table existence once per process lifetime
                global _entity_table_verified
                if _entity_table_verified is None:
                    await cur.execute(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM information_schema.tables"
                        "  WHERE table_schema = 'public'"
                        "    AND table_name = 'entity_search'"
                        ")"
                    )
                    row = await cur.fetchone()
                    _entity_table_verified = bool(row and row.get("exists", False))
                    if not _entity_table_verified:
                        logger.warning("[resolve] entity_search table does not exist")

                if not _entity_table_verified:
                    if ctx:
                        await ctx.info("[resolve] entity_search table not found — returning all not-found")
                    return [_not_found(q.get("term", ""), q.get("entity_type", "")) for q in queries]

                # ── Pass 1: exact + FTS for all queries (no HTTP) ─────
                pass1_start = time.perf_counter()
                need_vector: list[tuple[int, str, str | None, list[dict]]] = []
                for i, q in enumerate(queries):
                    term = str(q.get("term", "")).strip()
                    entity_type = str(q.get("entity_type", "")).strip() or None

                    if not term:
                        results.append(_not_found(term, entity_type or ""))
                        continue

                    # Validate entity_type if provided; ignore invalid hints
                    if entity_type and entity_type not in _VALID_ENTITY_TYPES:
                        entity_type = None

                    result, fts_results = await _resolve_pass1(cur, term, entity_type)
                    if result is not None:
                        results.append(result)
                    else:
                        results.append(None)  # placeholder for pass 2
                        need_vector.append(
                            (len(results) - 1, term, entity_type, fts_results)
                        )

                pass1_ms = (time.perf_counter() - pass1_start) * 1000
                resolved_p1 = sum(1 for r in results if r is not None)
                logger.info(
                    "[resolve] pass1 done — %d/%d resolved (exact+FTS), %d need vector (%.0fms)",
                    resolved_p1, len(queries), len(need_vector), pass1_ms,
                )
                if ctx:
                    await ctx.info(
                        f"[resolve] pass1: {resolved_p1}/{len(queries)} resolved, "
                        f"{len(need_vector)} need vector ({pass1_ms:.0f}ms)"
                    )

                # ── Pass 2: ONE batched embedding call + vector DB ────
                if need_vector:
                    terms_to_embed = [nv[1] for nv in need_vector]
                    embed_start = time.perf_counter()
                    embeddings = await _batch_embed(terms_to_embed, ctx)
                    embed_ms = (time.perf_counter() - embed_start) * 1000
                    logger.info(
                        "[resolve] embedding %d terms in %.0fms",
                        len(terms_to_embed), embed_ms,
                    )

                    vec_start = time.perf_counter()
                    for j, (idx, term, etype, fts_hits) in enumerate(need_vector):
                        emb = (
                            embeddings[j]
                            if embeddings and j < len(embeddings)
                            else None
                        )
                        results[idx] = await _resolve_pass2(
                            cur, term, etype, fts_hits, emb,
                        )
                    vec_ms = (time.perf_counter() - vec_start) * 1000
                    logger.info(
                        "[resolve] pass2 vector lookups done — %.0fms", vec_ms,
                    )
                    if ctx:
                        await ctx.info(
                            f"[resolve] pass2: embed {embed_ms:.0f}ms + "
                            f"vector DB {vec_ms:.0f}ms"
                        )

                # ── Log every result (same messages as before) ────────
                for result in results:
                    if result is None:
                        continue
                    logger.info(
                        "[resolve] %s → %s (%s, %s)",
                        result["term"], result["name"],
                        result["entity_type"], result["match_type"],
                    )
                    if ctx:
                        status = result["name"] or "not found"
                        await ctx.info(
                            f"[resolve] {result['term']} → {status}"
                            f" ({result['entity_type']}, {result['match_type']})"
                        )

    except Exception as exc:
        logger.error("[resolve] database error: %s", exc)
        if ctx:
            await ctx.info(f"[resolve] error: {exc}")
        # Return not-found for any unprocessed queries
        while len(results) < len(queries):
            q = queries[len(results)]
            results.append(_not_found(q.get("term", ""), q.get("entity_type", "")))
        # Fill in any None placeholders from interrupted pass 2
        for i, r in enumerate(results):
            if r is None:
                q = queries[i]
                results[i] = _not_found(
                    str(q.get("term", "")).strip(),
                    str(q.get("entity_type", "")).strip() or "",
                )
        return results

    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("[resolve] %d queries resolved in %.0fms", len(queries), elapsed_ms)
    if ctx:
        found_count = sum(1 for r in results if r and r["found"])
        await ctx.info(f"[RESULT] Resolved {found_count}/{len(queries)} entities ({elapsed_ms:.0f}ms)")

    return results


async def _resolve_pass1(
    cur, term: str, entity_type: str | None,
) -> tuple[dict | None, list[dict]]:
    """Pass 1: exact code + exact name + FTS (no HTTP calls).

    Returns ``(result, fts_results)``.
    If *result* is not None the term is fully resolved; the caller should
    skip pass 2.  *fts_results* are carried forward for the RRF merge in
    pass 2.
    """
    type_filter = entity_type  # None = search all types

    # 1. Exact code match (highest confidence)
    if type_filter:
        await cur.execute(
            "SELECT entity_type, name, code FROM entity_search "
            "WHERE entity_type = %s AND UPPER(code) = UPPER(%s) LIMIT 1",
            [type_filter, term],
        )
    else:
        await cur.execute(
            "SELECT entity_type, name, code FROM entity_search "
            "WHERE UPPER(code) = UPPER(%s) LIMIT 1",
            [term],
        )
    row = await cur.fetchone()
    if row:
        return _found(term, row, "code_exact", 1.0), []

    # 2. Exact name match (case-insensitive)
    if type_filter:
        await cur.execute(
            "SELECT entity_type, name, code FROM entity_search "
            "WHERE entity_type = %s AND LOWER(name) = LOWER(%s) LIMIT 1",
            [type_filter, term],
        )
    else:
        await cur.execute(
            "SELECT entity_type, name, code FROM entity_search "
            "WHERE LOWER(name) = LOWER(%s) LIMIT 1",
            [term],
        )
    row = await cur.fetchone()
    if row:
        return _found(term, row, "name_exact", 1.0), []

    # 3. FTS search (fast — no API call needed)
    fts_results = await _fts_search(cur, term, type_filter)

    # Strong AND-mode match with good word overlap → resolve now
    if fts_results and fts_results[0].get("fts_mode") == "and":
        top = fts_results[0]
        word_overlap = _word_overlap_ratio(term, top.get("search_text", ""))
        if word_overlap >= _MIN_FTS_AND_WORD_OVERLAP:
            result = {
                "term": term,
                "entity_type": top["entity_type"],
                "found": True,
                "name": top["name"],
                "code": top["code"],
                "match_type": "fts",
                "confidence": round(word_overlap, 3),
            }
            return result, fts_results

    # Not resolved yet — pass FTS results forward for RRF merge
    return None, fts_results


async def _resolve_pass2(
    cur,
    term: str,
    entity_type: str | None,
    fts_results: list[dict],
    embedding: list[float] | None,
) -> dict:
    """Pass 2: vector search (pre-computed embedding) + RRF + alias.

    Called only for terms not resolved by pass 1.
    """
    type_filter = entity_type

    # 4. RRF merge: FTS + vector (embedding already computed in batch)
    vec_results = (
        await _vector_search_with_embedding(cur, embedding, type_filter)
        if embedding is not None
        else []
    )
    merged = _rrf_merge(fts_results, vec_results)
    if merged:
        top = merged[0]
        confidence = _compute_confidence(term, top)
        if confidence >= _MIN_RRF_CONFIDENCE:
            return {
                "term": term,
                "entity_type": top["entity_type"],
                "found": True,
                "name": top["name"],
                "code": top["code"],
                "match_type": f"rrf(fts={top.get('fts_rank', '-')},vec={top.get('vec_rank', '-')})",
                "confidence": round(confidence, 3),
            }

    # 5. Alias substring fallback
    if type_filter:
        await cur.execute(
            "SELECT entity_type, name, code FROM entity_search "
            "WHERE entity_type = %s AND aliases ILIKE '%%' || %s || '%%' LIMIT 1",
            [type_filter, term],
        )
    else:
        await cur.execute(
            "SELECT entity_type, name, code FROM entity_search "
            "WHERE aliases ILIKE '%%' || %s || '%%' LIMIT 1",
            [term],
        )
    row = await cur.fetchone()
    if row:
        return _found(term, row, "alias_substring", 0.7)

    # 6. Not found
    return _not_found(term, entity_type or "")


def _found(term: str, row: dict, match_type: str, confidence: float) -> dict:
    return {
        "term": term,
        "entity_type": row["entity_type"],
        "found": True,
        "name": row["name"],
        "code": row["code"],
        "match_type": match_type,
        "confidence": round(confidence, 3),
    }


def _word_overlap_ratio(term: str, search_text: str) -> float:
    """Compute the fraction of query words that appear in the search text.

    Returns 0.0-1.0. Used as a real confidence signal.
    """
    term_words = {w.lower() for w in term.split() if len(w) > 1}
    if not term_words:
        return 0.0
    search_lower = search_text.lower()
    matched = sum(1 for w in term_words if w in search_lower)
    return matched / len(term_words)


def _compute_confidence(term: str, candidate: dict) -> float:
    """Compute real confidence from available signals.

    Uses the best of:
    - Vector cosine similarity (0-1, most reliable)
    - Word overlap ratio (0-1, simple but effective)

    Returns 0.0-1.0.
    """
    signals = []

    # Vector similarity — most reliable signal
    vec_score = candidate.get("vec_score")
    if vec_score is not None and vec_score > 0:
        signals.append(float(vec_score))

    # Word overlap — simple but catches obvious mismatches
    search_text = candidate.get("search_text", candidate.get("name", ""))
    overlap = _word_overlap_ratio(term, search_text)
    if overlap > 0:
        signals.append(overlap)

    if not signals:
        return 0.0

    # Use the maximum signal — if either method is confident, trust it
    return max(signals)


async def _fts_search(cur, term: str, type_filter: str | None) -> list[dict]:
    """Run FTS search — try AND first, fall back to OR.

    Returns results with an 'fts_mode' field ('and' or 'or') so the caller
    can decide whether a vector search is worth the cost.
    Results are re-ranked by word overlap with the original term to break ties.
    """
    # AND query (all words must match) — high confidence
    if type_filter:
        await cur.execute(
            "SELECT entity_type, name, code, search_text, "
            "  ts_rank(fts_vector, plainto_tsquery('english', %s)) AS score "
            "FROM entity_search "
            "WHERE entity_type = %s AND fts_vector @@ plainto_tsquery('english', %s) "
            "ORDER BY score DESC LIMIT %s",
            [term, type_filter, term, _RRF_CANDIDATES],
        )
    else:
        await cur.execute(
            "SELECT entity_type, name, code, search_text, "
            "  ts_rank(fts_vector, plainto_tsquery('english', %s)) AS score "
            "FROM entity_search "
            "WHERE fts_vector @@ plainto_tsquery('english', %s) "
            "ORDER BY score DESC LIMIT %s",
            [term, term, _RRF_CANDIDATES],
        )
    results = await cur.fetchall()
    if results:
        ranked = _rerank_by_word_overlap(term, [dict(r) for r in results])
        return [{**r, "fts_mode": "and"} for r in ranked]

    # OR query (any word can match) — lower confidence, needs vector to confirm
    words = [w for w in term.split() if len(w) > 1]
    if not words:
        return []
    or_query = " | ".join(words)
    if type_filter:
        await cur.execute(
            "SELECT entity_type, name, code, search_text, "
            "  ts_rank(fts_vector, to_tsquery('english', %s)) AS score "
            "FROM entity_search "
            "WHERE entity_type = %s AND fts_vector @@ to_tsquery('english', %s) "
            "ORDER BY score DESC LIMIT %s",
            [or_query, type_filter, or_query, _RRF_CANDIDATES],
        )
    else:
        await cur.execute(
            "SELECT entity_type, name, code, search_text, "
            "  ts_rank(fts_vector, to_tsquery('english', %s)) AS score "
            "FROM entity_search "
            "WHERE fts_vector @@ to_tsquery('english', %s) "
            "ORDER BY score DESC LIMIT %s",
            [or_query, or_query, _RRF_CANDIDATES],
        )
    results = await cur.fetchall()
    ranked = _rerank_by_word_overlap(term, [dict(r) for r in results])
    return [{**r, "fts_mode": "or"} for r in ranked]


def _rerank_by_word_overlap(term: str, results: list[dict]) -> list[dict]:
    """Re-rank FTS results by word overlap with the search term.

    When FTS returns multiple results with similar ts_rank scores, the
    original term's words are matched against each result's search_text
    to produce a tiebreaker score.  This ensures "Google Cloud data"
    ranks "Google Cloud Professional Data Engineer" above
    "Google Cloud Professional Cloud Architect".
    """
    if len(results) <= 1:
        return results

    term_words = {w.lower() for w in term.split() if len(w) > 1}
    if not term_words:
        return results

    for r in results:
        search_lower = r.get("search_text", "").lower()
        overlap = sum(1 for w in term_words if w in search_lower)
        # Combined score: FTS score + overlap bonus (overlap is more decisive)
        r["_combined"] = float(r.get("score", 0)) + (overlap * 0.1)

    results.sort(key=lambda r: r["_combined"], reverse=True)
    return results


async def _batch_embed(terms: list[str], ctx=None) -> list[list[float]] | None:
    """Embed multiple terms in ONE Azure OpenAI API call.

    Returns a list of embedding vectors aligned with the input list,
    or ``None`` on failure (caller falls back to FTS-only resolution).
    """
    if not terms:
        return []
    try:
        from .vector_tools import _get_openai_client
        from talent_backend.config import AZURE_OPENAI_EMBEDDING_DEPLOYMENT

        t0 = time.perf_counter()
        client = _get_openai_client()
        client_ms = (time.perf_counter() - t0) * 1000
        if client_ms > 500:
            logger.info("[resolve] client init %.0fms (credential acquisition)", client_ms)
            if ctx:
                await ctx.info(f"[resolve] credential acquisition: {client_ms:.0f}ms")

        t1 = time.perf_counter()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.embeddings.create(
                input=terms,
                model=AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            ),
        )
        api_ms = (time.perf_counter() - t1) * 1000
        logger.info("[resolve] embedding API call: %d terms in %.0fms", len(terms), api_ms)
        if ctx:
            await ctx.info(f"[resolve] embedding API: {len(terms)} terms in {api_ms:.0f}ms")

        # API may return embeddings out of order — sort by index
        sorted_data = sorted(response.data, key=lambda d: d.index)
        return [d.embedding for d in sorted_data]
    except Exception as exc:
        logger.warning("[resolve] batch embedding failed: %s", exc)
        return None


async def _vector_search_with_embedding(
    cur, embedding: list[float], type_filter: str | None,
) -> list[dict]:
    """Run vector similarity search with a pre-computed embedding vector."""
    vec_str = str(embedding)
    if type_filter:
        await cur.execute(
            "SELECT entity_type, name, code, "
            "  1 - (embedding <=> %s::vector) AS score "
            "FROM entity_search "
            "WHERE entity_type = %s AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            [vec_str, type_filter, vec_str, _RRF_CANDIDATES],
        )
    else:
        await cur.execute(
            "SELECT entity_type, name, code, "
            "  1 - (embedding <=> %s::vector) AS score "
            "FROM entity_search "
            "WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            [vec_str, vec_str, _RRF_CANDIDATES],
        )
    results = await cur.fetchall()
    return [dict(r) for r in results]


def _rrf_merge(fts_results: list[dict], vec_results: list[dict]) -> list[dict]:
    """Reciprocal Rank Fusion of FTS and vector search results.

    RRF score = 1/(k + rank_fts) + 1/(k + rank_vec)
    where k = 60 (standard constant).
    """
    if not fts_results and not vec_results:
        return []

    candidates: dict[str, dict] = {}

    for rank, r in enumerate(fts_results, start=1):
        name = r["name"]
        if name not in candidates:
            candidates[name] = {"name": name, "code": r["code"], "entity_type": r["entity_type"],
                                "search_text": r.get("search_text", "")}
        candidates[name]["fts_rank"] = rank
        candidates[name]["fts_score"] = float(r.get("score", 0))

    for rank, r in enumerate(vec_results, start=1):
        name = r["name"]
        if name not in candidates:
            candidates[name] = {"name": name, "code": r["code"], "entity_type": r["entity_type"]}
        candidates[name]["vec_rank"] = rank
        candidates[name]["vec_score"] = float(r.get("score", 0))

    for c in candidates.values():
        fts_rank = c.get("fts_rank")
        vec_rank = c.get("vec_rank")
        rrf = 0.0
        if fts_rank is not None:
            rrf += 1.0 / (_RRF_K + fts_rank)
        if vec_rank is not None:
            rrf += 1.0 / (_RRF_K + vec_rank)
        c["rrf_score"] = rrf

    ranked = sorted(candidates.values(), key=lambda x: x["rrf_score"], reverse=True)
    return ranked
