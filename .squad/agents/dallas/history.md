# Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Created:** 2026-05-08

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-05-09: Full React/Vite frontend scaffolded
- **Location:** `talent_ui/` at repo root
- **Stack:** React 18, Vite 6, MSAL React (Entra ID auth), react-markdown + remark-gfm, recharts (charts), Application Insights telemetry
- **Key files:**
  - `talent_ui/src/App.jsx` — Main SPA component (chat, sidebar, run log, auth, SSE streaming)
  - `talent_ui/src/App.css` — Full dark theme CSS, brand accent #E8845A
  - `talent_ui/src/authConfig.js` — MSAL config using `VITE_*` env vars
  - `talent_ui/src/ChartView.jsx` — Markdown table → recharts bar/line charts
  - `talent_ui/src/telemetry.js` — App Insights wrapper (graceful degradation if unconfigured)
  - `talent_ui/src/main.jsx` — React root with MsalProvider
  - `talent_ui/vite.config.js` — Proxy `/af` → `http://localhost:8000`
  - `talent_ui/.env.example` — All env vars documented
- **Env var pattern:** Vite uses `import.meta.env.VITE_*` (not `process.env.REACT_APP_*`)
- **Backends:** Currently one: "graph-search". AF backend code is present but not listed in the selector array.
- **Run log panel:** Right side panel, only shown for graph-search backend. Streams orchestrator/agent/query/result events via NDJSON SSE.
- **CSS:** ~700 lines. All class names from the reference are implemented. Dark theme with CSS custom properties for easy theming.

### 2026-05-09: Entra ID auth wired end-to-end
- MSAL config at `talent_ui/src/authConfig.js` — clientId, tenant, scope hardcoded for dev
- All API calls (graph-search, agent-framework, default) include `Authorization: Bearer <token>` acquired via MSAL
- Scope: `https://ai.azure.com/user_impersonation`, SPA redirect: `http://localhost:5173`
- Production: replace hardcoded values with `VITE_*` env vars

### 2026-05-09: FAQ sidebar expanded to 15 categories / 35 questions
- Went from 7→15 categories, 21→35 questions
- New categories: Data Provenance, Resume & CV Generation, Export & Reporting, Notifications & Reminders, Tender & RFP, Candidate Management, Pre-Sales & CPQ
- Each category annotated with US-xxx user story references for traceability
- FAQ array lives in `talent_ui/src/App.jsx`

### 2026-05-09: Backend NDJSON streaming integration
- Backend exposes `POST /af/graph/responses` — streams NDJSON events
- Vite proxy rule: `/af` → `http://localhost:8000` (route already includes `/af`)
- Frontend run-log panel parses `response_message` wrappers for orchestrator/agent/query/result events

### 2026-05-09 — Entra ID token audience & issuer learnings
- MSAL authConfig hardcoded: clientId `48449491-8390-4af0-8121-da7af091ad56`, tenant `150305b3-cc4b-46dd-9912-425678db1498`, scope `https://ai.azure.com/user_impersonation`. SPA redirect `http://localhost:5173`.
- When `user_impersonation` scope is used, the Bearer token audience will be `https://ai.azure.com`, NOT the app client ID. Backend must be configured to accept this.

### 2026-05-12: Cross-agent — Bishop's infrastructure scaffolding complete
- **Bishop completed:** VNet 10.0.0.0/16, single CAE with Consumption profile, private DNS zones, naming convention established.
- **Dallas action:** Frontend deployment hooks coming — configure Container App environment, ingress.external: true, app service plan. Files: `talent_infra/main.bicep`, `talent_infra/modules/container-app-env.bicep`.

### 2026-05-10: Session ID fix — graph response handler
- Critical bug: `callGraphBackendApi` processed `msg.type === "done"` but never stored `msg.session_id` → every request created a new session
- Fix: `if (msg.session_id) setAfSessionId(msg.session_id)` in the done handler
- The SSE handler (`callAfBackendApi`) already did this correctly

### 2026-05-10: Run log panel enhancements  
- RunLogBlock now parses `[QUERY] CYPHER:`, `[QUERY] SQL:`, `[QUERY] FTS:`, `[QUERY] VECTOR:` prefixes into specific badge labels
- SQL/Cypher entries render in `<code>` blocks for readability
- `[HANDOFF]` messages classified as new "handoff" kind with purple styling
- ReactMarkdown `table` component override wraps tables in scrollable `<div className="table-wrapper">`
- Assistant bubbles expanded to `max-width: 90%` for wide tables

### 2026-05-10: File upload flow
- After upload, auto-send with original user question from chat history (not hardcoded message)
- `sendMessage` already attaches `uploadedFile` as `file_context`
- Removed hardcoded template selector UI — CV template selection is agent-driven

### 2026-05-10: Technical specs — SSE/Auth and Production Agentic UI
- Wrote `docs/specs/ui-sse-auth.md` — documents current SSE streaming (NDJSON for graph-search, SSE for agent-framework), token lifecycle, state management (19 useState vars), and API client patterns. Key gaps: no AbortController, no proactive token refresh, no auto-retry on 401.
- Wrote `docs/specs/ui-agentic-production.md` — future vision for multi-agent visibility, structured tool execution views, shortlist management, dashboards, i18n (ES/EN/FR/PT), WCAG 2.1 AA, Fluent UI v9 alignment, responsive breakpoints, performance budgets.
- Key architectural decisions documented: POST-based SSE (not EventSource) is correct because we need POST bodies with auth headers; `localStorage` recommended for prod token cache (cross-tab SSO); WebSocket not needed until server-initiated notifications are required; Fluent UI adds ~80-100KB but covers accessibility out of the box.
- Migration roadmap: 4 phases from production hardening (AbortController, token refresh) through agentic workspace (agent cards, dashboards, i18n) to performance (virtual scrolling, service worker).

### 2026-05-10: Cross-agent — Tech spec decisions affecting Dallas
- **Ripley:** Structured JSON logging with OTel correlation — frontend App Insights already correct, add `session_id` correlation.
- **Kane:** RBAC via Entra ID app roles — no immediate frontend changes (token already contains roles claim). Session migration via `SESSION_PROVIDER` flag — no frontend impact.
- **Parker:** No direct frontend impact from DB architecture spec.

### 2026-05-12 — Cross-agent: Bishop's infrastructure Pass 3 — Container App deployment
**From Bishop (Deployment Engineer):**
- Frontend Container App is now provisioned with User-Assigned Managed Identity (UAMI). Ingress is **external** (public, port 80).
- Frontend env vars:
  - `BACKEND_URL` — internal FQDN to backend Container App (e.g., `http://backend-ca.xxx.azurecontainerapps.io:8000`). Use to proxy API calls.
  - `KEY_VAULT_URI` — if frontend needs to fetch secrets (e.g., telemetry config).
  - `APPLICATIONINSIGHTS_CONNECTION_STRING` — send telemetry to Application Insights.
  - `AZURE_CLIENT_ID` — UAMI client ID for `DefaultAzureCredential` (may be needed if frontend calls Azure services directly).
- **Action required:** Create `Dockerfile` under `talent_ui/` that builds Vite production bundle and serves via HTTP server on port 80, update frontend to read `BACKEND_URL` from env (not hardcoded), update proxy rules in dev (`vite.config.js`), ensure telemetry sends to injected connection string.
- **Deployment flow:** `azd up` provisions Container App. `azd deploy` builds Vite bundle inside Docker image and pushes to ACR. Frontend starts on port 80.
