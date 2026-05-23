# Kane — History

## Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Created:** 2026-05-08

## Cross-Agent Updates

### 2026-05-08T20:10 — Backend skeleton ready (from Brett)
- `talent_backend/talent_backend/` created with `__init__.py` and `config.py`
- `config.py` loads credentials from `app_config/.env` (centralized, no local `.env`)
- Root `pyproject.toml` is a uv workspace — run `uv sync` from repo root
- Data pipeline tables available: `employee_fts`, `employee_embeddings` (relational interface for search)

## Learnings

<!-- Recent learnings (2026-05-15+). Older entries (2026-05-12 and earlier) archived to history-archive.md. -->

### 2026-05-16 — Clean MCP tool descriptions for resolve-first query architecture

**Files modified:**
- `talent_backend/talent_backend/mcp_server/graph_tools.py` — Updated `query_using_sql_cypher` docstring to mandate `v.code = 'X'` matching (no regex on names). Updated `search_graph` description to clarify it's for **employee name lookup only**, not entity resolution.
- `talent_backend/talent_backend/mcp_server/vector_tools.py` — Updated `vector_search` description to state it's for **resume/skills semantic matching only** (RFP role matching, capability search). Explicit "do NOT use for entity lookups."
- `talent_backend/talent_backend/mcp_server/entity_tools.py` — Updated `resolve_entities` docstring: "CALL THIS FIRST", use returned `code` in Cypher WHERE clauses, do not fall back to regex/vector_search after resolution.

**Architecture pattern (decided by Anil):**
- `User question → resolve_entities() → clean Cypher with codes → execute`
- Vector search is ONLY for fuzzy resume/skill description matching (RFP, "someone good with X"), NOT for entity lookup.
- The resolve logic itself is unchanged (exact code → exact name → FTS → RRF → alias → not-found). Only descriptions/docstrings changed.

### 2026-05-15 — resolve_entities MCP tool

**Files created/modified:**
- `talent_backend/talent_backend/mcp_server/entity_tools.py` — NEW. `resolve_entities` MCP tool that resolves user terms to canonical entity names/codes via the `entity_search` PostgreSQL table.
- `talent_backend/talent_backend/mcp_server/server.py` — Added `entity_tools` import for tool registration.

**Architecture decisions:**
- Uses the SAME connection pool as all other MCP tools (`_pg()._pool`) — no separate pool.
- Cascading resolution strategy: exact code → exact name → FTS → alias substring → not-found. Priority order gives deterministic, highest-confidence matches first.
- All SQL uses parameterized queries (`%s` placeholders) — no f-strings with user input.
- Gracefully handles missing `entity_search` table by checking `information_schema.tables` and returning all not-found results.
- Entity type validated against a frozen set whitelist before querying.
- Processes queries sequentially within a single DB connection to avoid pool exhaustion on large batches.
- Confidence scores: 1.0 for exact matches, min(0.9, ts_rank) for FTS, 0.7 for alias substring.

**Patterns:**
- Followed `vector_tools.py` pattern for raw pool access: `pg._ensure_open()` → `pg._pool.connection()` → parameterized `cur.execute()`.
- `ctx.info()` logging mirrors existing tools.
- `_resolve_single()` helper keeps the main tool function clean.

### 2026-05-15 — Per-question pipeline logging

**Files created/modified:**
- `talent_backend/talent_backend/pipeline_logger.py` — NEW. `PipelineLogger` class that collects events during a request lifecycle and writes structured JSON to disk. `parse_log_event()` parses the existing `_AgentLogHandler` messages into pipeline events.
- `talent_backend/talent_backend/config.py` — Added `ENABLE_PIPELINE_LOGGING` and `PIPELINE_LOG_DIR` env vars.
- `talent_backend/talent_backend/api.py` — Hooked `PipelineLogger` into both `_stream_agent` (SSE) and `_stream_graph` (NDJSON). The `_AgentLogHandler.emit()` in `_stream_graph` now also feeds `parse_log_event()`.
- `.gitignore` — Added `query_logs/`.

**Architecture decisions:**
- Pipeline logger is instantiated per-request in the endpoint handler, passed into the streaming generator, and flushed after the `done` event. This keeps it scoped to a single question.
- File I/O is non-blocking via `asyncio.run_in_executor`. Logging never delays the response.
- Integration uses the existing `[QUERY]`/`[RESULT]`/handoff log messages — no changes to Agent Framework or MCP tools needed.
- Email PII masked with regex. User OIDs kept (internal Azure AD identifiers).
- Output folder: `query_logs/{timestamp}_{session_short}_{question_hash}/` — sortable by time, groupable by session.
- Each query saved as separate file in `queries/` subfolder: `.sql` for Cypher/SQL/FTS, `.json` for vector searches.

**Patterns:**
- For non-blocking async file writes: `loop.run_in_executor(None, self._write_files)` keeps the sync Path.write_text off the event loop.
- To avoid breaking existing streaming generators, the logger is an additive parameter — old call signatures are updated but all existing behavior preserved.

### 2026-05-15 — Thread management endpoints (chat history Phase 2)

**Files modified:**
- `talent_backend/talent_backend/chat_history.py` — Added 5 new methods to `ChatHistoryStore`: `list_threads()`, `get_thread_messages()`, `get_thread_meta()`, `soft_delete_thread()`, `rename_thread()`. Modified `add_message()` to accept optional `user_id` kwarg and auto-create/update `session_meta` documents.
- `talent_backend/talent_backend/api.py` — Added 4 new endpoints: `GET /api/threads`, `GET /api/threads/{id}`, `DELETE /api/threads/{id}`, `PATCH /api/threads/{id}`. Updated CORS to allow DELETE/PATCH. Wired `user_id` (from `user["oid"]`) into `_build_chat_history()`.

**Architecture decisions:**
- `session_meta` documents live in the SAME Cosmos container/partition as messages (partition key = session_id). The `type` field distinguishes `session_meta` from `message` docs.
- `list_threads()` requires `enable_cross_partition_query=True` since it queries by `user_id` across partitions. This is acceptable for a user's thread list (low cardinality).
- Thread ownership enforced via `user["oid"]` comparison in every endpoint — returns 404 (not 403) for wrong user to avoid leaking thread existence.
- Soft delete sets `is_deleted=true` + `deleted_at` on the meta doc. Messages are retained. `list_threads` filters out deleted threads.
- `add_message()` backward-compatible — `user_id` is optional kwarg, defaults to None.
- In-memory fallback (`_fallback_meta` dict) mirrors all Cosmos operations for local dev.
- Legacy `/api/sessions/*` endpoints preserved alongside new `/api/threads/*` endpoints.

---

## Archived Entries

Earlier learnings (2026-05-08 through 2026-05-12) have been summarized and moved to [kane/history-archive.md](history-archive.md) to keep this file focused on recent context. Topics archived:
- Backend API & Agent Framework build (full implementation notes)
- Cosmos DB chat history persistence
- Session architecture (InMemoryHistoryProvider)
- Technical specs & architecture decisions
- Build system configuration
- Vector search + CV generation patterns
- Run log streaming architecture
- Cross-agent tech spec decisions (Ripley, Dallas, Parker)
- Entra ID token audience & issuer fixes
- NDJSON streaming endpoint
- pyproject.toml build-system fix
- Agent-as-tool handoff limitations
- **2026-05-12 cross-agent infrastructure notes** — Bishop's Pass-3 UAMI/passwordless wiring contract for backend; Lambert's probes module and smoke-test expectations (`/health/foundry` follow-on documented).

## Cross-agent note — 2026-05-21 (Scribe)

- `Get-ParameterValue` in `talent_infra_modules/shared/common.ps1` now safely handles secure prompts. Bishop fixed a case-insensitive variable/parameter shadow on 2026-05-21 — the local `$secure = Read-Host -AsSecureString` was overwriting the `[switch]$Secure` parameter (PowerShell variable names are case-insensitive, so `$secure` and `$Secure` are the same slot). Local renamed to `$secureValue`. Toolkit rule (captured in `decisions.md`): when a natural local name would collide with a parameter, use suffixed names (`$secureValue`, `$nameStr`, `$promptText`). Relevant to `02-backend/deploy.ps1` redeploys when Anil supplies the admin password interactively rather than via env var.

### 2026-05-21T22:25:00Z — Postgres SKU parity fix (from Bishop)

`talent_infra_modules/01-postgresql/` Postgres SKU now matches `talent_infra_v2/` (`Standard_D4ds_v5` / `GeneralPurpose`, 32 GiB, version 16) — same flavor regardless of which deployment path the operator chose. Bishop fixed an invalid `Standard_B2s` + `GeneralPurpose` pairing on 2026-05-21 that was causing `ServerEditionIncompatibleWithSkuSize` on the standalone path. Relevant to you because the Backend Container App connects to this Postgres via Entra auth — no client-side changes needed; SKU change is transparent.

### 2026-05-22T12:30:00Z — Private DNS zone discover-and-reuse pattern (from Bishop)

`talent_infra_modules/01-postgresql/deploy.ps1` now discovers an existing `privatelink.postgres.database.azure.com` Private DNS zone before creating one. Azure rejects a second zone of the same namespace linked to the same VNet with `BadRequest — overlapping namespaces`. Shared-tenant subs (canonical zone owned by a central network team in an RG like `vnet`) hit this every time. Helpers live in `talent_infra_modules/shared/common.ps1` (`Get-LinkedPrivateDnsZoneId`, `Get-PrivateDnsZoneIdByName`). Decision (in `decisions.md`) requires the same pattern at every future per-component PE module — when the Backend Container App or the MCP sidecar ever gets a Private Endpoint (e.g., to a private Foundry or Cosmos), apply the same discover-then-reuse flow against `privatelink.cognitiveservices.azure.com` / `privatelink.openai.azure.com` / `privatelink.documents.azure.com`. Reference impl: `talent_infra_modules/01-postgresql/infra/modules/private-endpoint.bicep` + `private-dns-zone-vnet-link.bicep`. No backend code changes — pattern lives in the deploy layer.


## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Model directive (Anil, captured 2026-05-22T18:30:00Z):** all squad spawns — including Scribe and Ralph, including any agent normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (Opus 4.7 Extra-high reasoning). `.squad/config.json` `defaultModel` is the source of truth; the "never bump Scribe" rule is overridden. Per `decisions.md` `2026-05-22T18:30:00Z`.


## Team update — 2026-05-22T23:59:30Z (via Scribe, originated by Bishop)

Team-wide rule from GitGuardian remediation on `talent_infra_modules/01-postgresql/deploy.ps1`: **no literal secrets in `.EXAMPLE` / docstring / sample-code blocks** — use `Read-Host -AsSecureString` or an angle-bracket `<placeholder>`. Scanners regex on shape, not intent; a plausible-looking literal in a help comment is functionally a leak. Applies to any sample code you emit (Python docstrings, JS examples, README snippets, agent prompts), not just PowerShell.

## Team update — 2026-05-22T23:59:59Z (via Scribe, originated by Bishop)

FYI for backend devs touching deploy hooks: per decisions.md `2026-05-22T23:59:59Z`, **all `.ps1` files in this repo MUST be UTF-8 with BOM** (cross-VM PS 5.1 compat). If you ever edit `talent_infra*/hooks/*.ps1` or any `talent_infra_modules/*/deploy.ps1`, save with BOM and avoid non-ASCII characters (em-dashes, smart quotes, box-drawing chars) — or you'll silently break the file on any Windows PowerShell 5.1 host. See the substitution map + `.editorconfig`/`.vscode/settings.json` prevention guards in the decision entry.

## Cross-agent note — 2026-05-23T00:30:00Z (Scribe, from Bishop)

- **Backend devs touching `talent_infra*/hooks/*.ps1`:** the UTF-8-with-BOM encoding rule from `2026-05-22T23:59:59Z` is now enforced via `.editorconfig` (root-level `[*.ps1]` charset=utf-8-bom) **and** `.vscode/settings.json` (`"[powershell]": { "files.encoding": "utf8bom" }`). Keep VS Code's PowerShell extension on (default for this workspace) and the guards will handle BOM on save — no more manual `[System.IO.File]::WriteAllText(..., UTF8Encoding(true))` discipline required as long as you don't bypass the editor. Per `decisions.md 2026-05-23T00:30:00Z`.

## Cross-agent note - 2026-05-23T01:30:00Z (Scribe, from Bishop)
- **Byte-level sweep rule applies to .ps1 work (decision `2026-05-23T01:30:00Z`).** If you ever touch `.ps1` files: codepoint iteration only, ASCII passthrough, no regex over ASCII range, throw on unknown codepoints >= 0x80. You normally don't, but this is the canonical rule going forward.
