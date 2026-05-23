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

### 2026-05-12T02:00:00Z: Cross-agent — Full deployment stack now in place
- **Bishop:** 8-section azd-up.md runbook (~420 lines, mermaid flowchart). Infrastructure passes 1-3 complete: VNet + data/AI services + Container Apps with UAMI. Fixed azure.yaml to route Dockerfile.mcp to MCP service.
- **Kane:** Backend + MCP dockerfiles (multi-stage), centralized azure_clients.py for credential lifecycle, refactored auth/vector/chat layers to use singletons.
- **Dallas:** Frontend dockerfile (multi-stage nginx), nginx.conf with SSE streaming support, runtime env injection pattern (config.js.template + envsubst).
- **Brett:** Data pipeline dual-mode auth (db.py with token caching), now works against both local PG (password) and Azure PG (Entra token).
- **Ripley pending:** Architecture review of full deployment stack (infra + containerization + auth). Confirm readiness for `azd up && azd deploy` cycle. Test containerization end-to-end (health probes, log streaming, RBAC verification).

### 2026-05-21: `talent_infra_modules/` — per-component deployment toolkit architected
- **Why this exists:** Need a path to deploy ONLY the app tier (PG, backend+MCP, frontend, data loading) into an environment where RG / VNet+subnets / ACA env / ACR / Foundry already exist. `talent_infra_v2/` is azd-orchestrated and assumes greenfield. Per-component PowerShell scripts iterate faster than full Bicep redeploys and don't need an azd environment.
- **Design pattern:** Four independent component folders (`01-postgresql`, `02-backend`, `03-frontend`, `04-data-loading`) each owning a `deploy.ps1` + `infra/main.bicep` + `infra/main.parameters.json` + emitting a `.outputs.json`. State hand-off is **file-based** between folders. No azd, no environment store.
- **Auth-disable contract (demo mode default):** Backend = **omit** `AZURE_TENANT_ID` env var (auth.py lines 86-90 short-circuit). Frontend = **`VITE_DISABLE_AUTH=true`** Docker build arg. UI code change (gate `<MsalProvider>` and `useIsAuthenticated()` on the flag) is **Dallas's job** — scripts assume it's merged. AUTH-DISABLED.md documents the contract end-to-end.
- **Shared infrastructure (`shared/common.ps1`):** Single dot-source point. Functions: `Write-Step/Success/Warn/Fail/Info`, `Invoke-Native` (azure CLI wrapper that fails fast on non-zero), `Test-AzLoggedIn`/`Test-AzSubscription`, `Get-ParameterValue` (layered Value→EnvVar→Prompt→Default with `-Secure` support), `Test-ResourceExists` (with typeMap aliases vnet/containerappenv/containerapp/acr/postgres/foundry/cosmos/keyvault/uami), `Test-VnetSubnetExists`, `Test-FoundryProject`, `Get-AcrLoginServer`, `Confirm-Action` (auto-yes on `-Force` or `$env:CI`), `Assert-PrerequisitesExist` (bulk hashtable verifier — called FIRST in every deploy.ps1).
- **Lessons baked into READMEs for Bishop:** (a) UAMI-as-PG-role control-plane fallback — display name MUST equal UAMI name. (b) AGE preload requires PG restart — check `[?isConfigPendingRestart]`. (c) MCP-as-sidecar uses **backend UAMI** as PGUSER (`<backend-app-name>-identity`), not a separate identity. Backend reaches MCP via `http://localhost:3002/mcp`. (d) PG flex serializes control-plane ops via `dependsOn`: `server → azureExtensions → sharedPreloadLibraries → entraAdministrator → firewallRules`. (e) Cognitive Services ETag race: `modelDeployment dependsOn aiProject`. (f) Container App revision restart after PG state changes via `az containerapp revision restart --revision <active>`. (g) PowerShell quoting hazard: avoid nested `az containerapp exec → python -c "..."`; use control-plane operations only.
- **Outputs hand-off chain:** `01-postgresql/.outputs.json` → consumed by `02-backend` + `04-data-loading`. `02-backend/.outputs.json` → consumed by `03-frontend` + optionally `04-data-loading` (for narrowing UAMI grants). DEPLOYMENT-ORDER.md documents the full flow + skip patterns.
- **Boundary with `talent_infra_v2/`:** v2 is the production-shape, full-stack, MSAL-on, azd-orchestrated deployment. This new toolkit is the demo-shape, app-tier-only, auth-off, script-orchestrated deployment. README.md compares them side-by-side so future agents pick the right one.
- **Hand-off to Bishop:** 4 deploy.ps1 scripts + 3 bicep templates (no bicep for `04-data-loading` — pure local python invocation). Bishop's contract is the per-folder README.md — inputs, outputs schema, prerequisites, deployment lessons. All architectural decisions are locked.

## Cross-agent note — 2026-05-21 (Scribe)
- **Architecture pass succeeded.** All 4 Bishop spawns (01-postgresql, 02-backend, 03-frontend, 04-data-loading) plus the Dallas UI bypass landed without architectural drift from the contract documented in `talent_infra_modules/{README,AUTH-DISABLED,DEPLOYMENT-ORDER}.md`. The single "silent success" on Bishop 03-frontend produced complete on-disk artifacts (deploy.ps1, infra/main.bicep, parameters file, copied container-app.bicep with no sidecar).
- **Lambert verdict: APPROVED — ship as-is.** All 6 hazards from `/memories/repo/talentiq-azd-deploy.md` covered; all `.bicep` files compile; all `.ps1` files parse zero errors; `.outputs.json` schema consistent across folder boundaries. Three WARN-level cosmetic findings logged but non-blocking. No Reviewer Rejection Protocol invoked.

## Cross-agent note — 2026-05-22 (Scribe)
- **PE-bearing `talent_infra_modules/*/deploy.ps1` scripts now have a normative self-heal pattern for stale `privateDnsZoneGroup` resources.** Bishop shipped `-FixStaleDnsZoneGroup` (umbrella `-Force` implies it) on `01-postgresql/deploy.ps1` 2026-05-22T18:00:00Z. Azure forbids in-place mutation of `privateDnsZoneConfigs[*].properties.privateDnsZoneId` with `UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed` — the only fix is to delete the stale zone group and let Bicep recreate it pointing at the canonical zone discovered via the 2026-05-22T12:30:00Z discover-and-reuse helpers. Read-only detection runs every deploy; the destructive action is gated behind explicit operator opt-in.
- **Architecture implication for future PE-bearing modules in `talent_infra_modules/`:** Any new component that creates an Azure Private Endpoint — Cosmos, Foundry/CogServices, Key Vault, ACR, or internal-ingress ACA env — MUST adopt the four-step pattern (detect → surface in plan summary → act gated → optional same-RG empty-and-unlinked orphan-zone cleanup) and MUST expose `[switch]$FixStaleDnsZoneGroup` with `-Force` implication. No env-var binding by default. README must show the new switch in the Inputs table. See `.squad/decisions.md` (2026-05-22T18:00:00Z) for the normative spec and `.squad/skills/azure-pe-dns-zone-group-self-heal/SKILL.md` for the reusable PowerShell template. The Bicep surface is intentionally untouched — this lives in the deploy script because the constraint is enforced at the Network RP layer, not in the template.

## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Bishop deploy.ps1 sweep follow-up.** Two additional `01-postgresql/deploy.ps1` bugs fixed (2026-05-22T22:00:00Z Section 7c DNS stale-list trap; 2026-05-22T22:15:00Z Section 8 `az deployment group create` `2>&1` JSON-capture stream pollution). Both are reusable patterns: (a) gate DNS link cleanup on `record-set list` (counters lag the RP); (b) separate stderr to per-run log file when capturing `az ... --output json` (never `2>&1`). Lambert should sweep `talent_infra_modules/{00,02,03,04}/deploy.ps1` for the same `2>&1` JSON-capture idiom. Architectural awareness for future PE modules: list/count endpoints lag the RP — only named-delete attempts are authoritative. See decisions.md `2026-05-22T22:20:00Z` for the normative pattern. **Model directive (2026-05-22):** all future squad spawns (including Scribe/Ralph) use `claude-opus-4.6-1m` per `.squad/config.json` `defaultModel`. Coordinator must pass `model: "claude-opus-4.6-1m"` on every spawn until Anil changes it.


## Team update — 2026-05-22T23:59:30Z (via Scribe, originated by Bishop)

Team-wide rule from GitGuardian remediation on `talent_infra_modules/01-postgresql/deploy.ps1`: **no literal secrets in `.EXAMPLE` / docstring / sample-code blocks** — use `Read-Host -AsSecureString` or an angle-bracket `<placeholder>`. Scanners regex on shape, not intent; a plausible-looking literal in a help comment is functionally a leak. Applies to any sample code you emit (Python docstrings, JS examples, README snippets, agent prompts), not just PowerShell.

## Team update — 2026-05-22T23:59:59Z (via Scribe, originated by Bishop)

Architectural guardrail (decisions.md `2026-05-22T23:59:59Z`): **all `.ps1` files in this repo MUST be UTF-8 with BOM.** Cross-VM PS 5.1 parser-cascade failure (em-dash in BOM-less UTF-8 → CP1252 mojibake → quoted-string break → 30+ misleading errors) just hit Bishop's `talent_infra_modules\01-postgresql\deploy.ps1`. One file fixed; 11 sibling `.ps1` files identified with the same latent bug and deferred. Apply when reviewing any new infra module or PS-based tooling — `shared/common.ps1` is the cross-cutting hazard since every component deploy.ps1 sources it.

## Cross-agent note — 2026-05-23T00:30:00Z (Scribe, from Bishop)

- **11-file `.ps1` UTF-8-with-BOM sweep COMPLETE** — the architectural guardrail from `2026-05-22T23:59:59Z` is now fully enforced across `talent_infra_modules/`, `talent_infra/hooks/`, and `talent_infra_v2/hooks/`. Bishop also landed `.editorconfig` (root=true; `[*.ps1]` charset=utf-8-bom, end_of_line=crlf, insert_final_newline=true) plus `.vscode/settings.json` (`"[powershell]": { "files.encoding": "utf8bom" }`) prevention guards at the repo root, so new `.ps1` files will save with BOM automatically. Two BOM-less files still flagged for a future cleanup pass: `.squad/templates/skills/distributed-mesh/sync-mesh.ps1` and `talent_infra_v2/scripts/Purge-SoftDeletedFoundryAccounts.ps1`. Per `decisions.md 2026-05-23T00:30:00Z`.