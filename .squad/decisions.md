# Decisions

> Shared decision log. All agents read this before starting work.
> Only the Coordinator (via Scribe merge) writes here.

<!-- Decisions appear below, newest first. -->

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
