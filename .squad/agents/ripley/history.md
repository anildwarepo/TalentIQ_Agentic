# Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Created:** 2026-05-08

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-05-10: Technical specification documents authored
- **Backend Architecture:** Documented the three-service topology (FastAPI + MCP + SPA), SSE/NDJSON dual streaming protocol, agent-as-tool handoff pattern, and MCP client/server boundary. Key decision: co-host backend API and MCP server on localhost in production (single App Service) — only separate when scaling demands it.
- **VNet Integration:** 4-subnet VNet design (app, private endpoints, DB delegated, egress). PostgreSQL Flexible Server uses delegated subnet (not PE). NAT Gateway for egress, not Azure Firewall (cost). Private DNS Zones for all PaaS. Migration is 4 phases over 4 weeks. Incremental cost ~$75-100/mo.
- **Telemetry:** Backend has zero observability today — critical gap. OpenTelemetry SDK with Azure Monitor exporter is the path. Custom spans at orchestrator/handoff/MCP/DB layers. Token usage tracking for cost visibility. Three workbooks (ops, AI cost, DB perf). Structured logging with correlation IDs.
- **Pattern:** Always document Current State → Target State → Migration Path. Makes specs actionable, not aspirational.
- **Architecture principle:** MCP server stays internal (localhost or VNet-internal FQDN). Never expose MCP to public Internet.

### 2026-05-11: Workday Integration specification authored
- **Spec:** `docs/specs/workday-integration.md` — master spec for Workday → Graph DB ingestion pipeline.
- **Key decisions:** Container Apps Jobs for scheduling (no timeout limits, same VNet), RaaS for bulk extraction + REST API for CV docs, delta reports via date-range filter for incremental sync (webhooks deferred to Phase 4), soft delete for terminated employees, dual-graph swap for zero-downtime full loads.
- **Data mapping:** Complete field-by-field mapping for all 14 node labels and 12 edge types. Workday Management Level → job_level integer mapping. CEFR proficiency derivation from Workday language scale. EQF/MECES derivation from degree type.
- **Migration:** 4-phase rollout over ~5 weeks. Synthetic pipeline kept as permanent fallback via `WORKDAY_ENABLED` feature flag. Phase 1 against Workday sandbox, Phase 3 production cutover with rollback plan.
- **Security:** Workday ISU credentials in Key Vault (never in env vars), managed identity for DB and Blob, NAT Gateway static IP for Workday IP allowlist, CV storage in private-endpoint Blob Storage.
- **New components:** WorkdayClient, WorkdayTransformer, CVExtractor, PipelineOrchestrator, WorkdayConfig. Existing loaders (Graph, Vector, FTS) extended with delta upsert.
- **Pattern confirmed:** Feature flags for data source switching (`WORKDAY_ENABLED`, `WORKDAY_SYNC_MODE`) — same approach as Kane's `SESSION_PROVIDER` pattern.

### 2026-05-10: Cross-agent — Team tech spec decisions
- **Kane:** Session management migration via `SESSION_PROVIDER` feature flag, RBAC via Entra ID app roles, JWKS retry on key rotation, shared HistoryProvider across agents.
- **Dallas:** SSE POST+ReadableStream confirmed correct, localStorage token cache for production, AbortController needed, Fluent UI v9 + i18n targeted for Phase 3.
- **Parker:** 3 production gaps in DB layer — `search_graph_nodes()` function missing, `employee_ageid` always 0, `pg_trgm` extension availability on Azure.

### 2026-05-12: Cross-agent — Bishop's infrastructure scaffolding complete
- **Bishop completed:** VNet 10.0.0.0/16 with 3 delegated subnets (ACA, private endpoints, DB). Single CAE with Consumption workload profile. Private DNS zones + naming convention.
- **Ripley action:** Review VNet subnet allocation, CIDR delegation choices for scalability. Decisions documented in `.squad/decisions.md` — "VNet CIDR Plan 10.0.0.0/16".
