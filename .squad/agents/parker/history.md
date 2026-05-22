# Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Created:** 2026-05-08

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

> **Older entries (2026-05-09 — 2026-05-12) archived to [`history-archive.md`](./history-archive.md) on 2026-05-22T23:55:00Z by Scribe.**
> Archived: Data Access Layer Created, Kane's API & Agent layer, MCP Server Created, Kane's Agent Framework rewrite, Database Architecture Spec Written, Tech spec decisions affecting Parker, Bishop's infrastructure Pass 2, Bishop's infrastructure Pass 3.

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

## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Model directive (Anil, captured 2026-05-22T18:30:00Z):** all squad spawns — including Scribe and Ralph, including any agent normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (Opus 4.7 Extra-high reasoning). `.squad/config.json` `defaultModel` is the source of truth; the "never bump Scribe" rule is overridden. Per `decisions.md` `2026-05-22T18:30:00Z`.

## Cross-agent note — 2026-05-22T23:45:00Z (Scribe, from Brett)
- **Pipeline layout cleanup (Brett, requested by Anil):** the outer `talent_data_pipeline/{loaders,generators,schema}/` flat-layout folders are GONE (13 files deleted: loaders=5, generators=6, schema=2). The nested `talent_data_pipeline/talent_data_pipeline/` package is now the SOLE source of truth for pipeline schema/queries — no more dual-edit discipline, no more silent divergence between outer and nested copies. Pre-flight import scan returned zero hits; post-delete smoke test (`from talent_data_pipeline.loaders.{base,fts,graph,vector,entity_search}_loader import *`) returned OK. Deletions are unstaged (` D` in git); Anil owns the commit. All your future schema/query work goes directly into the nested package. Per `decisions.md` `2026-05-22: talent_data_pipeline outer folders are stale refactor artifacts`.

## Cross-agent note — 2026-05-22T23:55:00Z (Scribe, from Brett)
- **Pipeline CLI change (Brett, requested by Anil):** `talent_data_pipeline.main` gained a first-class `--mode {env,manual}` flag + `DATALOAD_MODE` env var. Precedence: **CLI > env var > default (`env`)**. `env` is identical to today's behavior (no prompts, reads everything from `.env`); `manual` interactively prompts `PG host [<current PGHOST>]:` (host ONLY — port/user/database/sslmode stay from `.env`), Enter accepts default, up to 3 attempts. Invalid env-var values and `--mode manual` + no-TTY both fail fast with exit 2 (never silently re-route, never hang in CI). Host override flows through new `config.apply_host_override(host)` which mutates the `db_config` singleton **in place** via `object.__setattr__` (bypassing `@dataclass(frozen=True)`) so every lazy reader (`base_loader._get_pool()`, `pg_connect()`, etc.) picks up the new host on next read — rebinding `config.db_config = NewInstance()` would have left those references stale. Entra `DefaultAzureCredential` path in `pg_entra.pg_connect()` is fully preserved (no password fallback). Inner package only — outer stubs at `talent_data_pipeline/{main,config,validate,connectivity_test}.py` deliberately left alone per 2026-05-22 cleanup. Verification: 14/14 isolated unit checks + `py_compile` + `--help` + live no-TTY exit. Pipeline-code git commit owned by Anil. Per `decisions.md 2026-05-22T23:55:00Z`.

## Cross-agent note — 2026-05-22T23:58:00Z (Scribe, from Brett)
- **Empty-`PGUSER` pitfall + new `pg_entra` hint behavior (Phase 1 connectivity test root cause, 2026-05-22).** Anil hit `FATAL: password authentication failed for user "anildwa"` against `tiqpg9a6d3.postgres.database.azure.com` despite the pipeline being Entra-token-only since 2026-05-12. Root cause: `app_config/.env` line 55 was literally `PGUSER=` (empty) → `db_config.user=""` → libpq fell back to the **OS account name** (`anildwa` on Windows) → PG looked up the role bound to `user="anildwa"`, didn't match the principal in the bearer token, rejected. H1 (Phase 1 bypasses Entra) was FALSIFIED — `talent_data_pipeline/talent_data_pipeline/connectivity_test.py:_connect()` already calls `pg_entra.pg_connect()`; repo-wide grep confirms exactly one `psycopg2.connect()` in the inner package and zero `PGPASSWORD` refs. Brett shipped a hint-wrapping `try/except` in `pg_entra.pg_connect()` and `EntraThreadedConnectionPool._connect()`: when libpq returns `password authentication failed` (case-insensitive), the original `psycopg2.OperationalError` is re-raised (chained via `raise ... from exc`) with a multi-line hint covering the empty-PGUSER (OS-fallback) and short-PGUSER (no `@`) cases. **No password fallback added; no auto-mutation of `PGUSER`.** As pipeline co-owner: any new loader, queries module, or batch job you add MUST route its PG connection through `pg_entra.pg_connect()` or `EntraThreadedConnectionPool` to inherit the hint automatically. Pre-commit guardrail grep (still passing): `grep -RInE "psycopg2\.connect\(|psycopg2\.pool" talent_data_pipeline/talent_data_pipeline/` must return exactly one match — the call inside `pg_entra.pg_connect`. Per `decisions.md 2026-05-22T23:59:00Z`.