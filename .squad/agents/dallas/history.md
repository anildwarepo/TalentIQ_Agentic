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
