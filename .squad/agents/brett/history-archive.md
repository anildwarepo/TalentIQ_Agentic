# Brett — History Archive

> Archived 2026-05-16 by Scribe. Entries from 2026-05-08 and 2026-05-09 work log moved here after history.md exceeded 15KB threshold.

## Work Log (Archived)

### 2026-05-08 — Built complete data pipeline (greenfield)
Built `data_pipeline/` from scratch — 18 Python files across 4 packages: config, connectivity_test, main, validate, schema/ (graph labels, relational tables, indexes), generators/ (reference data, 130K employees, 12 edge types, resume summaries, embeddings), loaders/ (graph/vector/FTS).

### 2026-05-08 — Project restructuring: rename, uv workspace, centralized config
Renamed `data_pipeline/` → `talent_data_pipeline/` with nested package layout. Updated 15 imports. Aligned env vars to `app_config/.env`. Created root pyproject.toml as uv workspace. Created `talent_backend/` skeleton.

### 2026-05-09 — Added checkpoint/resume to data loading pipeline
`LoadCheckpoint` class: thread-safe, atomic disk writes, per-phase status, per-batch completion tracking. Wired through all loaders. Checkpoint at `talent_synthetic_data/.load_checkpoint.json`. `--reset` flag for fresh load.

### 2026-05-09 — Rewrote edge loader: Cypher MERGE → direct SQL batch INSERT
Direct SQL INSERT into AGE internal tables. `build_all_lookups()` for ID dicts, `execute_values()` with page_size=5000. Performance: ~1 edge/sec → 10,000+ edges/sec. Node loading stays on Cypher MERGE.

### 2026-05-09 — Switched embeddings from sentence-transformers to Azure OpenAI
Replaced `all-MiniLM-L6-v2` (384-dim) with `text-embedding-ada-002` (1536-dim). Azure OpenAI batch API calls (100 texts/request), 3-retry exponential backoff, synthetic fallback preserved.

### 2026-05-09 — Added checkpoint/resume to embedding GENERATION step
Batch-level checkpointing for `EmbeddingGenerator.generate_embeddings()`. Per-batch `.npz` files with atomic writes. Corrupt-file detection with auto-removal. Cleaned up after successful DB load.

### 2026-05-12 — Cross-agent: Bishop's infrastructure Passes 2 & 3
PostgreSQL provisioned with Entra ID-only auth. Extensions allowlisted. Pipeline must authenticate using Entra ID tokens. Outer stub file kept in sync.

### Archived Learnings (2026-05-08 through 2026-05-09)
- AGE labels: `ag_catalog.create_vlabel`/`create_elabel`, not DDL
- DiskANN extension: try `vectorscale` → `pg_diskann` → HNSW fallback
- AGE internal tables: `{graph}."Label"` stores id (agtype bigint) + properties (agtype JSON)
- AGE ID encoding: `label_id << 48 | sequence_value`
- Cypher MERGE catastrophically slow for edges at scale; direct SQL INSERT bypasses Cypher parser
- `execute_values()` template supports SQL expressions per-row
- Faker locales for culturally appropriate names (sr_RS, vi_VN, bg_BG, es_MX)
- Hatchling editable installs fail with source remapping — use nested package layout
- Centralized .env path: `Path(__file__).resolve().parent.parent.parent / "app_config" / ".env"`
- `ThreadPoolExecutor` + `as_completed`: track completed batch *indices* (set), not count
- Atomic file writes on Windows: `os.replace()` handles overwriting
- ada-002 doesn't support `dimensions` parameter — only embedding-3-* models do
- `get_bearer_token_provider` from azure.identity returns auto-refreshing callable
- `np.savez` auto-appends `.npz` — use `.npz` suffix in `tempfile.mkstemp()`
