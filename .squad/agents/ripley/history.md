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

### 2026-05-10: Cross-agent — Team tech spec decisions
- **Kane:** Session management migration via `SESSION_PROVIDER` feature flag, RBAC via Entra ID app roles, JWKS retry on key rotation, shared HistoryProvider across agents.
- **Dallas:** SSE POST+ReadableStream confirmed correct, localStorage token cache for production, AbortController needed, Fluent UI v9 + i18n targeted for Phase 3.
- **Parker:** 3 production gaps in DB layer — `search_graph_nodes()` function missing, `employee_ageid` always 0, `pg_trgm` extension availability on Azure.
