# Decisions

> Shared decision log. All agents read this before starting work.
> Only the Coordinator (via Scribe merge) writes here.

<!-- Decisions appear below, newest first. -->

### 2026-05-09: Backend API & Agent architecture — implemented
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Built complete FastAPI backend with OpenAI function-calling agent (9 tools), Entra ID JWT auth (dev-mode bypass via `TALENTIQ_AUTH_DISABLED=true`), NL chat endpoint (`/api/v1/chat`), structured search endpoints (`/api/v1/search/*`), health probes. Agent uses `DefaultAzureCredential` for Azure OpenAI auth. Lazy imports for data access layer — backend loads before Parker's layer exists. Lifespan manages DB pool + credential cleanup. 12 files across `talent_backend/talent_backend/`.
**Impact:** All agents: backend is runnable with `uvicorn talent_backend.main:app`. Parker's data access layer is imported lazily — no startup crash if missing.

### 2026-05-09: Data Access Layer — implemented
**By:** Parker (Data Engineer)
**Status:** Implemented
**What:** 8-module async data access layer at `talent_backend/talent_backend/data_access/`. Async psycopg3 pool with Entra ID token support, 10+ Pydantic v2 models, Cypher/SQL/Vector/FTS/Hybrid query functions. AGE Cypher safety via `_sanitize_identifier()`. Hybrid search normalises per-engine scores with configurable weights (0.3 graph, 0.3 vector, 0.2 FTS, 0.2 SQL).
**Impact:** Kane's API/agent layer calls these functions. All queries return typed Pydantic models. Vector search operates on 1536-dim embeddings.

### 2026-05-09: Checkpoint/resume for data loading pipeline — implemented
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Added `LoadCheckpoint` class with thread-safe batch tracking, atomic disk writes, per-phase status management. All loaders accept optional `checkpoint` parameter. Orchestrator creates checkpoint, passes to all loaders, supports `--reset` flag.
**Why:** Loading 130K employees + 2.6M edges to Azure PostgreSQL takes 7+ hours. Without checkpointing, crashes restart from scratch.

### 2026-05-09: Edge loading — Cypher MERGE → direct SQL batch INSERT
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Replaced per-row Cypher MERGE edge loading with direct SQL batch INSERT into AGE internal tables. `build_all_lookups()` queries AGE tables for ID dicts; `load_edges_direct()` uses `execute_values()` with page_size=5000. Node loading stays on Cypher MERGE. Performance: ~1 edge/sec → 10,000+ edges/sec.
**Impact:** Load pipeline uses new direct path automatically. Old Cypher method kept for backward compat but unused.

### 2026-05-09: Embeddings — sentence-transformers → Azure OpenAI ada-002
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Replaced local `all-MiniLM-L6-v2` (384-dim) with Azure OpenAI `text-embedding-ada-002` (1536-dim). Auth via `DefaultAzureCredential`. Batch size 100, 3 retries with exponential backoff. Deterministic synthetic fallback if Azure OpenAI unavailable.
**Impact:** Parker's vector search now operates on 1536-dim embeddings. Schema column already `vector(1536)`.

### 2026-05-09: Database query test strategy — implemented
**By:** Lambert (QA)
**Status:** Implemented
**What:** Live database testing (not mocks) — 7 test classes, 88 tests covering graph/FTS/vector/hybrid queries. Every test docstring references its user story ID. Coverage matrix at `docs/test-coverage-matrix.md`.
**Impact:** Tests require a running Azure PostgreSQL instance with loaded data. Session-scoped connection fixture.

### 2026-05-08T20:20: User directive — synthetic data location
**By:** Anil (via Copilot)
**What:** All synthetic data must be generated under `talent_synthetic_data/` at the repo root. Never write generated data files elsewhere.
**Why:** User request — captured for team memory

### 2026-05-08T20:10: User directive — talent_ prefix, centralized config, single root pyproject

**By:** Anil (via Copilot)  
**What:** Implementation folders must use `talent_` prefix (e.g., `talent_data_pipeline/`, `talent_backend/`). All code must load `.env` from `app_config/` — never create local `.env` files. A single `pyproject.toml` at the repo root manages all implementation folders as uv workspace members.  
**Why:** User request — captured for team memory

### 2026-05-08T19:55: User directive — uv sync only, no pip

**By:** Anil (via Copilot)  
**What:** All Python development must use `uv sync` in each code folder for dependency management. Never use `pip install` directly. Each code folder maintains its own `pyproject.toml`.  
**Why:** User request — captured for team memory

### 2026-05-08: Project restructuring — uv workspace, rename, centralized config

**By:** Brett (Data Generator & Loader)  
**Status:** Implemented  
**What:** Renamed `data_pipeline/` → `talent_data_pipeline/` (nested package layout). Updated all 15 Python imports. Aligned config.py env vars to `app_config/.env` (`PGHOST`, `PGPORT`, etc.). Created root `pyproject.toml` as uv workspace. Created `talent_backend/` skeleton for Kane. Deleted per-folder `.env.example`. `uv sync --all-packages` succeeds (47 packages).  
**Impact:**
- All agents: run `uv sync` from the repo root, not inside subfolders.
- All agents: credentials come from `app_config/.env` exclusively.
- Kane: `talent_backend/talent_backend/` is your code folder, `config.py` is ready.
- Parker: graph query code should import from `talent_data_pipeline.config` if needed.

### 2026-05-08: Data Pipeline Architecture — implemented

**By:** Brett (Data Generator & Loader)  
**Status:** Implemented  
**What:** Greenfield data pipeline under `data_pipeline/` — 18 Python files + 1 SQL + pyproject.toml. Covers 130K employees, 2.6M edges, vector embeddings, FTS indexes. Key choices: psycopg2 + ThreadedConnectionPool over asyncpg, Cypher MERGE for idempotency, DiskANN→HNSW fallback at runtime, Faker locale-per-country for culturally appropriate names, hardcoded reference data (46 locations, 96 skills, 39 certs) for ontology fidelity.  
**Impact:** Parker should use `properties->>'key'` index pattern for graph queries. Kane should use `employee_fts` and `employee_embeddings` relational tables as the search API interface.

### 2026-05-08: Requirements decomposition — fresh start

**By:** Ash (Scrum Master)  
**What:** Complete fresh requirements decomposition from source CSVs. 72 files: 1 product spec, 1 backlog, 1 traceability matrix, 17 epics, 52 user stories. 30 of 48 features.csv entries identified as gaps needing backlog grooming.  
**Why:** Clean decomposition from scratch for TalentIQ v2 platform.  
**Impact:** All team members should use `docs/` as the canonical requirements source.
