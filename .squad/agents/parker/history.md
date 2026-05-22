# Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Created:** 2026-05-08

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-05-09: Data Access Layer Created
- **Path:** `talent_backend/talent_backend/data_access/` — 8 files (init, connection, models, cypher_queries, sql_queries, vector_queries, fts_queries, hybrid_queries)
- **Pattern:** All functions are async, accept `AsyncConnection` from psycopg3, return Pydantic v2 models
- **Connection:** `AsyncConnectionPool` singleton with optional Entra ID token auth via `azure.identity.aio`
- **AGE queries:** Use `_cypher()` helper that wraps `ag_catalog.cypher('{graph_name}', $$ ... $$)`. Search path set on connection acquire via pool configure callback
- **agtype parsing:** `_parse_agtype()` strips ::vertex/::edge suffixes then JSON-parses. AGE returns properties inside a `properties` key in vertex JSON
- **Input sanitization:** `_sanitize_identifier()` escapes `\` and `'` for values injected into Cypher `$$` blocks. All SQL queries use `%s` parameterised placeholders
- **Hybrid search:** `multi_criteria_search()` fans out to graph + vector + FTS, normalises scores per-engine, then weighted-merges with configurable weights dict
- **Key tables:** `employee_embeddings` (vector(1536) resume + skills), `employee_fts` (tsvector + trigram indexes)
- **Graph name:** loaded from `GRAPH_NAME` env var, default `talent_graph`, available as `connection.GRAPH_NAME`

### 2026-05-09 — Cross-agent: Kane's API & Agent layer
- Kane built the FastAPI backend that consumes this data access layer
- Chat endpoint: `/api/v1/chat` → `TalentAgent` (OpenAI function calling, 9 tools mapped to data_access functions)
- Search endpoints: `/api/v1/search/candidates`, `/search/employee/{id}`, `/search/semantic`, `/search/text`, `/search/team/{id}`
- Health: `/health/live` + `/health/ready` (checks DB pool)
- Auth: Entra ID JWT validation; bypass with `TALENTIQ_AUTH_DISABLED=true` for local dev
- Lazy imports: Kane's tools.py and search.py use lazy `from talent_backend.data_access import ...` — no startup crash
- Agent tool dispatch in `tools.py` calls data_access functions by name

### 2026-05-09: MCP Server Created
- **Path:** `talent_backend/talent_backend/mcp_server/` — 4 files (__init__, pg_age_helper, server, run_server)
- **Architecture:** Standalone FastMCP process on port 3002 (env: `MCP_PORT`), separate from FastAPI backend
- **Transport:** `streamable-http` — agent connects via `MCPStreamableHTTPTool`
- **Tools exposed:** `fetch_ontology`, `save_ontology`, `query_using_sql_cypher`, `discover_nodes`, `search_graph`, `resolve_entity_ids`, `build_query_context`, `analyze_graph_statistics`
- **Pre-loaded ontology:** Full talent_graph schema (14 node labels, 12 edge labels) hardcoded in `_TALENT_GRAPH_ONTOLOGY` — eliminates discovery round-trip
- **PGAgeHelper:** Async psycopg3 `AsyncConnectionPool`, sets AGE search_path on every query, parses agtype results
- **Name verification:** FTS results are name-verified via Cypher follow-up to filter false positives
- **FTS dependency:** Uses `public.search_graph_nodes()` SQL function — must exist in DB
- **Existing data_access layer preserved:** Still used by `/api/v1/search/*` structured endpoints — MCP server is additive for agent workflow
- **Windows compat:** `WindowsSelectorEventLoopPolicy` + `PSYCOPG_IMPL=python` fallback for Windows dev
- **CORS:** Permissive CORS middleware for local dev (origins=*, expose Mcp-Session-Id header)
- **SQL sanitization:** `_sanitize_sql_string()` helper escapes single quotes for f-string SQL interpolation

### 2026-05-09 — Cross-agent: Kane's Agent Framework rewrite
- Kane rewrote `talent_agent.py` to use Agent Framework SDK (`agent_framework>=1.3.0`) with `MCPStreamableHTTPTool`
- Agent now connects to this MCP server at `MCP_ENDPOINT` (default `http://localhost:3002/mcp`)
- All 9 manual tool definitions removed from agent side — MCP server is the sole tool provider for agent queries
- `tools.py` retained only `generate_embedding()` for search endpoints
- Chat history added via Cosmos DB — new endpoints: `GET/DELETE /sessions`, `POST /chat` returns `message_id`
- Existing data_access layer still powers structured search endpoints (`/api/v1/search/*`)

### 2026-05-10: Database Architecture Spec Written
- **Path:** `docs/specs/database-architecture.md` — comprehensive technical spec covering all 4 query paradigms
- **Key patterns documented:**
  - AGE `ag_catalog.cypher()` wrapping with search_path management, agtype parsing rules
  - 14 node labels, 12 edge labels, ~130K nodes, ~1.87M edges — full property schemas
  - DiskANN/HNSW auto-detection: pipeline checks `pg_extension` for vectorscale/pg_diskann, falls back to HNSW
  - Vector column whitelist (`_VALID_COLUMNS`) prevents injection — only `resume_embedding` or `skills_embedding` allowed
  - FTS preprocessing: title stripping, progressive retry with shorter terms, name verification post-filter
  - AGE property indexes use `agtype_access_operator()` — 19 indexes on key lookup properties
  - Checkpoint system: JSON file with per-phase + per-batch tracking, atomic writes via tempfile+replace
- **Security assessment:** MCP `query_using_sql_cypher` is medium risk (agent-constructed SQL), mitigated by internal-only caller. All relational queries properly parameterised.
- **Production gaps identified:** `search_graph_nodes()` SQL function must exist in DB but is not created by pipeline; `employee_ageid` columns always 0 (AGE vertex ID cross-ref not wired); `pg_trgm` not guaranteed on Azure

### 2026-05-10: Cross-agent — Tech spec decisions affecting Parker
- **Ripley:** PostgreSQL uses delegated subnet (not private endpoint) in VNet design. NAT Gateway for egress.
- **Kane:** ChatHistoryStore async SDK migration planned — no impact on Parker's data layer. Session management feature flag does not affect DB schema.
- **Parker production gaps acknowledged by team:** Must resolve `search_graph_nodes()`, `employee_ageid`, and `pg_trgm` before staging.

### 2026-05-12 — Cross-agent: Bishop's infrastructure Pass 2
- **Bishop completed:** PostgreSQL Flexible Server (PG 16) provisioned with Entra ID-only auth, delegated subnet integration, extensions allowlisted (age, vector, pg_trgm, pg_stat_statements)
- **For Parker:** `pg_trgm` extension is now in the allowlist and will be available on Azure deployment. Continue resolving production gaps: `search_graph_nodes()` SQL function creation, `employee_ageid` wiring, `pg_trgm` extension availability confirmation on Azure PG
- **Deployment hook:** Once `azd up` runs, PostgreSQL will be live. Data pipeline can connect via connection string + Entra ID token auth

### 2026-05-12 — Cross-agent: Bishop's infrastructure Pass 3 — PostgreSQL extensions confirmed
**From Bishop (Deployment Engineer):**
- PostgreSQL extensions are **confirmed in Bicep:** `age`, `vector`, `pg_trgm`, `pg_stat_statements` are all allowlisted in `talent_infra/modules/postgres.bicep`.
- When `azd up` runs, these extensions will be created on PostgreSQL server.
- **For Parker:** Data pipeline can now assume all 4 extensions are available on Azure deployment. No fallback logic needed for production.
- **MCP Server:** Confirmed using `public.search_graph_nodes()` SQL function — schema setup will run after `azd up` provisions PostgreSQL. This function must be created as part of schema initialization step (not yet wired; will be part of separate `azd postprovision` hook or manual schema migration).

### 2026-05-15: Agent instructions updated for entity resolution workflow
- **Path:** `talent_backend/talent_backend/agent/instructions/TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md`
- **What changed:**
  - Added `resolve_entities` MCP tool to Tools section — resolves user terms to canonical names/codes before Cypher
  - Updated NODE LABELS: 10 reference entities (Certification, Skill, Country, SkillDomain, ServiceLine, Offering, University, Client, Language, Project) now show `code` and `aliases` properties
  - Rewrote Workflow section: new 7-step entity-resolution-first flow — parse → classify → resolve → build Cypher → execute → format
  - Added Entity Resolution Example section showing complete worked example (BA + Poland + PMP)
  - Updated rule #10 (string matching): replaced "always use regex for entity matching" with "use `resolve_entities` to get codes, match with `entity.code = 'X'`"
  - Updated Common Query Patterns: certification example uses `cert.code = 'PMP'`, country example uses `c.code = 'ES'` and `s.code = 'PYTHON'`
- **Key principle:** Canonical entities (Certification, Skill, Country, etc.) are resolved via `resolve_entities` tool BEFORE Cypher is built. Free-text fields (job_title, employee name) still use regex. Enum values (skill_level, status, region) used directly.
- **All 19 AGE Query Rules preserved.** RFP Multi-Role workflow preserved. Response Format preserved.

### 2026-05-16: Agent instructions rewritten for clean resolve-first architecture
- **Path:** `talent_backend/talent_backend/agent/instructions/TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md`
- **What changed:**
  - **Tools section rewritten:** `resolve_entities` is now listed FIRST with "ALWAYS call this first" directive. `search_graph` scoped to employee name lookups only. `vector_search` scoped to RFP/semantic matching only. Tool descriptions teach purpose, not mechanics.
  - **Rule #10 simplified:** Removed all specific entity examples (cert names, country names). Now states: "Entities have `code` properties. Always use `resolve_entities` to find the code." Regex rules kept for free-text fields only.
  - **Workflow section rewritten:** Reduced from 7 steps to 5 clean steps: parse → resolve → build Cypher → execute → format. Removed the classify step (resolver handles type discovery). Entity Type → MATCH Pattern table extracted as a standalone reference.
  - **Example replaced:** Old BA/Poland/PMP example replaced with "show 5 people with Google Cloud data in Poland" — demonstrates fuzzy term resolution ("Google Cloud data" → GCP-DE).
  - **Common Query Patterns updated:** All 6 examples now use `.code` matching. Bench employee example uses `s.code = 'JAVA'`. Multi-relationship example uses `s.code IN ['PYTHON', 'FASTAPI']`. Added resolve_entities comments showing the resolution step.
  - **Removed all hardcoded values:** No specific cert names, country names, or skill names appear as rules. Examples use codes as teaching patterns, not as hardcoded mappings.
- **Key principle:** Instructions teach PATTERNS, not specific values. The resolver is the single source of truth for entity→code mapping. Agent never needs to know entity codes itself.
- **Preserved:** All 19 AGE Query Rules, RFP Multi-Role Matching Workflow, Response Format, Graph Ontology.

## Cross-agent note — 2026-05-21 (Scribe)
- `Get-ParameterValue` in `talent_infra_modules/shared/common.ps1` now safely handles secure prompts. Bishop fixed a case-insensitive variable/parameter shadow on 2026-05-21 — the local `$secure = Read-Host -AsSecureString` was overwriting the `[switch]$Secure` parameter (PowerShell variable names are case-insensitive, so `$secure` and `$Secure` are the same slot). Local renamed to `$secureValue`. Toolkit rule (captured in `decisions.md`): when a natural local name would collide with a parameter, use suffixed names (`$secureValue`, `$nameStr`, `$promptText`). Relevant to `04-data-loading/deploy.ps1` runs when Anil supplies the admin password interactively rather than via env var.

### 2026-05-21T22:25:00Z — Postgres SKU parity fix (from Bishop)

`talent_infra_modules/01-postgresql/` Postgres SKU now matches `talent_infra_v2/` (`Standard_D4ds_v5` / `GeneralPurpose`, 32 GiB, version 16) — same flavor regardless of which deployment path the operator chose. Bishop fixed an invalid `Standard_B2s` + `GeneralPurpose` pairing on 2026-05-21 that was causing `ServerEditionIncompatibleWithSkuSize` on the standalone path. Relevant to you because `04-data-loading/deploy.ps1` connects to this Postgres via Entra auth — no pipeline changes needed; SKU change is transparent.

### 2026-05-22T12:30:00Z — Private DNS zone discover-and-reuse pattern (from Bishop)

`talent_infra_modules/01-postgresql/deploy.ps1` now discovers an existing `privatelink.postgres.database.azure.com` Private DNS zone before creating one. Azure enforces one Private DNS zone per namespace per VNet — a second zone of the same name linked to the same VNet (even from a different RG) is rejected with `BadRequest — overlapping namespaces`. Shared-tenant subs (canonical zone owned by a central network team in an RG like `vnet`) hit this on every new component deploy. Helpers live in `talent_infra_modules/shared/common.ps1` (`Get-LinkedPrivateDnsZoneId`, `Get-PrivateDnsZoneIdByName`). Decision (in `decisions.md`) requires the same pattern at every future per-component PE module — directly relevant when the data pipeline gets its own PE module (none today, but if Cosmos or Foundry pipeline-side connections ever go private, apply against `privatelink.documents.azure.com` / `privatelink.cognitiveservices.azure.com`). Reference impl: `talent_infra_modules/01-postgresql/infra/modules/private-endpoint.bicep` + `private-dns-zone-vnet-link.bicep`. No pipeline code changes — pattern lives in the deploy layer.