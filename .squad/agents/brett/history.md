# Brett — History

> Older entries archived to `history-archive.md` on 2026-05-16 by Scribe.

## Project Context
- **Project:** TalentIQ — Talent Matching/Searching platform
- **Owner:** Anil
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, PostgreSQL + Apache AGE (graph), DiskANN (vectors), FTS
- **My role:** Data Generator & Database Loader — generate realistic talent data from the DXC ontology, load into PostgreSQL/AGE, vectorize with DiskANN, build FTS indexes

## Ontology Summary
- 15 node labels: Employee (130K), Location (46), Country (19), Subregion (15), Skill (96), SkillDomain (13), Certification (39), Language (18), ServiceLine (8), Offering (8), Manager (80), University (75), Client (36), Project (22), Role (17)
- 13 edge types: LOCATED_IN, IN_COUNTRY, SPECIALIZES_IN, HAS_SKILL, HOLDS_CERT, SPEAKS, BELONGS_TO_SL, WORKS_IN_OFFERING, REPORTS_TO, STUDIED_AT, WORKED_FOR, WORKED_ON, HAS_ROLE
- 130,475 total nodes, ~2.6M total edges
- 19 countries with specific distribution percentages

## Work Log

### 2026-05-08 through 2026-05-09 (Archived — see history-archive.md)
Built complete data pipeline (18 files), restructured project (rename + uv workspace + centralized config), added checkpoint/resume to loading + embedding generation, rewrote edge loader (Cypher MERGE -> direct SQL batch INSERT for 10,000x speedup), switched embeddings from sentence-transformers to Azure OpenAI ada-002 (1536-dim).

### 2026-05-12 — Cross-agent: Bishop infrastructure Passes 2 and 3
PostgreSQL provisioned with Entra ID-only auth. Pipeline must authenticate using Entra tokens. Outer stub file kept in sync.

### 2026-05-15 — Added code + aliases to all reference entities + entity_search table
Added `code` and `aliases` fields to ALL 10 reference entity types. Created `entity_search` table for unified FTS + vector search across reference/dimension entities. SKILLS_BY_DOMAIN restructured from `list[str]` to `list[dict]`. Added entity_search_loader.py wired as step 4g. All changes applied to both outer stubs and inner package.

### 2026-05-16 — Added Role as a canonical entity to the data model
Unified 17 roles (previously hardcoded strings in 3 generators) into canonical `Role` entity with code + aliases. Added `HAS_ROLE` as 1:1 Employee -> Role edge. Added `role_name` field to Employee (alongside existing `job_title`). AGE property indexes: `idx_role_name`, `idx_role_code`. Role added to ENTITY_SOURCES for FTS + embeddings. All changes applied to both outer stubs and inner package (14 files).

## Learnings
- SKILLS_BY_DOMAIN change from str->dict is a breaking API change — need to update all downstream consumers
- `_cypher_escape` must handle Python lists for AGE Cypher array properties
- Entity search table uses `UNIQUE (entity_type, name)` constraint for UPSERT idempotency
- Inner package files are NOT always identical to outer stubs — must update each independently
- Deduplicating roles across generators: unify all hardcoded lists into single reference data source
- `role_name` on Employee serves dual purpose: edge generation metadata for HAS_ROLE, and structured query alternative to regex on `job_title`
- **2026-05-22 — Stale outer pipeline folders removed.** Deleted the leftover flat-layout artifacts `talent_data_pipeline/{loaders,generators,schema}/` (13 tracked files total: loaders=5, generators=6, schema=2). All entry scripts (`main.py`, `validate.py`, `connectivity_test.py`) and `pyproject.toml` (`packages = ["talent_data_pipeline"]`) only ever referenced the nested package, and the inner copies had diverged with checkpoint/resume + batched `execute_values` optimizations the outer stubs lacked. Pre-flight import scan across the repo (excluding `.venv`/`__pycache__`/`node_modules`) found zero hits on bare `loaders|generators|schema` imports; post-delete smoke test `from talent_data_pipeline.loaders.{base,fts,graph,vector,entity_search}_loader import *` returned `OK`. Going forward, the nested `talent_data_pipeline/talent_data_pipeline/` package is the sole source of truth — no more dual-edit discipline, no more silent divergence between outer stubs and inner package. The 13 deletions are unstaged (` D`) in git; Anil decides when to commit.


## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Model directive (Anil, captured 2026-05-22T18:30:00Z):** all squad spawns — including Scribe and Ralph, including any agent normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (Opus 4.7 Extra-high reasoning). `.squad/config.json` `defaultModel` is the source of truth; the "never bump Scribe" rule is overridden. Per `decisions.md` `2026-05-22T18:30:00Z`.
