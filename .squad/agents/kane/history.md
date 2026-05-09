# Project Context

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

<!-- Append new learnings below. Each entry is something lasting about the project. -->
