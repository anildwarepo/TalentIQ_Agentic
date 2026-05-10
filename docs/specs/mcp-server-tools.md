# MCP Server Tools Spec

**Author:** Kane (Backend Dev)  
**Date:** 2026-05-10  
**Status:** Living document  
**Source:** [talent_backend/talent_backend/mcp_server/](../../talent_backend/talent_backend/mcp_server/)

---

## 1. Current State

The MCP server exposes graph query, full-text search, vector search, and CV generation tools to the agent orchestrator via FastMCP's Streamable HTTP transport.

### Architecture

```
Agent Framework
    │
    │  MCPStreamableHTTPTool (HTTP POST)
    ▼
┌────────────────────────────────────┐
│  FastMCP("TalentIQ Graph MCP")     │
│  Port 3002, streamable-http       │
│                                    │
│  ┌──────────────────────────────┐  │
│  │ graph_tools.py               │  │
│  │  ├─ query_using_sql_cypher   │  │
│  │  ├─ search_graph             │  │
│  │  └─ analyze_graph_statistics │  │
│  ├──────────────────────────────┤  │
│  │ vector_tools.py              │  │
│  │  └─ vector_search            │  │
│  ├──────────────────────────────┤  │
│  │ cv_generator.py              │  │
│  │  ├─ list_cv_templates        │  │
│  │  └─ generate_employee_cv     │  │
│  └──────────────────────────────┘  │
│                                    │
│  PGAgeHelper (async psycopg pool)  │
│  AzureOpenAI (embedding client)    │
└────────────────────────────────────┘
    │
    ▼
PostgreSQL + Apache AGE
```

### File Layout

| File | Role |
|------|------|
| [app.py](../../talent_backend/talent_backend/mcp_server/app.py) | FastMCP instance, shared `pg_helper` singleton |
| [server.py](../../talent_backend/talent_backend/mcp_server/server.py) | Module aggregator — imports tool modules to trigger `@mcp.tool` registration |
| [graph_tools.py](../../talent_backend/talent_backend/mcp_server/graph_tools.py) | `query_using_sql_cypher`, `search_graph`, `analyze_graph_statistics` |
| [vector_tools.py](../../talent_backend/talent_backend/mcp_server/vector_tools.py) | `vector_search` |
| [cv_generator.py](../../talent_backend/talent_backend/mcp_server/cv_generator.py) | `list_cv_templates`, `generate_employee_cv` |
| [pg_age_helper.py](../../talent_backend/talent_backend/mcp_server/pg_age_helper.py) | Async connection pool, AGE search_path, agtype parsing |
| [helpers.py](../../talent_backend/talent_backend/mcp_server/helpers.py) | Ontology cache, search helpers, agtype stripping |
| [__main__.py](../../talent_backend/talent_backend/mcp_server/__main__.py) | Entry point, PGAgeHelper init, CORS, argparse |

---

## 2. Tool Inventory

### 2.1 `query_using_sql_cypher`

**File:** `graph_tools.py`  
**Purpose:** Execute arbitrary SQL or SQL-wrapped Cypher queries against PostgreSQL + Apache AGE.

```python
@mcp.tool
async def query_using_sql_cypher(
    sql_query: str,      # SQL query (may contain ag_catalog.cypher calls)
    graph_name: str,     # Graph name for AGE cypher calls
    ctx: Context = None,
) -> list[dict]:
```

**Behavior:**
- Detects query type from SQL content: `CYPHER`, `FTS`, `VECTOR`, `SQL`
- Executes via `PGAgeHelper.query_using_sql_cypher()` (sets AGE `search_path`)
- Parses agtype values in results
- Emits structured `[QUERY]` and `[RESULT]` log tags via `ctx.info()`

**Return:** List of dicts — each dict is a result row with parsed values.

**Security:** SQL is passed through from the agent. The agent's instruction file constrains it to valid patterns. See Security section below.

---

### 2.2 `search_graph`

**File:** `graph_tools.py`  
**Purpose:** Full-text search across graph nodes using `public.search_graph_nodes()`.

```python
@mcp.tool
async def search_graph(
    search_term: str,         # Text to search for
    graph_name: str,          # Graph name
    label_filter: str = "",   # Optional node label filter
    max_results: int = 10,    # Max results (default 10)
    ctx: Context = None,
) -> dict:
```

**Behavior:**
1. Strips titles/honorifics from search term (`strip_titles_for_search`)
2. Builds SQL query against `public.search_graph_nodes()` with optional label filter
3. If no results, retries with progressively shorter search terms (removes trailing words)
4. Compacts results: full payload for first 3, minimal for rest
5. Name verification: filters results where all significant search words appear in the name

**Return:**
```python
{
    "results": [{"entity_id": ..., "node_label": ..., "name": ..., "payload": ...}],
    "label_summary": {"Employee": 5, "Skill": 2},
    "search_term": "Jessica Berry",
    "total_found": 7,
}
```

---

### 2.3 `vector_search`

**File:** `vector_tools.py`  
**Purpose:** Semantic similarity search via Azure OpenAI embeddings over employee data.

```python
@mcp.tool
async def vector_search(
    search_text: str,          # NL text (combine multi-role with ' | ')
    search_type: str = "resume",  # 'resume' or 'skills'
    limit: int = 10,           # Max results (1-100)
    ctx: Context = None,
) -> list[dict]:
```

**Behavior:**
1. Validates `search_type` against column whitelist (`_VALID_COLUMNS`)
2. Clamps `limit` to 1-100
3. Generates embedding via Azure OpenAI (sync call run in executor)
4. Executes parameterized vector query using `<=>` cosine distance operator
5. Joins `employee_embeddings` with `employee_fts` for name/title/summary

**Return:**
```python
[{
    "workday_id": "WD-001",
    "name": "Jane Doe",
    "job_title": "Senior Developer",
    "resume_summary": "...",
    "skills_text": "...",
    "certs_text": "...",
    "similarity": 0.8712,
}]
```

**Column Whitelist:**
```python
_VALID_COLUMNS = {
    "resume": "resume_embedding",
    "skills": "skills_embedding",
}
```
Only these two values are accepted for `search_type`. Any other value returns an error. The column name is interpolated into SQL but is safe because it comes from a fixed dict, not user input.

---

### 2.4 `list_cv_templates`

**File:** `cv_generator.py`  
**Purpose:** List available CV templates from the `template_docs` directory.

```python
@mcp.tool
async def list_cv_templates(
    ctx: Context = None,
) -> list[dict]:
```

**Return:**
```python
[{
    "id": "01 CV_Coordinador",
    "name": "01 CV Coordinador",
    "filename": "01 CV_Coordinador.docx",
    "format": "docx",
    "usable": True,
    "note": "DOCX — can generate CV",
}]
```

PDF templates are listed but marked `usable: false`.

---

### 2.5 `generate_employee_cv`

**File:** `cv_generator.py`  
**Purpose:** Generate a DOCX CV for an employee by querying the graph and filling a template.

```python
@mcp.tool
async def generate_employee_cv(
    employee_email: str,       # e.g., 'jessica.berry@dxc.com'
    graph_name: str,           # AGE graph name
    template_name: str = "",   # Template filename (empty = default)
    format: str = "docx",      # Output format
    anonymize: bool = False,   # Strip personal identifiers
    ctx: Context = None,
) -> dict:
```

**Behavior:**
1. Queries graph for: profile, skills, certifications, languages, education, work experience, location (7 separate Cypher queries)
2. Resolves template from `agent/template_docs/`
3. Rejects PDF templates with error + available DOCX list
4. Calls `_build_docx()` to generate DOCX file
5. Saves to `CV_OUTPUT_DIR` (default: `/tmp/talentiq_cvs`)
6. Returns download URL

**Return:**
```python
{
    "download_url": "http://localhost:8000/af/cv/files/CV_Jessica_Berry_abc123.docx",
    "filename": "CV_Jessica_Berry_abc123.docx",
    "employee": "Jessica Berry",
    ...
}
```

---

## 3. PGAgeHelper

**File:** [pg_age_helper.py](../../talent_backend/talent_backend/mcp_server/pg_age_helper.py)

### Connection Pool

```python
class PGAgeHelper:
    @classmethod
    async def create(cls, conninfo=None, min_size=2, max_size=10) -> PGAgeHelper
    @classmethod
    def create_deferred(cls, conninfo=None, min_size=2, max_size=10) -> PGAgeHelper
```

| Method | Pool opened | Use case |
|--------|-------------|----------|
| `create()` | Immediately (async) | Test scripts |
| `create_deferred()` | Lazily on first query | Production — pool opens in server's event loop |

### AGE Search Path

Every query sets `search_path = ag_catalog, "$user", public` before execution. This is required by Apache AGE to resolve `agtype` and cypher functions.

### Agtype Parsing

`_parse_agtype_value()` converts AGE result values:

| AGE Format | Python Result |
|-----------|---------------|
| `"some text"` | `"some text"` (str) |
| `123` | `123` (int) |
| `12.5::numeric` | `12.5` (float) |
| `true` / `false` | `True` / `False` |
| `["Label"]` | `"Label"` (str) |
| `{"key": "val"}` | `{"key": "val"}` (dict) |
| `null` | `None` |

### Pool Tuning

| Parameter | Default | Notes |
|-----------|---------|-------|
| `min_size` | 2 | Minimum idle connections |
| `max_size` | 10 | Maximum concurrent connections |
| Row factory | `dict_row` | All results as dicts |

Production recommendation: `min_size=5, max_size=20` for concurrent agent requests.

---

## 4. Security

### SQL Sanitization

```python
def _sanitize_sql_string(value: str) -> str:
    """Escape single quotes for safe SQL interpolation."""
    return value.replace("'", "''")
```

Used in `search_graph` (label_filter, search_term) and `generate_employee_cv` (email, graph_name).

**Limitation:** This is basic quote escaping, not parameterized queries. The `query_using_sql_cypher` tool accepts raw SQL from the agent. Security relies on:
1. The agent's instruction file constraining queries to valid patterns
2. The PostgreSQL user having read-only permissions on the graph
3. The MCP server being internal (not exposed to end users)

### Vector Search Column Whitelisting

```python
_VALID_COLUMNS = {"resume": "resume_embedding", "skills": "skills_embedding"}
```

The `search_type` parameter is validated against this fixed dict. Invalid values return an error without executing any SQL.

### Parameterized Queries (vector_search)

The vector search tool uses parameterized queries (`%s` placeholders) for the embedding value and limit. Only the column name is interpolated, and it comes from `_VALID_COLUMNS`.

---

## 5. MCP Transport

### Configuration

| Setting | Value |
|---------|-------|
| Transport | Streamable HTTP |
| Default port | 3002 |
| Default host | 0.0.0.0 |
| Endpoint | `/mcp` |
| CORS | All origins (`*`), exposes `Mcp-Session-Id` header |

### Entry Point

```bash
uv run python -m talent_backend.mcp_server
# or with options:
uv run python -m talent_backend.mcp_server --transport streamable-http --port 3002 --host 0.0.0.0
```

### Client Configuration

In the agent orchestrator:
```python
mcp_tool = MCPStreamableHTTPTool(
    name="talent_graph_mcp",
    url=MCP_ENDPOINT,  # default: http://localhost:3002/mcp
)
```

---

## 6. Logging & Observability

### Structured Log Tags

All tools emit structured tags via `ctx.info()` for the frontend run log panel:

| Tag | Format | Example |
|-----|--------|---------|
| `[QUERY]` | `[QUERY] {TYPE}: {details}` | `[QUERY] CYPHER: MATCH (e:Employee)...` |
| `[RESULT]` | `[RESULT] {TYPE} returned {n} rows ({ms}ms)` | `[RESULT] CYPHER returned 5 rows (42ms)` |
| `[cv]` | `[cv] {action}` | `[cv] Generating CV for jessica@dxc.com...` |

Query type detection (from SQL content):

| SQL Contains | Query Type |
|-------------|-----------|
| `ag_catalog.cypher` | `CYPHER` |
| `search_graph_nodes` | `FTS` |
| `embedding` or `vector` | `VECTOR` |
| (default) | `SQL` |

### Log File

MCP server logs to: `talent_backend/talent_backend/mcp_server/logs/mcp_server.log`

### Performance Profiling

Every tool call logs execution time:
```
[query] 5 rows in 42ms
[vector_search] embedding generated in 180ms
[vector_search] 10 rows in 35ms
```

---

## 7. Adding New Tools

### Step-by-Step

1. **Create the tool module** (e.g., `scoring_tools.py`):
   ```python
   from .app import mcp, _pg

   @mcp.tool
   async def score_candidates(
       criteria: Annotated[str, "Description of criteria"],
       ctx: Context = None,
   ) -> list[dict]:
       """Score candidates against provided criteria."""
       if ctx:
           await ctx.info("[QUERY] SCORING: ...")
       # implementation
       if ctx:
           await ctx.info(f"[RESULT] SCORING: {len(results)} candidates scored")
       return results
   ```

2. **Register in `server.py`**:
   ```python
   from . import scoring_tools  # noqa: F401
   ```

3. **No agent changes needed** — the MCP tool is automatically available to any agent using `MCPStreamableHTTPTool`.

4. **Update agent instructions** if the tool requires specific calling patterns.

---

## 8. Target State

### Planned Tools

| Tool | Purpose | Priority |
|------|---------|----------|
| `score_candidates` | Score candidates against RFP requirements with weighted criteria | High |
| `shortlist_candidates` | Create/manage persistent candidate shortlists | Medium |
| `export_report` | Generate Excel/PDF staffing reports | Medium |
| `notify_stakeholders` | Send email/Teams notifications on bench changes | Low |

### Production Hardening

| Area | Current | Target |
|------|---------|--------|
| SQL injection | Basic quote escaping | Parameterized queries for all tools |
| Rate limiting | None | Per-tool rate limits (vector_search: 10/min) |
| Caching | None | FTS result cache (60s TTL), ontology cache (already exists) |
| Health check | None | `/health` endpoint on MCP server with pool stats |
| Metrics | Log-based | OpenTelemetry spans per tool call |

### Migration Path

1. **Phase 1 (Current)**: 6 tools, basic security, log-based observability
2. **Phase 2**: Parameterized queries everywhere, health endpoint, scoring tool
3. **Phase 3**: OpenTelemetry integration, caching layer, shortlist + export tools
4. **Phase 4**: Rate limiting, notification tool, tool versioning

---

## 9. Configuration Reference

| Variable | Source | Default | Purpose |
|----------|--------|---------|---------|
| `MCP_ENDPOINT` | `app_config/.env` | `http://localhost:3002/mcp` | Agent → MCP URL |
| `PGHOST` | `app_config/.env` | `localhost` | PostgreSQL host |
| `PGPORT` | `app_config/.env` | `5432` | PostgreSQL port |
| `PGDATABASE` | `app_config/.env` | `postgres` | Database name |
| `PGUSER` | `app_config/.env` | (required) | Database user |
| `PGPASSWORD` | `app_config/.env` | (required) | Database password |
| `PGSSLMODE` | `app_config/.env` | `require` | SSL mode |
| `GRAPH_NAME` | `app_config/.env` | `talent_graph` | AGE graph name |
| `AZURE_OPENAI_ENDPOINT` | `app_config/.env` | (required) | For embedding generation |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | `app_config/.env` | `text-embedding-ada-002` | Embedding model |
| `AZURE_OPENAI_EMBEDDING_DIMENSIONS` | `app_config/.env` | `1536` | Embedding dimensions |
| `CV_OUTPUT_DIR` | env | `/tmp/talentiq_cvs` | Generated CV output path |
| `CV_DOWNLOAD_BASE` | env | `http://localhost:8000/af/cv/files` | CV download URL base |
