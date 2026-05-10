# UI Architecture: SSE & Entra ID Authentication Spec

> **Version:** 1.0  
> **Date:** 2026-05-10  
> **Author:** Dallas (Frontend Dev)  
> **Status:** Current-state documentation + target-state recommendations

---

## 1. SSE Streaming Implementation

### 1.1 Current State

TalentIQ uses **POST-initiated SSE** for streaming responses. Unlike standard `EventSource` (GET-only), we use `fetch()` with `ReadableStream` to support POST bodies with auth headers.

**Endpoints:**

| Backend | Endpoint | Stream Format |
|---------|----------|--------------|
| `graph-search` | `POST /af/graph/responses` | NDJSON (newline-delimited JSON) |
| `agent-framework` | `POST /af/responses` | SSE (`event:` / `data:` lines) |
| `default` | `POST /chat` | Non-streaming JSON response |

**File:** [talent_ui/src/App.jsx](../../talent_ui/src/App.jsx)

#### 1.1.1 Graph Search Stream (NDJSON)

```
POST /af/graph/responses
Content-Type: application/json
Authorization: Bearer <token>

{"input": "Find Java developers in Spain", "session_id": "..."}
```

Response body — newline-separated JSON objects:

```jsonl
{"response_message": {"type": "OrchestratorEvent", "delta": "Routing to search agent..."}}
{"response_message": {"type": "AgentEvent", "delta": "[QUERY] CYPHER: MATCH (e:Employee)..."}}
{"response_message": {"type": "AgentEvent", "delta": "[RESULT] Found 12 employees"}}
{"response_message": {"type": "WorkflowOutputEvent", "delta": "| Name | Skills | Location |..."}}
{"response_message": {"type": "done", "result": "...", "session_id": "abc-123"}}
```

**Event types and their UI handling:**

| `type` | UI Behavior | Badge |
|--------|------------|-------|
| `OrchestratorEvent` / `MagenticOrchestratorMessageEvent` | Appends to run log panel | `ORCH` |
| `AgentEvent` / `MagenticAgentMessageEvent` | Parsed for `[QUERY]`, `[RESULT]`, `[HANDOFF]` prefixes → run log | `CYPHER`/`SQL`/`FTS`/`VECTOR`/`HANDOFF` |
| `WorkflowOutputEvent` / `WorkflowFinalResultEvent` | Renders as assistant message bubble | — |
| `done` | Stores `session_id`, completes telemetry tracking | — |
| `error` | Throws → caught by `sendMessage` error handler | `ERROR` |

#### 1.1.2 Agent Framework Stream (SSE)

```
event: message
data: {"text": "Here are the results...", "speaker": "assistant", "id": "resp-1"}

event: handoff
data: {"target": "cv-generation-agent"}

event: done
data: {"session_id": "abc-123", "id": "resp-1"}

event: error
data: {"message": "Workflow error"}
```

#### 1.1.3 ReadableStream Parsing

Both backends use the same pattern:

```javascript
const reader = res.body.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });

  const lines = buffer.split("\n");
  buffer = lines.pop(); // keep incomplete line in buffer

  for (const line of lines) {
    // Parse NDJSON or SSE event/data pairs
  }
}
```

**Key detail:** The `{ stream: true }` flag on `TextDecoder.decode()` is critical — it prevents multi-byte UTF-8 characters from being split across chunks.

### 1.2 Connection Lifecycle

```
┌─────────┐    POST /af/graph/responses    ┌─────────┐
│  Client  │──────────────────────────────▶│  Server  │
│          │◀── 200 + chunked body ────────│          │
│          │◀── NDJSON chunk ──────────────│          │
│          │◀── NDJSON chunk ──────────────│          │
│          │◀── {"type":"done"} ───────────│          │
│          │── reader.read() returns done ─│          │
└─────────┘                                └─────────┘
```

**States:**

1. **Idle** — No active stream. `chatLoading = false`.
2. **Connecting** — `fetch()` in flight. `chatLoading = true`.
3. **Streaming** — Reading chunks. Run log updates in real time. Message bubble accumulates.
4. **Complete** — `done` event received or `reader.read()` returns `{ done: true }`. `chatLoading = false`.
5. **Error** — Network failure or `error` event. Error bar shown. `chatLoading = false`.

### 1.3 Current Limitations

| Issue | Description | Impact |
|-------|-------------|--------|
| **No AbortController** | User cannot cancel an in-flight stream | UI frozen until stream completes or errors |
| **No reconnection** | If the connection drops mid-stream, the partial response is lost | User sees incomplete answer |
| **No backpressure** | If the UI can't render fast enough, chunks queue in memory | Potential memory pressure on very large responses |
| **No concurrent stream prevention** | `sendingRef.current` guards double-click but not rapid sequential sends | Could theoretically open two readers |
| **Token expiry mid-stream** | If a token expires during a long stream, there's no mechanism to refresh | Stream fails with auth error |

### 1.4 Target State

#### AbortController Integration

```javascript
// In App.jsx — add to component state
const abortControllerRef = useRef(null);

const sendMessage = async (text) => {
  // Cancel any in-flight stream
  abortControllerRef.current?.abort();
  const controller = new AbortController();
  abortControllerRef.current = controller;

  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: controller.signal,
  });

  // ... reading loop ...
  // On user cancel:
  // abortControllerRef.current.abort();
};
```

**UI:** Add a "Stop generating" button visible during `chatLoading`:

```jsx
{chatLoading && (
  <button className="btn-ghost btn-stop" onClick={() => abortControllerRef.current?.abort()}>
    ■ Stop
  </button>
)}
```

#### Reconnection Strategy

For POST-based SSE, true reconnection is complex because the server doesn't support `Last-Event-ID`. Recommended approach:

1. **Detect disconnection** — `reader.read()` throws `TypeError: network error` or `AbortError`.
2. **Preserve partial content** — Keep accumulated message text and run log entries.
3. **Show recovery UI** — "Connection lost. Your partial results are preserved. Click to retry."
4. **Do NOT auto-retry** — POST requests are not idempotent. Auto-retry would duplicate the agent workflow.

#### Backpressure Handling

The current `while(true) { reader.read() }` loop is inherently pull-based, which provides natural backpressure — the browser won't fetch the next chunk until the current one is processed. This is **already correct** for our use case.

The only risk is if `setMessages()` / `setRunLogRuns()` React state updates queue faster than React can batch them. Mitigation:

```javascript
// Batch run log updates with requestAnimationFrame
const pendingEntries = useRef([]);

const pushLogEntry = (entry) => {
  pendingEntries.current.push(entry);
  if (pendingEntries.current.length === 1) {
    requestAnimationFrame(() => {
      const batch = pendingEntries.current.splice(0);
      setRunLogRuns((prev) => /* apply batch */);
    });
  }
};
```

### 1.5 Migration Path

| Step | Change | Risk |
|------|--------|------|
| 1 | Add `AbortController` to `callGraphBackendApi` and `callAfBackendApi` | Low — additive |
| 2 | Add "Stop generating" button in chat input bar | Low — UI only |
| 3 | Wrap stream reading in try/catch for `AbortError` handling | Low — error path only |
| 4 | Add connection-lost UI with partial content preservation | Medium — new state management |
| 5 | Batch run log updates with `requestAnimationFrame` | Low — performance optimization |

---

## 2. Entra ID Authentication & Token Refresh

### 2.1 Current State

**File:** [talent_ui/src/authConfig.js](../../talent_ui/src/authConfig.js)

```javascript
export const msalConfig = {
  auth: {
    clientId: "48449491-8390-4af0-8121-da7af091ad56",
    authority: "https://login.microsoftonline.com/150305b3-cc4b-46dd-9912-425678db1498",
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "sessionStorage",
    storeAuthStateInCookie: false,
  },
};

export const foundryLoginRequest = {
  scopes: ["https://ai.azure.com/user_impersonation"],
};
```

**Token acquisition flow in App.jsx:**

```
┌──────────────────────────────────────────────────────────────┐
│                    Token Acquisition Flow                      │
│                                                                │
│  getToken(forceRefresh?)                                       │
│    │                                                           │
│    ├─▶ acquireTokenSilent(foundryLoginRequest, account)        │
│    │     │                                                     │
│    │     ├─ Success → setAccessToken(token) → return token     │
│    │     │                                                     │
│    │     └─ InteractionRequiredAuthError                       │
│    │           │                                               │
│    │           └─▶ acquireTokenRedirect(foundryLoginRequest)   │
│    │                 │                                         │
│    │                 ├─ Success → redirect back → getToken()   │
│    │                 └─ Failure → setNeedsConsent(true)        │
│    │                                                           │
│    └─ Other error → setError(message)                          │
└──────────────────────────────────────────────────────────────┘
```

**Token usage in API calls:**

```javascript
// Every API call follows this pattern:
let token = accessToken;          // Try cached token first
if (!token) token = await getToken();  // Acquire if missing
if (!token) return;               // Auth failed — bail

const res = await fetch(url, {
  headers: { Authorization: `Bearer ${token}` },
  ...
});
```

**Token expiry handling (current):**

```javascript
const isTokenExpiredError = (err) => {
  const msg = (err?.message || String(err)).toLowerCase();
  return msg.includes("token") && (msg.includes("expired") || msg.includes("401"));
};

// In sendMessage catch block:
if (isTokenExpiredError(e)) {
  const freshToken = await getToken(true); // forceRefresh = true
  if (freshToken) {
    setError("Session refreshed. Please try your request again.");
  } else {
    setError("Your session has expired. Please sign in again.");
  }
}
```

### 2.2 Current Limitations

| Issue | Description |
|-------|-------------|
| **No proactive refresh** | Token is only refreshed on 401/expiry error — not before it expires |
| **No mid-stream refresh** | If token expires during a 30s+ SSE stream, the stream fails |
| **String-based error detection** | `isTokenExpiredError` relies on substring matching — fragile |
| **No auto-retry after refresh** | User gets "Session refreshed. Please try again." — manual retry |
| **sessionStorage cache** | Token lost on tab close; no cross-tab coordination |
| **Hardcoded values** | `clientId`, `authority` hardcoded in source — should come from `VITE_*` env vars |

### 2.3 Target State

#### 2.3.1 Proactive Token Refresh

MSAL tokens for `user_impersonation` typically have a 1-hour lifetime. We should refresh proactively before expiry.

```javascript
// Token refresh timer — start after successful token acquisition
const tokenRefreshTimerRef = useRef(null);

const scheduleTokenRefresh = useCallback((expiresOn) => {
  if (tokenRefreshTimerRef.current) {
    clearTimeout(tokenRefreshTimerRef.current);
  }

  const now = Date.now();
  const expiryMs = expiresOn instanceof Date ? expiresOn.getTime() : expiresOn * 1000;
  const refreshAt = expiryMs - 5 * 60 * 1000; // 5 minutes before expiry
  const delay = Math.max(refreshAt - now, 0);

  tokenRefreshTimerRef.current = setTimeout(async () => {
    console.debug("[auth] Proactive token refresh");
    await getToken(true);
  }, delay);
}, [getToken]);

// In getToken, after successful acquireTokenSilent:
const res = await instance.acquireTokenSilent({ ... });
setAccessToken(res.accessToken);
scheduleTokenRefresh(res.expiresOn);
return res.accessToken;
```

#### 2.3.2 Mid-Stream Token Handling

This is the hardest edge case. During a long SSE stream, the token might expire. The backend validates the token at connection open, so the stream itself won't fail. But if the user sends a follow-up immediately after a long stream, the cached token may be stale.

**Strategy:** The proactive refresh timer (above) handles this. Since `acquireTokenSilent` uses MSAL's internal cache and refresh tokens, it won't interrupt the SSE stream — it just updates the `accessToken` state for the next request.

**If the backend starts validating tokens per-chunk** (not current behavior), we'd need to:
1. Pass a token-refresh callback into the stream reader
2. Inject fresh tokens via a custom header on a keep-alive mechanism

This is **not needed today** — document for future reference.

#### 2.3.3 Automatic Retry After Token Refresh

```javascript
// Replace the current catch block with auto-retry:
catch (e) {
  if (isTokenExpiredError(e) && !retried) {
    const freshToken = await getToken(true);
    if (freshToken) {
      // Retry the same request with fresh token
      retried = true;
      const data = await callChatApi(body, freshToken);
      handleChatResponse(data);
      return;
    }
  }
  setError(e?.message || String(e));
}
```

#### 2.3.4 Production Cache Configuration

```javascript
// authConfig.js — production recommendation
export const msalConfig = {
  auth: {
    clientId: import.meta.env.VITE_AZURE_CLIENT_ID,
    authority: `https://login.microsoftonline.com/${import.meta.env.VITE_AZURE_TENANT_ID}`,
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    // localStorage for production: survives tab close, enables cross-tab SSO
    cacheLocation: import.meta.env.PROD ? "localStorage" : "sessionStorage",
    storeAuthStateInCookie: false,
  },
};
```

**Trade-offs:**

| Cache Location | Pros | Cons |
|---------------|------|------|
| `sessionStorage` (current) | Isolated per tab, cleared on close | No cross-tab SSO, re-auth on every tab |
| `localStorage` (recommended for prod) | Cross-tab SSO, survives refresh | Persists until explicit logout, XSS risk |

For a corporate intranet app with HTTPS and CSP headers, `localStorage` is the standard choice.

#### 2.3.5 Multi-Tab Token Coordination

With `localStorage`, MSAL handles cross-tab coordination automatically via `BroadcastChannel`. No additional code needed — MSAL.js v3 includes this by default.

If custom coordination is needed (e.g., syncing `afSessionId` across tabs):

```javascript
// Optional: sync session state across tabs
const channel = new BroadcastChannel("talentiq-sync");
channel.onmessage = (e) => {
  if (e.data.type === "session-update") {
    setAfSessionId(e.data.sessionId);
  }
};
// On session change:
channel.postMessage({ type: "session-update", sessionId: newId });
```

#### 2.3.6 Logout and Token Cleanup

Current logout is correct but should also clear app-specific state:

```javascript
const logout = () => {
  // Clear app state
  setAccessToken(null);
  setMessages([]);
  setAfSessionId(null);
  setRunLogRuns([]);
  setPendingApprovals(null);
  setUploadedFile(null);

  // Clear refresh timer
  if (tokenRefreshTimerRef.current) {
    clearTimeout(tokenRefreshTimerRef.current);
  }

  // MSAL logout — clears cache and redirects
  instance.logoutRedirect({ account });
};
```

### 2.4 Migration Path

| Step | Change | Risk |
|------|--------|------|
| 1 | Move hardcoded auth values to `VITE_*` env vars | Low — config change |
| 2 | Add proactive token refresh timer (5-min window) | Low — additive |
| 3 | Implement auto-retry on 401 with fresh token | Medium — must prevent infinite retry |
| 4 | Switch to `localStorage` cache for production builds | Low — MSAL config flag |
| 5 | Add comprehensive logout cleanup | Low — additive |

---

## 3. State Management

### 3.1 Current State

All state lives in `useState` hooks inside `App.jsx`. The component manages **19 state variables**:

```javascript
// Auth state
const [error, setError] = useState(null);
const [needsConsent, setNeedsConsent] = useState(false);
const [accessToken, setAccessToken] = useState(null);

// Chat state
const [chatInput, setChatInput] = useState("");
const [chatLoading, setChatLoading] = useState(false);
const [messages, setMessages] = useState([]);
const [previousResponseId, setPreviousResponseId] = useState(null);
const [afSessionId, setAfSessionId] = useState(null);

// Run log state
const [runLogRuns, setRunLogRuns] = useState([]);

// Thread state
const [threads, setThreads] = useState([]);
const [threadsLoading, setThreadsLoading] = useState(false);
const [activeThreadId, setActiveThreadId] = useState(null);

// MCP approval state
const [pendingApprovals, setPendingApprovals] = useState(null);
const [pendingApprovalResponseId, setPendingApprovalResponseId] = useState(null);

// OAuth consent state
const [oauthConsentLink, setOauthConsentLink] = useState(null);
const [oauthResponseId, setOauthResponseId] = useState(null);

// File upload state
const [uploadedFile, setUploadedFile] = useState(null);
const [uploading, setUploading] = useState(false);

// CV template state
const [cvTemplates, setCvTemplates] = useState([]);
const [showTemplateSelector, setShowTemplateSelector] = useState(false);
const [pendingCvEmail, setPendingCvEmail] = useState(null);
const [pendingCvQuestion, setPendingCvQuestion] = useState(null);

// Backend selector
const [selectedBackend, setSelectedBackend] = useState("graph-search");
```

### 3.2 Limitations

1. **God component** — `App.jsx` is ~1250 lines with all state and logic in one component.
2. **Prop drilling risk** — As components are extracted, state must pass through multiple levels.
3. **Related state is scattered** — Approval state (`pendingApprovals`, `pendingApprovalResponseId`) should be co-located.
4. **No state reset function** — `clearChat()` manually resets 7 variables — easy to miss one.

### 3.3 Target State

#### Recommended: `useReducer` for Chat State

```javascript
const initialChatState = {
  messages: [],
  loading: false,
  error: null,
  previousResponseId: null,
  sessionId: null,
  activeThreadId: null,
  // Approval sub-state
  pendingApprovals: null,
  pendingApprovalResponseId: null,
  // OAuth sub-state
  oauthConsentLink: null,
  oauthResponseId: null,
};

function chatReducer(state, action) {
  switch (action.type) {
    case "SEND_MESSAGE":
      return {
        ...state,
        loading: true,
        error: null,
        messages: [...state.messages, { role: "user", text: action.text }],
      };
    case "RECEIVE_DELTA":
      return {
        ...state,
        messages: updateLastAssistantMessage(state.messages, action.text, action.speaker),
      };
    case "RECEIVE_DONE":
      return {
        ...state,
        loading: false,
        sessionId: action.sessionId || state.sessionId,
        previousResponseId: action.responseId || state.previousResponseId,
      };
    case "RECEIVE_ERROR":
      return { ...state, loading: false, error: action.message };
    case "APPROVAL_REQUIRED":
      return {
        ...state,
        pendingApprovals: action.approvals,
        pendingApprovalResponseId: action.responseId,
      };
    case "CLEAR":
      return { ...initialChatState };
    case "LOAD_THREAD":
      return {
        ...initialChatState,
        messages: action.messages,
        previousResponseId: action.lastResponseId,
        activeThreadId: action.threadId,
      };
    default:
      return state;
  }
}
```

#### State Shape Diagram

```
AppState
├── auth (managed by MSAL + local state)
│   ├── accessToken: string | null
│   ├── needsConsent: boolean
│   └── error: string | null
│
├── chat (useReducer — chatReducer)
│   ├── messages: Message[]
│   ├── loading: boolean
│   ├── error: string | null
│   ├── previousResponseId: string | null
│   ├── sessionId: string | null
│   ├── activeThreadId: string | null
│   ├── pendingApprovals: Approval[] | null
│   ├── pendingApprovalResponseId: string | null
│   ├── oauthConsentLink: string | null
│   └── oauthResponseId: string | null
│
├── runLog (useState — isolated, append-only)
│   └── runs: RunLogEntry[]
│
├── upload (useState — transient)
│   ├── uploadedFile: FileContext | null
│   └── uploading: boolean
│
└── ui (useState — presentational)
    ├── selectedBackend: string
    ├── chatInput: string
    └── showTemplateSelector: boolean
```

### 3.4 Migration Path

| Step | Change | Risk |
|------|--------|------|
| 1 | Introduce `chatReducer` replacing 10 `useState` calls | Medium — core refactor |
| 2 | Extract `AuthProvider` context for token management | Medium — touches all API calls |
| 3 | Extract child components (`ChatPanel`, `Sidebar`, `RunLogPanel` already exists) | Low — incremental |
| 4 | Move FAQ data to separate file (`quickQuestions.js`) | Low — no behavior change |

---

## 4. API Client Layer

### 4.1 Current State

API calls are inline in `App.jsx` — each function (`sendMessage`, `handleFileUpload`, `loadThreads`, etc.) constructs its own `fetch` call with auth headers.

### 4.2 Target State

#### Centralized API Client

```javascript
// src/api/client.js
class TalentIQClient {
  constructor(getTokenFn) {
    this.getToken = getTokenFn;
    this.baseUrl = import.meta.env.VITE_AF_BACKEND_URL ?? "/af";
  }

  async _fetch(path, options = {}) {
    const token = await this.getToken();
    if (!token) throw new AuthError("No token available");

    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...options.headers,
      },
    });

    if (res.status === 401) {
      // Retry with forced refresh
      const freshToken = await this.getToken(true);
      if (!freshToken) throw new AuthError("Session expired");

      const retry = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${freshToken}`,
          ...options.headers,
        },
      });

      if (!retry.ok) throw await this._parseError(retry);
      return retry;
    }

    if (!res.ok) throw await this._parseError(res);
    return res;
  }

  async _parseError(res) {
    const data = await res.json().catch(() => ({}));
    const msg = data?.error?.message || data?.detail || `HTTP ${res.status}`;
    if (res.status === 401 || res.status === 403) return new AuthError(msg);
    if (res.status >= 500) return new ServerError(msg);
    return new ApiError(msg, res.status);
  }

  // Streaming endpoint — returns ReadableStream reader
  async streamGraphQuery(input, sessionId, fileContext, signal) {
    const body = { input };
    if (sessionId) body.session_id = sessionId;
    if (fileContext) body.file_context = fileContext;

    const res = await this._fetch("/graph/responses", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    });
    return res.body.getReader();
  }

  async uploadFile(file) {
    const token = await this.getToken();
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${this.baseUrl}/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });

    if (!res.ok) throw await this._parseError(res);
    return res.json();
  }

  async getTemplates() {
    const res = await this._fetch("/cv/templates");
    return res.json();
  }
}

// Error types for classification
class AuthError extends Error { constructor(msg) { super(msg); this.name = "AuthError"; } }
class ServerError extends Error { constructor(msg) { super(msg); this.name = "ServerError"; } }
class ApiError extends Error {
  constructor(msg, status) { super(msg); this.name = "ApiError"; this.status = status; }
}
```

#### Error Classification

```
Error caught
├── AuthError → force token refresh → retry once → redirect to login
├── ServerError → "Service unavailable. Please try again."
├── AbortError → user cancelled → no error shown
├── TypeError (network) → "Connection lost. Check your network."
└── ApiError → show error message from server
```

### 4.3 Migration Path

| Step | Change | Risk |
|------|--------|------|
| 1 | Create `src/api/client.js` with centralized fetch wrapper | Low — new file |
| 2 | Create error classes (`AuthError`, `ServerError`, `ApiError`) | Low — new file |
| 3 | Migrate `callGraphBackendApi` to use client | Medium — core flow |
| 4 | Migrate `callAfBackendApi` to use client | Medium — core flow |
| 5 | Migrate `handleFileUpload`, `loadThreads`, `loadThread` | Low — helper flows |

---

## 5. Component Architecture

### 5.1 Current State — Component Tree

```
<MsalProvider>                          // main.jsx
  <App>                                 // App.jsx — ~1250 lines, ALL logic
    ├── <aside.sidebar>
    │   ├── CollapsibleCategory × 15    // FAQ categories
    │   ├── CollapsibleCategory          // Chat History
    │   └── User info + logout
    │
    ├── <main.main-content>
    │   ├── Error bar
    │   ├── Consent bar
    │   └── <div.chat-container>
    │       ├── Chat header
    │       ├── <div.chat-messages>
    │       │   ├── Bubble × N           // inline component
    │       │   │   └── ChartView        // ChartView.jsx
    │       │   ├── ApprovalDialog       // inline component
    │       │   └── typing indicator
    │       ├── Template selector
    │       └── Chat input bar (textarea + upload + send)
    │
    └── <RunLogPanel>                    // inline component
        └── RunLogBlock × N              // inline component
```

**Inline components** (defined in App.jsx, not separate files):
- `CollapsibleCategory`
- `RunLogPanel`
- `RunLogBlock`
- `Bubble`
- `ApprovalDialog`

**Separate files:**
- `ChartView.jsx` — chart rendering from markdown tables
- `authConfig.js` — MSAL configuration
- `telemetry.js` — Application Insights wrapper

### 5.2 Target State — Recommended Refactoring

```
src/
├── main.jsx                     // Entry — MsalProvider
├── App.jsx                      // Layout shell — sidebar + main + runlog
├── authConfig.js                // MSAL config (env vars)
├── telemetry.js                 // App Insights
│
├── api/
│   └── client.js                // Centralized API client
│
├── hooks/
│   ├── useChat.js               // Chat state reducer + API calls
│   ├── useAuth.js               // Token management, refresh timer
│   ├── useStreamReader.js       // NDJSON/SSE stream parsing
│   └── useThreads.js            // Chat history CRUD
│
├── components/
│   ├── Sidebar/
│   │   ├── Sidebar.jsx
│   │   ├── QuickQuestions.jsx
│   │   └── ThreadList.jsx
│   │
│   ├── Chat/
│   │   ├── ChatPanel.jsx        // Messages list + input
│   │   ├── Bubble.jsx           // Single message bubble
│   │   ├── ApprovalDialog.jsx   // MCP tool approval
│   │   ├── OAuthBar.jsx
│   │   └── ChatInput.jsx        // Textarea + upload + send
│   │
│   ├── RunLog/
│   │   ├── RunLogPanel.jsx      // (already exists inline)
│   │   └── RunLogBlock.jsx
│   │
│   └── ChartView.jsx            // (already separate)
│
├── data/
│   └── quickQuestions.js         // FAQ categories array
│
└── styles/
    └── App.css                   // (could split per component later)
```

### 5.3 Error Boundary Placement

```jsx
// Wrap at route/panel level, not per-component
<ErrorBoundary fallback={<ErrorFallback />}>
  <ChatPanel />
</ErrorBoundary>

<ErrorBoundary fallback={<span>Run log error</span>}>
  <RunLogPanel />
</ErrorBoundary>
```

Error boundaries catch render errors only — they do NOT catch errors in event handlers or async code. API errors are handled by the error state in the chat reducer.

### 5.4 Lazy Loading

Not critical for the current SPA (single route), but useful for future multi-view:

```javascript
const ChartView = React.lazy(() => import("./components/ChartView"));

// In Bubble:
{showChart && (
  <Suspense fallback={<div className="chart-loading">Loading chart…</div>}>
    <ChartView text={text} />
  </Suspense>
)}
```

### 5.5 Migration Path

| Step | Change | Risk |
|------|--------|------|
| 1 | Extract FAQ data to `src/data/quickQuestions.js` | Low — data only |
| 2 | Extract `Bubble`, `ApprovalDialog` to separate files | Low — move + import |
| 3 | Extract `RunLogPanel`, `RunLogBlock` to `src/components/RunLog/` | Low — already isolated |
| 4 | Create `useChat` hook with reducer | Medium — core refactor |
| 5 | Create `useAuth` hook wrapping MSAL | Medium — touches auth flow |
| 6 | Create API client and migrate fetch calls | Medium — all API paths |
| 7 | Add `ErrorBoundary` around `ChatPanel` and `RunLogPanel` | Low — additive |

---

## 6. Telemetry Integration

### 6.1 Current State

**File:** [talent_ui/src/telemetry.js](../../talent_ui/src/telemetry.js)

Application Insights is initialized from `VITE_APPINSIGHTS_CONNECTION_STRING`. If not configured, all tracking functions are no-ops (graceful degradation).

**Tracked events:**

| Function | When | Data |
|----------|------|------|
| `trackUserQuery` | User sends message | query text (truncated 200 chars), backend |
| `trackApiCallStart` | Before fetch | endpoint → returns tracker with `.complete()` / `.fail()` |
| `trackQueryResponseTime` | Stream complete | query, backend, duration, success |
| `trackWorkflowEvent` | Each run log entry | event type, message (truncated 200 chars) |
| `trackError` | Any error | Error object + properties |
| `trackEvent` | Generic events | name + properties |

### 6.2 Recommendations

- Add `trackEvent("SessionStart")` on initial token acquisition
- Add `trackEvent("FileUpload", { filename, size })` on upload
- Add `trackEvent("StreamCancelled")` when user clicks Stop
- Add page view tracking for future multi-route SPA

---

## Appendix A: Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VITE_AZURE_CLIENT_ID` | Prod | hardcoded | Entra ID app registration client ID |
| `VITE_AZURE_TENANT_ID` | Prod | hardcoded | Entra ID tenant ID |
| `VITE_API_BASE` | No | `""` | Base URL for default chat API |
| `VITE_AF_BACKEND_URL` | No | `/af` | Backend API base (proxied in dev) |
| `VITE_AGENT_NAME` | No | `talentiq-agent` | Agent name for API calls |
| `VITE_APPINSIGHTS_CONNECTION_STRING` | No | — | Application Insights connection string |

## Appendix B: Key Decisions Reference

- **2026-05-09:** MSAL scope is `user_impersonation` on the Foundry resource (`https://ai.azure.com`), not the app's own client ID. This means the token audience is `https://ai.azure.com`. Backend must accept both audiences.
- **2026-05-09:** Token issuer can be v1 or v2 format depending on the resource registration. Backend accepts both.
- **2026-05-10:** Session ID must be stored from `done` events and sent on subsequent requests to maintain chat continuity.
- **2026-05-10:** Run log parsing uses prefix-based classification (`[QUERY] CYPHER:`, `[QUERY] FTS:`, `[HANDOFF]`) for badge rendering.
