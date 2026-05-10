# Backend Architecture Specification

**Author:** Ripley (Lead Architect)
**Date:** 2026-05-10
**Status:** Draft
**Audience:** Engineering team, DevOps, Security reviewers

---

## 1. System Overview

TalentIQ is a talent matching platform that uses an agentic AI architecture to interpret natural-language queries, search a graph database, perform vector similarity matching, and generate employee CVs. The backend consists of three co-deployed services:

| Service | Runtime | Port | Entry Point |
|---------|---------|------|-------------|
| **FastAPI Backend** | Python / uvicorn | 8000 | `talent_backend/__main__.py` |
| **FastMCP Server** | Python / FastMCP | 3002 | `talent_backend/mcp_server/__main__.py` |
| **React SPA** | Node / Vite | 5173 | `talent_ui/` |

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (React SPA)                                                │
│  MSAL Auth · SSE consumer · App Insights telemetry                  │
└──────────┬──────────────────────────────────────────────────────────┘
           │ HTTPS + Bearer JWT
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI Backend (port 8000)                                         │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐   │
│  │ Auth Middleware│  │ SSE / NDJSON     │  │ Chat History         │   │
│  │ (Entra JWT)   │  │ Streaming        │  │ (Cosmos DB + fallback│   │
│  └──────┬───────┘  └───────┬──────────┘  └──────────┬───────────┘   │
│         │                  │                         │               │
│  ┌──────▼──────────────────▼─────────────────────────▼───────────┐   │
│  │  Agent Framework Orchestrator                                  │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ Triage Agent │→ │ Query Agent  │  │ Document Agent       │  │   │
│  │  │              │→ │ CV Agent     │  │                      │  │   │
│  │  └──────────────┘  └──────┬───────┘  └──────────────────────┘  │   │
│  └───────────────────────────┼────────────────────────────────────┘   │
└──────────────────────────────┼───────────────────────────────────────┘
                               │ Streamable HTTP (MCP protocol)
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastMCP Server (port 3002)                                          │
│  Tools: query_using_sql_cypher · search_graph · vector_search        │
│         list_cv_templates · generate_employee_cv                     │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  PGAgeHelper (psycopg connection pool)                    │        │
│  └──────────────────────┬───────────────────────────────────┘        │
└─────────────────────────┼────────────────────────────────────────────┘
                          │ libpq / TLS
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PostgreSQL + Apache AGE                                             │
│  ┌──────────────────┐  ┌───────────┐  ┌──────────────────────────┐  │
│  │ Graph (Cypher)    │  │ tsvector  │  │ DiskANN (vector index)   │  │
│  │ ag_catalog.cypher │  │ FTS index │  │ pgvector cosine          │  │
│  └──────────────────┘  └───────────┘  └──────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Request Flow

### 2.1 Primary Query Flow

```
sequenceDiagram
    participant UI as React SPA
    participant API as FastAPI Backend
    participant TRI as Triage Agent
    participant QA as Query Agent
    participant MCP as MCP Server
    participant DB as PostgreSQL/AGE

    UI->>API: POST /af/graph/responses {input, session_id} + Bearer JWT
    API->>API: Validate JWT (auth.py)
    API->>API: Build chat history (Cosmos DB)
    API->>API: CV template augmentation (if short reply)
    API->>TRI: run(messages, stream=True)
    TRI->>QA: handoff_to_query_agent(task)
    QA->>MCP: MCPStreamableHTTPTool → query_using_sql_cypher
    MCP->>DB: SQL/Cypher via PGAgeHelper
    DB-->>MCP: Result rows
    MCP-->>QA: Tool result (JSON)
    QA-->>TRI: AgentResponse
    TRI-->>API: Stream AgentResponseUpdate tokens
    API-->>UI: NDJSON stream (response_message wrappers)
```

### 2.2 Endpoint Map

| Method | Path | Auth | Response | Purpose |
|--------|------|------|----------|---------|
| `POST` | `/api/chat` | JWT | SSE `text/event-stream` | Primary chat (legacy endpoint) |
| `POST` | `/af/graph/responses` | JWT | NDJSON `application/x-ndjson` | Graph search with run-log streaming |
| `POST` | `/af/upload` | JWT | JSON | File upload + text extraction |
| `GET`  | `/health` | None | JSON | Health check |

---

## 3. FastAPI Application Structure

### 3.1 Lifespan

Defined in [talent_backend/talent_backend/api.py](../../talent_backend/talent_backend/api.py):

```python
@asynccontextmanager
async def lifespan(application: FastAPI):
    global _agent, _history
    _history = ChatHistoryStore()           # Cosmos DB client init
    _agent = await create_orchestrator()    # Agent graph construction + AzureCredential
    yield
```

Startup cost is dominated by:
1. `DefaultAzureCredential()` initialization (~200ms locally, faster on Azure with MI)
2. `MCPStreamableHTTPTool` handshake — no connection on init, first-call lazy
3. `ChatHistoryStore()` — Cosmos container create-if-not-exists (~500ms first run)

### 3.2 Middleware Stack

| Order | Middleware | Configuration |
|-------|-----------|---------------|
| 1 | `CORSMiddleware` | Origins: `localhost:3000`, `localhost:5173` + `127.0.0.1` variants. Methods: GET, POST. Headers: `*`. |

**Production recommendation:** Strip localhost origins. Add the App Service hostname and any custom domain. Consider adding `X-Request-ID` middleware for correlation.

### 3.3 Authentication

JWT validation in [talent_backend/talent_backend/auth.py](../../talent_backend/talent_backend/auth.py):

- **JWKS endpoint:** `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys`
- **Cache TTL:** 1 hour (in-memory)
- **Accepted issuers:** Both v1 (`sts.windows.net/{tenant}/`) and v2 (`login.microsoftonline.com/{tenant}/v2.0`)
- **Accepted audiences:** `https://ai.azure.com` (Foundry scope) and app client ID
- **Dev mode:** When `AZURE_TENANT_ID` is not set, auth is bypassed with synthetic user

---

## 4. SSE Streaming Protocol

### 4.1 `/api/chat` — Server-Sent Events

Events are formatted as standard SSE with named event types:

```
event: start
data: {"id": "msg_abc123", "session_id": "def456"}

event: delta
data: {"id": "msg_abc123", "text": "Based on "}

event: delta
data: {"id": "msg_abc123", "text": "the search results..."}

event: message
data: {"id": "msg_abc123", "role": "assistant", "text": "Full response text"}

event: error
data: {"message": "Agent streaming error"}

event: done
data: {"id": "msg_abc123", "session_id": "def456"}
```

| Event | When | Payload |
|-------|------|---------|
| `start` | Stream begins | `{id, session_id}` |
| `delta` | Each token chunk from `AgentResponseUpdate` | `{id, text}` |
| `message` | Final complete message from `AgentResponse` | `{id, role, text}` |
| `error` | Exception during streaming | `{message}` |
| `done` | Stream ends | `{id, session_id}` |

### 4.2 `/af/graph/responses` — NDJSON

Each line is a JSON object wrapped in `{"response_message": {...}}` for frontend compatibility. Event types are derived from agent framework log interception:

- **OrchestratorEvent** — agent handoff notifications
- **AgentEvent** — tool calls (CYPHER, FTS, VECTOR badges)
- **WorkflowOutputEvent** — final chat response text
- **done** — stream termination

The NDJSON endpoint also intercepts `agent_framework` logger output to surface MCP tool calls as structured run-log events (query type, SQL, row counts, timing).

---

## 5. Agent Framework Integration

### 5.1 Orchestrator Pattern

The `TalentIQOrchestrator` class ([talent_backend/talent_backend/agent/__init__.py](../../talent_backend/talent_backend/agent/__init__.py)) uses the **agent-as-tool handoff pattern**:

```
Triage Agent
  ├── handoff_to_document_agent  (text analysis, no MCP)
  ├── handoff_to_query_agent     (graph search via MCP)
  └── handoff_to_cv_agent        (CV generation via MCP)
```

Each specialist agent is registered as a callable tool on the triage agent via `agent.as_tool(propagate_session=True)`.

### 5.2 Agent Configuration

| Agent | Model Client | MCP Tools | History Provider |
|-------|-------------|-----------|------------------|
| Triage | `OpenAIChatCompletionClient` (Azure OpenAI) | None (uses handoff tools) | `InMemoryHistoryProvider` |
| Query | Same | `MCPStreamableHTTPTool` → `localhost:3002/mcp` | `InMemoryHistoryProvider` |
| Document | Same | None | `InMemoryHistoryProvider` |
| CV Generation | Same | `MCPStreamableHTTPTool` → `localhost:3002/mcp` | `InMemoryHistoryProvider` |

### 5.3 Session Management

- **Agent-level:** `InMemoryHistoryProvider` per agent instance (not shared across restarts)
- **Application-level:** Cosmos DB `ChatHistoryStore` stores full conversation (20-message cap per retrieval)
- **Gap:** Agent framework session state is lost on process restart. Cosmos stores raw messages but not agent internal state.

---

## 6. MCP Client Configuration

The backend connects to the MCP server via `MCPStreamableHTTPTool`:

```python
mcp_tool = MCPStreamableHTTPTool(
    name="talent_graph_mcp",
    url=MCP_ENDPOINT,  # default: http://localhost:3002/mcp
)
```

- **Protocol:** MCP Streamable HTTP transport (not stdio)
- **Connection:** HTTP, no auth between backend and MCP server (same host assumed)
- **Tool discovery:** MCP protocol's `tools/list` at connection time
- **Registered tools:** `query_using_sql_cypher`, `search_graph`, `vector_search`, `list_cv_templates`, `generate_employee_cv`

**Production consideration:** When backend and MCP are co-deployed on the same App Service, communication stays on `localhost`. If separated, the MCP endpoint must be secured (see VNet spec).

---

## 7. MCP Server Architecture

The MCP server ([talent_backend/talent_backend/mcp_server/](../../talent_backend/talent_backend/mcp_server/)) uses FastMCP with Starlette CORS middleware:

```
mcp_server/
  ├── app.py             # FastMCP instance + PGAgeHelper singleton
  ├── server.py          # Tool module aggregator (import triggers registration)
  ├── __main__.py         # Entry point, argparse, CORS, PGAgeHelper init
  ├── graph_tools.py      # query_using_sql_cypher, search_graph
  ├── vector_tools.py     # vector_search (Azure OpenAI embeddings)
  ├── cv_generator.py     # list_cv_templates, generate_employee_cv
  ├── pg_age_helper.py    # psycopg pool + AGE session config
  └── helpers.py          # AGType stripping, search word extraction
```

### 7.1 Database Access

`PGAgeHelper` manages a `psycopg_pool.AsyncConnectionPool` with:
- AGE extension loaded per connection (`LOAD 'age'; SET search_path = ag_catalog, ...`)
- Connection string from `app_config/.env` (PGHOST, PGPORT, etc.)
- SSL mode: `require` (default)

---

## 8. Configuration Management

All configuration is centralized in `app_config/.env`, loaded by [talent_backend/talent_backend/config.py](../../talent_backend/talent_backend/config.py):

| Category | Variables | Notes |
|----------|-----------|-------|
| PostgreSQL | `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`, `GRAPH_NAME` | Used by MCP server |
| MCP | `MCP_ENDPOINT` | Default `http://localhost:3002/mcp` |
| Backend | `BACKEND_HOST`, `BACKEND_PORT` | Default `0.0.0.0:8000` |
| Azure OpenAI | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, `AZURE_OPENAI_EMBEDDING_DIMENSIONS` | Chat + embeddings |
| Entra ID | `AZURE_TENANT_ID`, `ENTRA_SPA_CLIENT_ID`, `AZURE_TOKEN_AUDIENCE` | JWT validation |
| Cosmos DB | `COSMOS_CHAT_ENDPOINT`, `COSMOS_CHAT_DATABASE`, `COSMOS_CHAT_CONTAINER` | Chat history |

**Production:** These should map to App Service configuration / Key Vault references. Never commit `.env` to source control.

---

## 9. Error Handling and Resilience

### 9.1 Current Patterns

| Layer | Pattern | Implementation |
|-------|---------|----------------|
| Auth | 401 on invalid/missing JWT | `auth.py` raises `HTTPException` |
| Chat History | Graceful degradation | Cosmos failures fall back to in-memory dict |
| Agent Streaming | Exception catch-and-emit | SSE `error` event sent to client |
| File Upload | Validation | 400 if no text extracted |
| MCP Server | Database errors | Exceptions propagate as MCP tool errors to agent |

### 9.2 Gaps and Recommendations

| Gap | Risk | Recommendation |
|-----|------|----------------|
| No circuit breaker on MCP client | Backend blocks if MCP is down | Add timeout + retry with backoff on `MCPStreamableHTTPTool` |
| No request timeout on agent runs | Runaway LLM calls block thread | Add asyncio timeout wrapper (~60s) |
| No rate limiting | Abuse via repeated LLM calls | Add per-user rate limiter (token bucket) |
| JWKS fetch failure | Auth blocks all requests | Add fallback to cached keys, alert on fetch failure |
| In-memory history loss | Session data lost on restart | Ensure Cosmos is always available in prod |

---

## 10. Health Check and Readiness

### 10.1 Current State

```python
@app.get("/health")
async def health():
    return {"status": "healthy", "agent": _agent is not None}
```

No readiness probe. No deep health checks (DB, Cosmos, MCP connectivity).

### 10.2 Recommended Target

```python
@app.get("/health")          # Liveness probe — always 200 if process is alive
@app.get("/health/ready")    # Readiness probe — checks dependencies
```

Readiness should verify:
- Agent initialized (`_agent is not None`)
- Cosmos reachable (if configured)
- MCP server responsive (lightweight ping)
- PostgreSQL connectable (via MCP or direct probe)

---

## 11. Deployment Topology

### 11.1 Current (Local Dev)

```
localhost:5173 (Vite dev server, proxies /af → :8000)
localhost:8000 (FastAPI / uvicorn)
localhost:3002 (FastMCP / streamable-http)
```

All launched via `uv run python run_all.py`.

### 11.2 Target (Azure Production)

**Option A — Single App Service (recommended for initial deployment):**

```
Azure App Service (Linux, Python 3.11+)
  ├── Process 1: uvicorn talent_backend.api:app --port 8000
  ├── Process 2: python -m talent_backend.mcp_server --port 3002
  └── Static: talent_ui/ build output served via /static or separate Static Web App
```

Use a custom startup script or `gunicorn` with multiple worker processes. MCP stays on localhost:3002 — no network hop.

**Option B — Container Apps (scale-out):**

```
Container App: backend-api (scales 1-5)
Container App: mcp-server (scales 1-3)
Static Web App: talent-ui
```

MCP server would need internal FQDN or sidecar pattern. More complex but allows independent scaling.

### 11.3 Recommendation

Start with Option A. MCP communication is internal only (`localhost`), no auth needed. Move to Option B when scaling demands it or when MCP server becomes a bottleneck.

---

## 12. Dependency Management

### 12.1 uv Workspace

The repo uses a **uv workspace** rooted at [pyproject.toml](../../pyproject.toml):

```toml
[tool.uv.workspace]
members = ["talent_data_pipeline", "talent_backend"]
```

- **Root:** test dependencies (`pytest`, `psycopg2-binary`)
- **talent_backend:** all runtime deps (FastAPI, agent-framework, Azure SDK, etc.)
- **talent_data_pipeline:** data generation and loading tools

### 12.2 Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | ≥0.115 | HTTP API framework |
| `uvicorn[standard]` | ≥0.34 | ASGI server |
| `agent-framework` | ≥1.3.0 | Agent orchestration, MCP client |
| `fastmcp` | ≥2.0 | MCP server framework |
| `psycopg[binary]` | ≥3.2 | PostgreSQL async driver |
| `psycopg-pool` | ≥3.2 | Connection pooling |
| `azure-identity` | ≥1.19 | DefaultAzureCredential |
| `azure-cosmos` | ≥4.7 | Chat history persistence |
| `PyJWT[crypto]` | ≥2.8 | JWT validation |
| `httpx` | ≥0.27 | JWKS fetching |
| `python-docx` | ≥1.1 | CV DOCX generation |
| `PyMuPDF` | ≥1.24 | PDF text extraction |

### 12.3 Build System

Hatchling build backend with explicit package declaration:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["talent_backend"]
```

After any `pyproject.toml` change: `uv sync --all-packages`.

---

## Appendix A: File Reference

| File | Purpose |
|------|---------|
| `talent_backend/talent_backend/api.py` | FastAPI app, SSE/NDJSON endpoints |
| `talent_backend/talent_backend/__main__.py` | uvicorn entry point |
| `talent_backend/talent_backend/agent/__init__.py` | Orchestrator + agent graph |
| `talent_backend/talent_backend/auth.py` | Entra ID JWT validation |
| `talent_backend/talent_backend/chat_history.py` | Cosmos DB chat history |
| `talent_backend/talent_backend/config.py` | Centralized env var config |
| `talent_backend/talent_backend/file_handler.py` | PDF/DOCX text extraction |
| `talent_backend/talent_backend/mcp_server/__main__.py` | MCP server entry point |
| `talent_backend/talent_backend/mcp_server/app.py` | FastMCP instance |
| `talent_backend/talent_backend/mcp_server/graph_tools.py` | SQL/Cypher + FTS tools |
| `talent_backend/talent_backend/mcp_server/vector_tools.py` | Vector search tool |
| `talent_backend/talent_backend/mcp_server/cv_generator.py` | CV generation tools |
| `talent_backend/talent_backend/mcp_server/pg_age_helper.py` | PostgreSQL/AGE connection pool |
| `app_config/.env` | Centralized configuration |
| `run_all.py` | Local dev launcher |
