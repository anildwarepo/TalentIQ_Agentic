# Production Agentic UI Spec (Future)

> **Version:** 1.0  
> **Date:** 2026-05-10  
> **Author:** Dallas (Frontend Dev)  
> **Status:** Target-state specification for production readiness

---

## 1. Vision

TalentIQ is currently a **chat-only** interface — a single text input, streaming responses, and a run log panel. This works for the internal pilot but is insufficient for production.

The target is a **full agentic workspace** where:
- Multiple agents are visible and their work is observable
- Users can manage conversations, shortlists, and exports without leaving the UI
- The interface supports accessibility, localization, and mobile form factors
- Performance and reliability meet enterprise standards

This spec defines the "north star" UI and the incremental path to get there.

---

## 2. Agentic UI Patterns

### 2.1 Current State

```
┌──────────────────────────────────────────────────────────┐
│  Sidebar         │  Chat                    │  Run Log   │
│  ├── FAQ cats    │  ├── Message bubbles     │  ├── Run 1 │
│  ├── History     │  ├── Typing indicator    │  ├── Run 2 │
│  └── User       │  └── Input bar           │  └── Run 3 │
└──────────────────────────────────────────────────────────┘
```

**What works:**
- Run log shows agent activity with typed badges (CYPHER, FTS, VECTOR, HANDOFF, ORCH)
- MCP tool approval dialog pauses the workflow for user consent
- OAuth consent flow for external MCP tools
- Real-time streaming with per-message elapsed time

**What's missing:**
- No visibility into *which* agent is active (orchestrator? search agent? CV agent?)
- No reasoning/thinking traces — only final outputs and query logs
- Run log is append-only text — no structured tool execution view
- No way to inspect intermediate agent decisions

### 2.2 Target State

#### 2.2.1 Multi-Agent Visibility

```
┌─────────────────────────────────────────────────────────────────┐
│  Chat Message                                                    │
│                                                                  │
│  🤖 TalentIQ Orchestrator                                       │
│  "I'll search for Java developers and check their bench status" │
│                                                                  │
│  ┌─ Agent: Search Agent ──────────────────────────────────────┐ │
│  │  🔍 Running CYPHER query...                                │ │
│  │  ✅ Found 12 candidates                                    │ │
│  │  📊 Scoring by skills match + availability                 │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ Agent: Bench Analyst ─────────────────────────────────────┐ │
│  │  ⏳ Checking bench status for 12 candidates...             │ │
│  │  ✅ 4 on bench, 8 allocated                                │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Here are the top 5 Java developers in Spain...                 │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation approach:**

The backend already emits `OrchestratorEvent`, `AgentEvent`, and `HandoffEvent` types. We need to:

1. **Parse agent identity** from event deltas — currently agents are anonymous in the stream.
2. **Group events by agent** in the UI — each agent gets a collapsible card within the message.
3. **Show handoff indicators** — "Routing to CV Generation Agent" with an arrow animation.

**Proposed SSE event enhancement:**

```jsonl
{"response_message": {"type": "AgentEvent", "agent": "search-agent", "delta": "[QUERY] CYPHER: ..."}}
{"response_message": {"type": "HandoffEvent", "from": "orchestrator", "to": "search-agent"}}
```

Adding an `agent` field lets the UI group and label events without parsing text content.

#### 2.2.2 Agent Thinking/Reasoning Display

```jsx
// Expandable reasoning trace within a message bubble
<div className="agent-reasoning">
  <button className="reasoning-toggle" onClick={toggle}>
    {expanded ? "▼" : "▶"} Agent reasoning (3 steps)
  </button>
  {expanded && (
    <div className="reasoning-steps">
      <div className="step">
        <span className="step-num">1</span>
        <span>User wants Java developers in Spain → search by skill + location</span>
      </div>
      <div className="step">
        <span className="step-num">2</span>
        <span>Also checking bench status per the "bench-first" policy</span>
      </div>
      <div className="step">
        <span className="step-num">3</span>
        <span>Scoring: 40% skills, 20% availability, 20% location, 20% bench priority</span>
      </div>
    </div>
  )}
</div>
```

**Backend requirement:** Emit a new event type `ReasoningEvent` with the agent's chain-of-thought. This is optional and should be toggleable (debug mode).

#### 2.2.3 Tool Execution Visualization

Replace the text-based run log with a structured tool execution view:

```
┌─ Tool: cypher_query ───────────────────────────┐
│  Status: ✅ Complete (1.2s)                     │
│  Input:                                         │
│    MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)  │
│    WHERE s.name =~ '(?i).*java.*'              │
│    RETURN e.name, e.location LIMIT 20          │
│  Output:                                        │
│    12 rows returned                             │
│    ┌──────────────┬───────────┐                 │
│    │ Name         │ Location  │                 │
│    ├──────────────┼───────────┤                 │
│    │ Carlos Lopez │ Madrid    │                 │
│    │ ...          │ ...       │                 │
│    └──────────────┴───────────┘                 │
└─────────────────────────────────────────────────┘
```

This requires structured tool call/result events (not just text deltas):

```jsonl
{"response_message": {"type": "ToolCallEvent", "tool": "cypher_query", "args": {"query": "MATCH ..."}}}
{"response_message": {"type": "ToolResultEvent", "tool": "cypher_query", "result": {"rows": 12}, "duration_ms": 1200}}
```

#### 2.2.4 Approval Workflows

**Current:** `ApprovalDialog` component in [App.jsx](../../talent_ui/src/App.jsx) — shows server label, tool name, arguments. User clicks "Approve All" or "Deny".

**Target enhancements:**
- **Per-tool approval** — approve/deny individual tools, not just all-or-nothing
- **Auto-approve allowlist** — user can configure trusted tools to skip approval
- **Approval history** — log of past approvals for audit
- **Timeout** — auto-deny after configurable timeout (e.g., 5 minutes)

#### 2.2.5 Agent-Initiated Actions

Future agents may proactively notify users:

```
┌─ Notification ──────────────────────────────────┐
│  📋 Certification Expiry Alert                   │
│  3 team members have certifications expiring     │
│  in the next 30 days.                            │
│  [View details] [Send reminders] [Dismiss]       │
└──────────────────────────────────────────────────┘
```

**Implementation:** WebSocket or polling endpoint for server-initiated messages. Not needed in the current SSE architecture (which is request-response only).

---

## 3. Production UI Components

### 3.1 Conversation Thread Management

**Current:** Basic thread list in sidebar with refresh, load, and new chat buttons. No rename, delete, or search.

**Target:**

```
┌─ Chat History ──────────────────┐
│  🔍 [Search conversations...]   │
│                                  │
│  Today                           │
│  ├── Java developers in Spain ✏️🗑│
│  └── Bench analysis Q2 2026  ✏️🗑│
│                                  │
│  Yesterday                       │
│  ├── RFP-12345 role matching ✏️🗑│
│  └── CV generation batch     ✏️🗑│
│                                  │
│  Last 7 days                     │
│  └── ...                         │
└──────────────────────────────────┘
```

**API requirements:**
- `PUT /threads/{id}` — rename thread
- `DELETE /threads/{id}` — delete thread
- `GET /threads?q=search` — search threads
- Group by date (Today, Yesterday, Last 7 days, Older)

### 3.2 Rich Message Rendering

**Current:** ReactMarkdown with `remark-gfm` handles markdown, tables, links. ChartView renders bar/line/radar/scatter charts from table data. CV download links detected by URL pattern.

**Target additions:**

| Content Type | Rendering | Status |
|-------------|-----------|--------|
| Markdown text | ReactMarkdown + remark-gfm | ✅ Done |
| Tables | Scrollable wrapper, sortable headers | Partial (scroll ✅, sort ❌) |
| Charts | recharts (bar, line, radar, scatter) | ✅ Done |
| File attachments | Download link with icon + size | Partial (CV links ✅, generic ❌) |
| Code blocks | Syntax highlighting (prism/highlight.js) | ❌ Missing |
| Images | Inline preview with lightbox | ❌ Missing |
| Candidate cards | Structured card with photo, score, skills | ❌ Missing |

#### Candidate Card Component (Future)

```jsx
<CandidateCard
  name="Carlos Lopez"
  email="carlos.lopez@dxc.com"
  location="Madrid, Spain"
  score={87}
  skills={["Java", "Spring Boot", "AWS"]}
  availability="Bench"
  benchDays={14}
  actions={[
    { label: "Add to shortlist", onClick: addToShortlist },
    { label: "Generate CV", onClick: generateCv },
  ]}
/>
```

### 3.3 Shortlist Management UI

**Current:** No shortlist UI.

**Target:**

```
┌─ Shortlist: RFP-12345 ─────────────────────────────────────┐
│  3 candidates | Last updated 2h ago                          │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Rank │ Name          │ Score │ Skills      │ Status     ││
│  │ 1    │ Carlos Lopez  │ 87    │ Java, AWS   │ ✅ Bench   ││
│  │ 2    │ Ana García    │ 82    │ Java, Azure │ ⏳ Alloc.  ││
│  │ 3    │ Vikram Patel  │ 79    │ Java, GCP   │ ✅ Bench   ││
│  └─────────────────────────────────────────────────────────┘│
│                                                              │
│  [Compare selected] [Generate CVs] [Export to Excel]         │
│  [Share shortlist]  [Add candidate]                          │
└──────────────────────────────────────────────────────────────┘
```

**Comparison view** — side-by-side radar charts of selected candidates:

```
┌─ Compare Candidates ────────────────────────────┐
│                                                  │
│   Carlos Lopez          Ana García               │
│   ┌──────────┐          ┌──────────┐            │
│   │  Radar   │          │  Radar   │            │
│   │  Chart   │          │  Chart   │            │
│   └──────────┘          └──────────┘            │
│                                                  │
│   Skills: 92           Skills: 88               │
│   Certs:  85           Certs:  90               │
│   Avail:  100          Avail:  60               │
│   Score:  87           Score:  82               │
└──────────────────────────────────────────────────┘
```

### 3.4 Dashboard Views

**Current:** No dashboards. Analytics are inline in chat responses.

**Target:** Dedicated dashboard route with:

| Dashboard | Widgets | Data Source |
|-----------|---------|-------------|
| People Analytics | Headcount by location, Skills heatmap, Bench breakdown | Graph queries |
| Scoring Distributions | Impressiveness histogram, Score by skill category | Aggregate queries |
| Bench Metrics | Bench aging chart, Bench by service line, Trending | Time-series queries |
| Certification Tracker | Expiring certs timeline, Coverage by skill area | Cert queries |

**Implementation:** React Router for multi-view SPA. Each dashboard is a lazy-loaded route.

```jsx
const Dashboard = React.lazy(() => import("./views/Dashboard"));

<Routes>
  <Route path="/" element={<ChatView />} />
  <Route path="/dashboard" element={<Dashboard />} />
  <Route path="/shortlists" element={<ShortlistView />} />
</Routes>
```

### 3.5 File Upload Flow

**Current:** Hidden file input triggered by 📎 button. Upload to `/af/upload`, response content stored in state, auto-sends with last user question.

**Target enhancements:**

```
┌─ Upload Progress ──────────────────────────────┐
│  📄 RFP_Telefonica_2026.pdf                     │
│  ████████████████████░░░░  78%                  │
│  Uploading... 2.4 MB / 3.1 MB                   │
│                                    [Cancel]      │
└─────────────────────────────────────────────────┘

┌─ Extraction Results ───────────────────────────┐
│  📄 RFP_Telefonica_2026.pdf                     │
│  ✅ Extracted 4 roles:                           │
│     • Senior Java Developer (2 positions)       │
│     • Project Manager (1 position)              │
│     • DevOps Engineer (1 position)              │
│                                                  │
│  [Match candidates] [View full extraction]       │
└─────────────────────────────────────────────────┘
```

**Implementation:**
- Use `XMLHttpRequest` or `fetch` with progress tracking for upload
- Show structured extraction results before sending to agent
- Allow user to edit/confirm extracted roles before matching

### 3.6 Export Actions

**Current:** Agent generates files server-side, returns download links in markdown.

**Target UI:**

```
┌─ Export ──────────────────────────────────────┐
│  Format:  [Excel ▼]                           │
│  Content: Search results (12 candidates)      │
│                                               │
│  ████████████████████████ 100%                │
│  ✅ Export ready                               │
│  [Download] [Open in new tab]                 │
└───────────────────────────────────────────────┘
```

**Supported formats:** Excel (.xlsx), PDF, PPTX (DXC-branded), CSV

**Implementation:** Backend generates files, returns a download URL. Frontend shows progress via polling or SSE events.

---

## 4. Accessibility & Internationalization

### 4.1 WCAG 2.1 AA Compliance

| Requirement | Current | Target |
|------------|---------|--------|
| Color contrast (4.5:1 text, 3:1 UI) | Partial — dark theme needs audit | Full compliance |
| Keyboard navigation | Partial — buttons work, no focus management | Full tab/arrow/enter navigation |
| Focus indicators | CSS `:focus` styles exist | Visible focus ring on all interactive elements |
| Screen reader labels | None | `aria-label`, `aria-live`, `role` attributes |
| Skip navigation | None | "Skip to chat" link |
| Reduced motion | None | `prefers-reduced-motion` media query |

#### Streaming Content Accessibility

Screen readers need live region announcements for streaming content:

```jsx
<div
  className="chat-messages"
  role="log"
  aria-live="polite"
  aria-label="Chat conversation"
>
  {messages.map(/* ... */)}
</div>

{/* Announce new messages to screen readers */}
<div className="sr-only" aria-live="assertive">
  {chatLoading ? "Assistant is thinking..." : ""}
</div>
```

**Challenge:** Streaming content generates many rapid updates. Use `aria-live="polite"` (not `assertive`) for message content, and only announce the final message — not every delta.

#### Keyboard Navigation Map

```
Tab order:
1. Skip link → main chat
2. Sidebar: FAQ categories (Enter to expand, arrow keys within)
3. Chat history items
4. Chat input textarea
5. Upload button
6. Send button
7. Clear chat button
8. Run log panel (if visible)

Shortcuts:
- Ctrl+Enter → Send message (alternative to Enter)
- Escape → Close approval dialog / template selector
- Ctrl+/ → Focus chat input
```

### 4.2 Internationalization (i18n)

**Product spec requirement:** ES, EN, FR, PT

**Recommended framework:** `react-i18next` — lightweight, proven, supports lazy-loaded translations.

```javascript
// src/i18n.js
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: require("./locales/en.json") },
    es: { translation: require("./locales/es.json") },
    fr: { translation: require("./locales/fr.json") },
    pt: { translation: require("./locales/pt.json") },
  },
  lng: navigator.language.split("-")[0],
  fallbackLng: "en",
});
```

**Translation scope:**

| Category | Examples | Count (est.) |
|----------|----------|-------------|
| UI chrome | "Sign in", "Clear chat", "Send", "Upload" | ~50 strings |
| Error messages | "Session expired", "Connection lost" | ~15 strings |
| FAQ questions | All 35 quick questions | ~35 strings |
| Placeholders | "Ask about candidates...", "Search conversations..." | ~10 strings |
| Accessibility | aria-labels, screen reader text | ~20 strings |

**Agent responses** are NOT translated — they come from the LLM. The product spec notes that the agent should respond in the user's language, which is an agent-level concern (system prompt), not a UI concern.

### 4.3 RTL Layout

Arabic and Hebrew are not in the initial language set. For future-proofing:

```css
/* CSS logical properties — already directional */
.sidebar { margin-inline-start: 0; }
.bubble.user { margin-inline-start: auto; }
```

**No RTL work needed now.** Document as a future consideration.

---

## 5. Performance & Reliability

### 5.1 Virtual Scrolling

**Problem:** Long conversations (100+ messages) cause DOM bloat. Each message bubble includes ReactMarkdown parsing.

**Solution:** `react-window` or `@tanstack/virtual` for virtualized message list.

```jsx
import { VariableSizeList } from "react-window";

<VariableSizeList
  height={chatHeight}
  itemCount={messages.length}
  itemSize={getMessageHeight}
  width="100%"
>
  {({ index, style }) => (
    <div style={style}>
      <Bubble {...messages[index]} />
    </div>
  )}
</VariableSizeList>
```

**Complexity:** High — message heights are variable (markdown content, tables, charts). Need a dynamic height measurement strategy or estimated heights with recalculation.

**Recommendation:** Defer until conversations regularly exceed 50 messages. Current DOM performance is acceptable for typical sessions.

### 5.2 Service Worker

```javascript
// sw.js — cache UI shell for fast load
const CACHE_NAME = "talentiq-v1";
const SHELL_URLS = ["/", "/index.html", "/assets/main.js", "/assets/main.css"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(SHELL_URLS)));
});

self.addEventListener("fetch", (e) => {
  // Network-first for API calls, cache-first for shell
  if (e.request.url.includes("/af/")) return; // skip API
  e.respondWith(
    caches.match(e.request).then((r) => r || fetch(e.request))
  );
});
```

**Scope:** Cache the UI shell (HTML, JS, CSS) only. API responses are never cached — data must be fresh.

**Recommendation:** Add after the app is deployed to a stable URL. Not needed during active development.

### 5.3 WebSocket vs SSE

| Feature | SSE (current) | WebSocket |
|---------|--------------|-----------|
| Direction | Server → Client only | Bidirectional |
| Protocol | HTTP/1.1 or HTTP/2 | ws:// or wss:// |
| Auth | Standard HTTP headers | Custom handshake needed |
| Reconnection | Built into EventSource (not our POST approach) | Manual |
| Proxy support | Excellent (standard HTTP) | Good (but some proxies struggle) |
| Use case fit | Request → streaming response ✅ | Real-time notifications, collaborative editing |

**Recommendation:** Stay with POST + SSE. WebSocket is only needed when we add:
- Server-initiated notifications (cert expiry alerts, bench status changes)
- Collaborative features (shared shortlists with live updates)
- Real-time agent-to-agent communication visibility

### 5.4 Bundle Optimization

**Current bundle (estimated from package.json):**

| Package | Size (gzip) | Purpose |
|---------|------------|---------|
| react + react-dom | ~42 KB | Core |
| recharts | ~150 KB | Charts |
| react-markdown + remark-gfm | ~35 KB | Markdown |
| @azure/msal-browser | ~45 KB | Auth |
| applicationinsights-web | ~30 KB | Telemetry |
| **Total** | **~302 KB** | |

**Optimization strategies:**

1. **Code splitting** — Lazy-load `ChartView` and `recharts` (only needed when user clicks "Show Chart"):
   ```javascript
   const ChartView = React.lazy(() => import("./ChartView"));
   // Saves ~150 KB from initial load
   ```

2. **Tree shaking** — Import only used recharts components (already done correctly):
   ```javascript
   import { BarChart, Bar } from "recharts"; // ✅ named imports
   ```

3. **Dynamic import for telemetry** — Load App Insights only when configured:
   ```javascript
   if (import.meta.env.VITE_APPINSIGHTS_CONNECTION_STRING) {
     import("@microsoft/applicationinsights-web").then(/* init */);
   }
   ```

### 5.5 Performance Budgets

| Metric | Budget | Current (est.) | Notes |
|--------|--------|---------------|-------|
| **LCP** (Largest Contentful Paint) | < 2.5s | ~1.5s | Login card or chat empty state |
| **FID** (First Input Delay) | < 100ms | ~50ms | No heavy JS on load |
| **CLS** (Cumulative Layout Shift) | < 0.1 | ~0.05 | Streaming bubbles grow downward — acceptable |
| **TTI** (Time to Interactive) | < 3.5s | ~2.5s | After MSAL init |
| **Bundle size** (gzip) | < 350 KB | ~302 KB | Within budget |

**Monitoring:** Application Insights captures Web Vitals when `enableAutoRouteTracking: true` is set (current config).

---

## 6. Design System

### 6.1 Current State

**File:** [talent_ui/src/App.css](../../talent_ui/src/App.css) — ~700 lines

**CSS custom properties (current):**

```css
:root {
  --bg: #181a20;
  --bg-secondary: #23263a;
  --text: #e6e6e6;
  --text-muted: #b0b0b0;
  --accent: #E8845A;        /* DXC brand orange */
  --accent-light: #f4a97a;
  --border: #2d2f3e;
  --shadow: 0 2px 12px rgba(0,0,0,0.25);
}
```

**Approach:** All styles in one CSS file. Class-name conventions match the reference implementation. Dark theme only.

### 6.2 Target State: Fluent UI v9

**Recommendation:** Align with [Fluent UI React v9](https://react.fluentui.dev/) for the Microsoft ecosystem.

**Rationale:**
- TalentIQ is a DXC internal tool running on Microsoft infrastructure (Entra ID, Foundry)
- Fluent UI provides accessible, themeable components out of the box
- Reduces custom CSS maintenance

**Migration approach:**
1. Install `@fluentui/react-components`
2. Replace primitive elements incrementally (buttons, inputs, dialogs)
3. Keep DXC brand tokens as Fluent theme overrides
4. Keep current CSS for layout; use Fluent for interactive components

```javascript
import { createLightTheme, createDarkTheme } from "@fluentui/react-components";

const dxcBrandRamp = {
  10: "#1a0a04",
  // ...
  80: "#E8845A",   // Primary brand color
  // ...
  160: "#fdf5f1",
};

const dxcDarkTheme = createDarkTheme(dxcBrandRamp);
const dxcLightTheme = createLightTheme(dxcBrandRamp);
```

**Trade-off:** Fluent UI v9 adds ~80-100 KB gzip to the bundle. Worth it for accessibility compliance and component quality, but should be lazy-loaded where possible.

### 6.3 Dark/Light Theme Support

```css
/* Theme toggle with CSS custom properties */
[data-theme="light"] {
  --bg: #f5f5f5;
  --bg-secondary: #ffffff;
  --text: #1a1a1a;
  --text-muted: #666666;
  --accent: #E8845A;
  --border: #e0e0e0;
  --shadow: 0 2px 12px rgba(0,0,0,0.1);
}
```

```jsx
// Theme toggle component
const [theme, setTheme] = useState(
  window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
);

useEffect(() => {
  document.documentElement.setAttribute("data-theme", theme);
}, [theme]);
```

### 6.4 DXC Branding Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--accent` | `#E8845A` | Primary buttons, links, active states |
| `--accent-light` | `#f4a97a` | Hover states |
| `--accent-dark` | `#c06840` | Active/pressed states |
| Font family | `"Segoe UI", system-ui, sans-serif` | All text |
| Border radius | `8px` (cards), `6px` (buttons), `4px` (inputs) | Consistent rounding |

### 6.5 Responsive Breakpoints

| Breakpoint | Width | Layout |
|-----------|-------|--------|
| Desktop | ≥ 1200px | Sidebar + Chat + Run Log (3 columns) |
| Tablet | 768–1199px | Sidebar collapsed (hamburger) + Chat + Run Log |
| Mobile | < 768px | Full-width chat, bottom nav, Run Log as drawer |

```css
@media (max-width: 1199px) {
  .sidebar { position: absolute; transform: translateX(-100%); }
  .sidebar.open { transform: translateX(0); }
  .runlog-panel { width: 100%; position: absolute; right: 0; }
}

@media (max-width: 767px) {
  .app-container { flex-direction: column; }
  .runlog-panel { display: none; } /* Show as bottom drawer on tap */
}
```

---

## 7. Migration Roadmap

### Phase 1: Production Hardening (Current Sprint)

| Item | Effort | Priority |
|------|--------|----------|
| AbortController for stream cancellation | S | P1 |
| Proactive token refresh (5-min window) | S | P1 |
| Auto-retry on 401 with fresh token | M | P1 |
| Move auth config to env vars | S | P1 |
| Extract components from App.jsx | M | P2 |
| useReducer for chat state | M | P2 |

### Phase 2: UX Enhancement (Sprint 5-6)

| Item | Effort | Priority |
|------|--------|----------|
| Thread rename/delete/search | M | P2 |
| Code syntax highlighting | S | P3 |
| Structured tool execution view | L | P2 |
| File upload progress | S | P3 |
| Keyboard navigation audit | M | P1 (accessibility) |
| ARIA labels and live regions | M | P1 (accessibility) |

### Phase 3: Agentic Workspace (Sprint 7+)

| Item | Effort | Priority |
|------|--------|----------|
| Multi-agent visibility (agent cards) | L | P2 |
| Agent reasoning traces | L | P3 |
| Shortlist management UI | L | P2 |
| Dashboard views | XL | P3 |
| i18n (ES, EN, FR, PT) | L | P2 |
| Dark/light theme toggle | M | P3 |
| Fluent UI component migration | XL | P3 |

### Phase 4: Scale & Performance (Backlog)

| Item | Effort | Priority |
|------|--------|----------|
| Virtual scrolling for conversations | L | P3 |
| Service Worker for offline shell | M | P3 |
| React Router for multi-view | M | P2 |
| Lazy-load recharts | S | P3 |
| Bundle size audit | S | P3 |
| Responsive mobile layout | L | P3 |

---

## Appendix A: Component Inventory (Current → Target)

| Component | Current Location | Target Location | Status |
|-----------|-----------------|-----------------|--------|
| `App` | `App.jsx` | `App.jsx` (layout shell) | Refactor |
| `CollapsibleCategory` | `App.jsx` (inline) | `components/Sidebar/CollapsibleCategory.jsx` | Extract |
| `RunLogPanel` | `App.jsx` (inline) | `components/RunLog/RunLogPanel.jsx` | Extract |
| `RunLogBlock` | `App.jsx` (inline) | `components/RunLog/RunLogBlock.jsx` | Extract |
| `Bubble` | `App.jsx` (inline) | `components/Chat/Bubble.jsx` | Extract |
| `ApprovalDialog` | `App.jsx` (inline) | `components/Chat/ApprovalDialog.jsx` | Extract |
| `ChartView` | `ChartView.jsx` | `components/ChartView.jsx` | Done |
| `CandidateCard` | — | `components/CandidateCard.jsx` | New |
| `ShortlistPanel` | — | `components/Shortlist/ShortlistPanel.jsx` | New |
| `ExportDialog` | — | `components/ExportDialog.jsx` | New |
| `ThemeToggle` | — | `components/ThemeToggle.jsx` | New |

## Appendix B: Dependencies Roadmap

| Package | Current | Phase | Purpose |
|---------|---------|-------|---------|
| `react` | 18.3.1 | — | Core |
| `recharts` | 2.13.3 | — | Charts |
| `react-markdown` | 9.0.1 | — | Markdown rendering |
| `@azure/msal-browser` | 3.27.0 | — | Auth |
| `react-i18next` | — | Phase 3 | Internationalization |
| `@fluentui/react-components` | — | Phase 3 | Component library |
| `react-router-dom` | — | Phase 3 | Multi-view routing |
| `react-window` | — | Phase 4 | Virtual scrolling |
| `prismjs` | — | Phase 2 | Code syntax highlighting |
