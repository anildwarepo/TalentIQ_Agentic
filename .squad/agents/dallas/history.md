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

### 2026-05-15 — Cross-agent: Kane's thread management endpoints are live
**From Kane (Backend Dev):**
- The 4 thread endpoints the frontend is already calling now exist and return real data:
  - `GET /api/threads?limit=20` — list user's threads
  - `GET /api/threads/{id}` — get thread messages
  - `DELETE /api/threads/{id}` — soft delete thread
  - `PATCH /api/threads/{id}` — rename thread (body: `{"title": "..."}`)
- CORS updated to allow `DELETE` and `PATCH` methods.
- Legacy `/api/sessions/*` endpoints still work but frontend should migrate to `/api/threads/*`.
- **No frontend changes needed** — endpoints match what App.jsx already calls.
- 16 tests passing (Lambert).

### 2026-05-21: `VITE_DISABLE_AUTH` build-time MSAL bypass for demo deployments
- **Why:** `talent_infra_modules/` deploys to environments where an Entra SPA app registration cannot be provisioned. Backend `auth.py` already short-circuits to a synthetic `dev-user` when `AZURE_TENANT_ID` is unset; this is the matching frontend half so the UI doesn't get stuck on the sign-in card.
- **Flag:** `VITE_DISABLE_AUTH=true` (Docker build arg, inlined by Vite as a literal — cannot be flipped at runtime). Default is `"false"` → production MSAL behavior unchanged.
- **Files touched (5, all under `talent_ui/`):**
  - `Dockerfile` — added `ARG`/`ENV` for `VITE_DISABLE_AUTH`, `VITE_API_BASE`, `VITE_AF_BACKEND_URL`, `VITE_AGENT_NAME` (matching the build args `03-frontend/deploy.ps1` passes).
  - `src/authConfig.js` — `msalConfig` now exports `null` when disabled; hardcoded clientId/authority/redirectUri replaced with `VITE_MSAL_*` env-var lookups + the existing dev values as fallback.
  - `src/main.jsx` — branched: AUTH_DISABLED renders `<App />` bare, else wraps in `<MsalProvider instance={msalInstance}>` exactly as before. `PublicClientApplication` is only constructed in the production branch (no console errors about missing clientId).
  - `src/App.jsx` — module-level `const AUTH_DISABLED = import.meta.env.VITE_DISABLE_AUTH === "true";` + `DEMO_ACCOUNT` constant. Conditional hook calls (`useMsal`, `useIsAuthenticated`) with `eslint-disable-next-line react-hooks/rules-of-hooks` — safe because Vite inlines the constant at build time so dead-code elimination makes the hook call pattern consistent per build. `getToken` short-circuits to `null`; `logout` becomes a local-state clear; every `if (!token) return` bail-out gated with `&& !AUTH_DISABLED`; every direct `Authorization: Bearer ${token}` header replaced with `AUTH_DISABLED ? {} : {...}` (handleFileUpload, default `/chat` path, loadThreads, loadThread); the `loadThreads` effect fires on `isAuthenticated && (accessToken || AUTH_DISABLED)`.
  - `.env.example` — documented `VITE_DISABLE_AUTH=false`.
- **How to undo when a future env gets MSAL:** set `VITE_DISABLE_AUTH=false` (or unset) at Docker build time, supply the four `VITE_MSAL_*` env vars per `.env.example`, rebuild and push. No source changes needed.
- **Contract with Bishop's `talent_infra_modules/03-frontend/`:** the flag name and the `"true"` string match `AUTH-DISABLED.md` exactly. If that doc changes, this code must follow.

## Cross-agent note — 2026-05-21 (Scribe)
- **Auth-disable contract is a two-agent deliverable.** Dallas owns the React source change (conditional `<MsalProvider>`, suppressed bearer header, synthetic demo account in `talent_ui/`); Bishop owns the Container App env-vars + deploy scripts (omits `AZURE_TENANT_ID` on backend; passes `VITE_DISABLE_AUTH=true` to the frontend Docker build). Both halves must move together to deliver the "auth-off demo deploy" promised by `talent_infra_modules/AUTH-DISABLED.md`. Changing the contract requires coordinated edits across both surfaces — never one in isolation.
