# Brett — History

## Project Context
- **Project:** TalentIQ — Talent Matching/Searching platform
- **Owner:** Anil
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, PostgreSQL + Apache AGE (graph), DiskANN (vectors), FTS
- **My role:** Data Generator & Database Loader — generate realistic talent data from the DXC ontology, load into PostgreSQL/AGE, vectorize with DiskANN, build FTS indexes

## Ontology Summary
- 14 node labels: Employee (130K), Location (46), Country (19), Subregion (15), Skill (96), SkillDomain (13), Certification (39), Language (18), ServiceLine (8), Offering (8), Manager (80), University (75), Client (36), Project (22)
- 12 edge types: LOCATED_IN, IN_COUNTRY, SPECIALIZES_IN, HAS_SKILL, HOLDS_CERT, SPEAKS, BELONGS_TO_SL, WORKS_IN_OFFERING, REPORTS_TO, STUDIED_AT, WORKED_FOR, WORKED_ON
- 130,475 total nodes, 2,609,663 total edges
- 19 countries with specific distribution percentages

## Work Log

### 2026-05-08 — Built complete data pipeline (greenfield)
Built `data_pipeline/` from scratch — 18 Python files across 4 packages:
- `config.py`, `connectivity_test.py`, `main.py`, `validate.py`
- `schema/` — graph label creation, relational tables (vector + FTS), all indexes
- `generators/` — reference data, 130K employees (culturally appropriate names via Faker locales), 12 edge types, resume summaries, embeddings
- `loaders/` — graph (Cypher MERGE), vector (pgvector upsert), FTS (tsvector)

## Learnings
- AGE labels created via `ag_catalog.create_vlabel`/`create_elabel`, not DDL
- DiskANN extension name varies: try `vectorscale` → `pg_diskann` → HNSW fallback
- Cypher MERGE is the idempotent pattern for AGE nodes/edges
- AGE property indexes use `properties->>'key'` on internal label tables
- psycopg2 ThreadedConnectionPool simpler than asyncpg for Cypher-heavy workloads
- Faker locales: `sr_RS` (Serbian), `vi_VN` (Vietnamese), `bg_BG` (Bulgarian), `es_MX` (closest for Costa Rica)
- Reference data (locations, skills, certs) hardcoded as constants for ontology fidelity
- `pyproject.toml` inside `data_pipeline/` for self-contained packaging
- Decision logged to `.squad/decisions/inbox/brett-data-pipeline-architecture.md`

### 2026-05-08 — Project restructuring: rename, uv workspace, centralized config
- Renamed `data_pipeline/` → `talent_data_pipeline/` with nested package layout (`talent_data_pipeline/talent_data_pipeline/`)
- Updated all 15 Python files' imports from `data_pipeline.*` → `talent_data_pipeline.*`
- Aligned config.py env var names to match `app_config/.env`: `PG_HOST`→`PGHOST`, `PG_PORT`→`PGPORT`, `PG_DATABASE`→`PGDATABASE`, `PG_USER`→`PGUSER`, `PG_PASSWORD`→`PGPASSWORD`, `AGE_GRAPH_NAME`→`GRAPH_NAME`; added `PGSSLMODE` support
- Created root `pyproject.toml` as uv workspace with members: `talent_data_pipeline`, `talent_backend`
- Created `talent_backend/` skeleton for Kane (config.py loads from same `app_config/.env`)
- Deleted per-folder `.env.example` — centralized in `app_config/.env`
- `uv sync --all-packages` succeeds: 47 packages installed, both workspace members built

### Learnings (2026-05-08, restructuring)
- Hatchling editable installs fail with source remapping that adds prefixes (`"." = "pkg_name"`) — use nested package layout instead (e.g. `talent_data_pipeline/talent_data_pipeline/`)
- `packages = ["talent_data_pipeline"]` in pyproject.toml requires a matching subdirectory inside the workspace member root
- For centralized `.env`, path from nested config is `Path(__file__).resolve().parent.parent.parent / "app_config" / ".env"` (3 levels: package → member root → repo root)
- `git mv` fails on untracked directories — use regular filesystem move if the folder hasn't been committed yet
- Standard PG env var names (`PGHOST`, `PGPORT`, etc.) are the convention; avoid inventing custom prefixes

### 2026-05-09 — Added checkpoint/resume to data loading pipeline
Added `checkpoint.py` module and wired checkpoint support through all loaders:
- `checkpoint.py` — `LoadCheckpoint` class: thread-safe (Lock), atomic disk writes (tmp+rename), tracks per-phase status and per-batch completion sets
- `graph_loader.py` — `load_nodes()`, `load_edges()`, `load_reference_nodes()`, `load_employees()` all accept optional `checkpoint` + `phase_key` params; skip completed phases, resume from completed batch indices
- `vector_loader.py` — `load_embeddings()` accepts checkpoint; skips completed batches on resume
- `fts_loader.py` — `load_fts_data()` accepts checkpoint; skips completed batches on resume
- `load.py` — creates `LoadCheckpoint` at startup, passes to all loaders, checks schema/indexes phases, prints resume summary if checkpoint exists, `--reset` flag deletes checkpoint for fresh load
- Checkpoint stored at `talent_synthetic_data/.load_checkpoint.json` — batch indices tracked as a set (not sequential count) to handle ThreadPoolExecutor's unordered completion

### 2026-05-09 — Rewrote edge loader: Cypher MERGE → direct SQL batch INSERT
Replaced the Cypher MERGE-per-row edge loading with direct SQL batch INSERT into AGE's internal PostgreSQL tables:
- `graph_loader.py` — added `_build_node_lookup()`, `build_all_lookups()`, `_get_edge_label_id()`, `load_edges_direct()`
  - Lookups: query AGE internal tables (`{graph}."Label"`) to build `{key_value → AGE id}` dicts for all 14 node labels
  - Edge IDs: generated via `(label_id::bigint << 48 | nextval('{graph}."LABEL_id_seq"'))::agtype`
  - Batch INSERT: `psycopg2.extras.execute_values()` with page_size=5000, chunks of 50K for progress reporting
  - Idempotency: DELETE FROM edge table before INSERT (skip with `--no-truncate`)
  - Kept existing Cypher MERGE methods for nodes (only ~130K+500 nodes, fast enough)
- `load.py` — restructured Phase 4: [4a] ref nodes, [4b] employee nodes, [4c] build lookups, [4d] all 12 edge types via direct SQL
  - IN_COUNTRY moved from separate step into unified edge loading loop
  - edge_configs simplified: no longer needs from_key_prop/to_key_prop columns (lookups are pre-built)
  - Checkpoint at edge-label level (not per-batch) since batch INSERT is fast enough

## Learnings
- For parallel batch tracking with `ThreadPoolExecutor` + `as_completed`, store completed batch *indices* (a set), not just a count — batches complete out of order
- Atomic file writes on Windows: `os.replace()` handles overwriting the target file (unlike `os.rename`)
- Flush-every-N-batches balances crash-recovery granularity vs. disk I/O overhead; 5 is a good default
- `TYPE_CHECKING` guard for checkpoint import avoids circular imports and keeps the module optional
- AGE internal tables: `{graph}."Label"` stores `id` (agtype bigint) and `properties` (agtype JSON). psycopg2 returns these as strings; parse with `int()` and `json.loads()`
- AGE ID encoding: `label_id << 48 | sequence_value`. Each label has its own sequence `"{Label}_id_seq"` in the graph schema
- `execute_values()` template parameter lets you embed SQL expressions (like `nextval()`) per-row while still using `%s` for parameterized values
- Cypher MERGE on edges is catastrophically slow at scale: one SQL round-trip per edge + pattern-matching lock contention crushes parallelism. Direct SQL INSERT bypasses the Cypher parser entirely
- For DELETE + INSERT idempotency, sequences continue from their last value (no reset needed) — AGE only cares about ID uniqueness, not specific values

### 2026-05-09 — Switched embeddings from sentence-transformers to Azure OpenAI
Replaced local `all-MiniLM-L6-v2` (384-dim) with Azure OpenAI `text-embedding-ada-002` (1536-dim):
- `embedding_generator.py` — `AzureOpenAI` client with `DefaultAzureCredential` + `get_bearer_token_provider`, batch API calls (100 texts/request), 3-retry exponential backoff, synthetic fallback preserved
- `config.py` (outer stub) — replaced `embedding_model`/`EMBEDDING_DIM(384)` with `azure_openai_endpoint`/`azure_openai_embedding_deployment`/`AZURE_OPENAI_EMBEDDING_DIMENSIONS(1536)` to match inner package config
- Inner package files (`talent_data_pipeline/talent_data_pipeline/`) were already updated — only the outer stubs needed fixing
- Dependencies already had `openai>=1.30.0` and `azure-identity>=1.16.0`; `sentence-transformers` no longer needed
- Decision logged to `.squad/decisions/inbox/brett-embeddings-azure-openai.md`

### Learnings (2026-05-09, embeddings)
- ada-002 doesn't support the `dimensions` parameter — only `embedding-3-*` models do. Must conditionally include it
- `get_bearer_token_provider` from `azure.identity` returns a callable that refreshes tokens automatically — cleaner than manually acquiring tokens
- Outer stub files in `talent_data_pipeline/generators/` (no `__init__.py`) are NOT part of the Python package — imports resolve to the inner `talent_data_pipeline/talent_data_pipeline/generators/` package. Keep both copies in sync to avoid confusion

### 2026-05-09 — Added checkpoint/resume to embedding GENERATION step
Added batch-level checkpointing to `EmbeddingGenerator.generate_embeddings()` so that completed Azure OpenAI API calls are saved to disk incrementally. On restart, cached batches are loaded from disk and their API calls are skipped.
- `embedding_generator.py` — new `_EMBEDDING_CHECKPOINT_DIR` at `talent_synthetic_data/.embedding_gen_checkpoint/`, per-batch `.npz` files with atomic writes (tempfile + os.replace), corrupt-file detection with auto-removal and re-generation
- `load.py` — `--reset` now also calls `EmbeddingGenerator.clear_checkpoint()`, and checkpoint dir is cleaned up after successful DB load of embeddings

### 2026-05-12 — Cross-agent: Bishop's infrastructure Pass 2
- **Bishop completed:** PostgreSQL Flexible Server (PG 16) with Entra ID-only auth, extensions allowlisted
- **For Brett:** Azure PostgreSQL is now provisioned. When `azd up` runs, data pipeline can connect via connection string from environment. Ensure migration code handles:
  - Entra ID token authentication (already supported via `DefaultAzureCredential`)
  - Extensions: `age`, `vector`, `pg_trgm`, `pg_stat_statements` — all allowlisted
  - VNet integration: Connection will be from Container Apps environment within the same VNet (delegated subnet `snet-db`)
- **Next:** Once Container App deployment is wired (Pass 3), the data pipeline will run as a job or init task within Azure
- Outer stub file kept in sync (3-level `_REPO_ROOT` vs 4-level in inner package)
- Same public interface preserved: `generate_embeddings(employees, skill_edges, batch_size)` returns `list[dict]`

### 2026-05-12 — Cross-agent: Bishop's infrastructure Pass 3 — PostgreSQL Entra ID auth for pipeline
**From Bishop (Deployment Engineer):**
- PostgreSQL deployment is now **Entra ID-only** — no SQL admin password.
- Data pipeline must authenticate using Entra ID tokens, NOT SQL passwords.
- **Action required for data pipeline:**
  1. When running locally (dev): Deploying user (Anil) is PostgreSQL Entra admin — local runs work automatically via `DefaultAzureCredential` + Azure CLI auth.
  2. When running in Azure (Container Apps Job/init task): Job's UAMI will be Entra admin → passwordless auth via `DefaultAzureCredential` + `AZURE_CLIENT_ID`.
  3. Update connection code: Construct Entra ID token and use as password in connection string (instead of `password=` from env var).
  4. Document this pattern in data pipeline README so future runs know to expect no password prompt.
- **Note:** Pipeline's outer stub (`config.py`) still has `PGPASSWORD` env var support for backward compat — but won't be used when connecting to Azure PostgreSQL. Token auth is mandatory.

### Learnings (2026-05-09, embedding checkpointing)
- `np.savez` auto-appends `.npz` to filenames that don't already end with it — use `.npz` suffix in `tempfile.mkstemp()` to avoid double extension
- `np.load(path, allow_pickle=False)` is safer for checkpoint files — embeddings are pure numeric arrays, no need for pickle
- Atomic writes on Windows: `tempfile.mkstemp()` + `os.close(fd)` + write + `os.replace()` — same pattern as `LoadCheckpoint._flush()`
- For 130K employees at batch_size=100, this saves ~1,300 `.npz` files (~1.5GB total) — acceptable tradeoff for crash resilience on ~2,600 API calls
