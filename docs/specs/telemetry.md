# Telemetry Specification

**Author:** Ripley (Lead Architect)
**Date:** 2026-05-10
**Status:** Draft
**Audience:** Engineering team, SRE, Product

---

## 1. Current State

### 1.1 Frontend Telemetry

The React SPA has Application Insights integration via [talent_ui/src/telemetry.js](../../talent_ui/src/telemetry.js):

| Function | App Insights API | What it captures |
|----------|-----------------|------------------|
| `trackUserQuery(query, backend)` | `trackEvent("UserQuery")` | User queries (first 200 chars) + backend type |
| `trackApiCallStart(endpoint)` | `trackDependencyData()` | HTTP call duration, status, success/failure |
| `trackQueryResponseTime(query, backend, duration, success)` | `trackMetric("QueryResponseTime")` | Response time per query |
| `trackWorkflowEvent(type, properties)` | `trackEvent("Workflow_*")` | Agent workflow events |
| `trackError(error, properties)` | `trackException()` | JavaScript errors |
| `trackEvent(name, properties)` | `trackEvent()` | Generic custom events |

**Configuration:**
- Connection string via `VITE_APPINSIGHTS_CONNECTION_STRING` env var
- Auto route tracking enabled
- Fetch tracking enabled (automatic dependency tracking for XHR/fetch)

### 1.2 Backend Telemetry

**There is no backend telemetry integration.** The backend uses Python's `logging` module with basic `StreamHandler` + `FileHandler` (MCP server). No traces, metrics, or structured logs are sent to Application Insights or any monitoring backend.

Current logging setup:

| Component | Logger Name | Output |
|-----------|-------------|--------|
| FastAPI backend | `talent_backend.api` | stdout |
| Auth module | `talent_backend.auth` | stdout |
| Agent orchestrator | `talent_backend.agent` | stdout |
| Chat history | `talent_backend.chat_history` | stdout |
| MCP server | `talent_mcp` | stdout + `mcp_server/logs/mcp_server.log` |

### 1.3 Gaps

| Gap | Impact |
|-----|--------|
| No backend distributed tracing | Cannot correlate frontend calls to backend processing to DB queries |
| No agent handoff visibility | No data on which agents are called, how often, latency per handoff |
| No MCP tool call metrics | No data on tool call frequency, success rate, latency |
| No token usage tracking | Cannot estimate Azure OpenAI cost per request |
| No structured logging | Logs are plain text, not queryable in Log Analytics |
| No correlation IDs | Frontend and backend telemetry are disconnected |
| No DB query performance data | No visibility into Cypher/SQL/Vector query latency at scale |
| No alerting | No alerts on error rates, latency spikes, or failures |

---

## 2. Target State — OpenTelemetry Integration

### 2.1 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  React SPA                                                   │
│  App Insights JS SDK → Application Insights resource         │
│  traceparent header on all API calls ────────────┐           │
└──────────────────────────────────────────────────┼───────────┘
                                                   │
┌──────────────────────────────────────────────────▼───────────┐
│  FastAPI Backend                                              │
│  OpenTelemetry Python SDK                                     │
│  ┌──────────────────────────────────────────────────────┐     │
│  │ Traces: request spans, agent spans, MCP call spans    │     │
│  │ Metrics: counters, histograms, gauges                 │     │
│  │ Logs: structured JSON with trace context               │     │
│  └──────────────────────┬───────────────────────────────┘     │
│                          │ OTLP / Azure Monitor exporter      │
└──────────────────────────┼───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│  MCP Server                                                    │
│  OpenTelemetry Python SDK                                      │
│  ┌──────────────────────────────────────────────────────┐      │
│  │ Traces: tool call spans, DB query spans               │      │
│  │ Metrics: query counts, latency histograms             │      │
│  └──────────────────────┬───────────────────────────────┘      │
│                          │ OTLP / Azure Monitor exporter       │
└──────────────────────────┼─────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Application Insights / Azure Monitor                         │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Traces   │  │ Metrics   │  │ Logs      │  │ Workbooks    │  │
│  │ (E2E)    │  │ (custom)  │  │ (struct.) │  │ (dashboards) │  │
│  └─────────┘  └──────────┘  └──────────┘  └──────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 SDK Selection

| Component | SDK | Exporter |
|-----------|-----|----------|
| React SPA | `@microsoft/applicationinsights-web` (existing) | Built-in App Insights |
| FastAPI Backend | `opentelemetry-sdk` + `azure-monitor-opentelemetry-exporter` | OTLP → App Insights |
| MCP Server | Same | OTLP → App Insights |

**Why OpenTelemetry over App Insights Python SDK:**
- Vendor-neutral instrumentation
- Richer auto-instrumentation for FastAPI, httpx, psycopg
- Same App Insights backend via Azure Monitor exporter
- Future flexibility to add Grafana/Prometheus exporters

---

## 3. Distributed Tracing

### 3.1 Trace Propagation

```
Frontend (traceparent header)
  └── POST /af/graph/responses
       └── Backend: api.chat span
            ├── auth.validate_jwt span
            ├── chat_history.get_history span
            └── agent.run span
                 ├── triage_agent.think span
                 └── handoff_to_query_agent span
                      ├── query_agent.think span
                      └── mcp.tool_call span
                           └── MCP Server: query_using_sql_cypher span
                                ├── pg_age_helper.execute span
                                └── db.query span (psycopg auto-instrumented)
```

### 3.2 W3C Trace Context

The frontend App Insights SDK automatically sets `traceparent` headers on fetch calls. The backend must:

1. Extract `traceparent` from incoming request headers
2. Create child spans under the extracted trace context
3. Propagate context to MCP server calls (MCPStreamableHTTPTool sends headers)

### 3.3 Implementation — Backend Initialization

Add to [talent_backend/talent_backend/__main__.py](../../talent_backend/talent_backend/__main__.py):

```python
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter, AzureMonitorMetricExporter, AzureMonitorLogExporter
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")

if conn_str:
    # Traces
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(
        BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=conn_str))
    )
    trace.set_tracer_provider(tracer_provider)

    # Metrics
    metric_reader = PeriodicExportingMetricReader(
        AzureMonitorMetricExporter(connection_string=conn_str),
        export_interval_millis=60000,
    )
    metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))

    # Logs
    logger_provider = LoggerProvider()
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(AzureMonitorLogExporter(connection_string=conn_str))
    )
    handler = LoggingHandler(logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)

    # Auto-instrumentation
    FastAPIInstrumentor.instrument()
    HTTPXClientInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=True)
```

### 3.4 Custom Spans

Add manual spans at key orchestration points:

```python
from opentelemetry import trace

tracer = trace.get_tracer("talent_backend.agent")

async def run(self, messages, session_id=None, stream=True):
    with tracer.start_as_current_span("agent.orchestrator.run") as span:
        span.set_attribute("session_id", session_id or "")
        span.set_attribute("message_count", len(messages))
        # ... existing code
```

### 3.5 Dependencies to Add

```toml
# In talent_backend/pyproject.toml
"opentelemetry-api>=1.25",
"opentelemetry-sdk>=1.25",
"azure-monitor-opentelemetry-exporter>=1.0.0b26",
"opentelemetry-instrumentation-fastapi>=0.46b0",
"opentelemetry-instrumentation-httpx>=0.46b0",
"opentelemetry-instrumentation-psycopg>=0.46b0",
"opentelemetry-instrumentation-logging>=0.46b0",
```

---

## 4. Metrics

### 4.1 Custom Metrics Definition

```python
from opentelemetry import metrics

meter = metrics.get_meter("talent_backend")

# Counters
request_counter = meter.create_counter(
    "talentiq.requests.total",
    description="Total API requests",
    unit="1",
)

agent_handoff_counter = meter.create_counter(
    "talentiq.agent.handoffs.total",
    description="Total agent handoffs by type",
    unit="1",
)

mcp_tool_call_counter = meter.create_counter(
    "talentiq.mcp.tool_calls.total",
    description="Total MCP tool calls by tool name",
    unit="1",
)

token_usage_counter = meter.create_counter(
    "talentiq.openai.tokens.total",
    description="Azure OpenAI token consumption",
    unit="tokens",
)

# Histograms
request_duration = meter.create_histogram(
    "talentiq.requests.duration",
    description="Request processing duration",
    unit="ms",
)

agent_run_duration = meter.create_histogram(
    "talentiq.agent.run.duration",
    description="Agent run duration (includes LLM + tool calls)",
    unit="ms",
)

db_query_duration = meter.create_histogram(
    "talentiq.db.query.duration",
    description="Database query execution time",
    unit="ms",
)

# Gauges
active_sessions = meter.create_up_down_counter(
    "talentiq.sessions.active",
    description="Currently active chat sessions",
    unit="1",
)
```

### 4.2 Metric Instrumentation Points

| Metric | Where to Instrument | Custom Dimensions |
|--------|-------------------|-------------------|
| `talentiq.requests.total` | `api.py` — each endpoint handler | `endpoint`, `status_code`, `user_oid` |
| `talentiq.agent.handoffs.total` | `agent/__init__.py` — when handoff tool is called | `agent_name`, `session_id` |
| `talentiq.mcp.tool_calls.total` | `mcp_server/graph_tools.py`, `vector_tools.py` | `tool_name`, `query_type` |
| `talentiq.openai.tokens.total` | Agent framework callback (if available) or response metadata | `model`, `agent_name`, `token_type` (prompt/completion) |
| `talentiq.requests.duration` | `api.py` — middleware or per-endpoint timer | `endpoint` |
| `talentiq.agent.run.duration` | `agent/__init__.py` — wrap `_triage_agent.run()` | `session_id` |
| `talentiq.db.query.duration` | `mcp_server/graph_tools.py` — already has `time.perf_counter()` | `query_type`, `row_count` |

---

## 5. Structured Logging

### 5.1 Log Format

Replace plain-text logging with structured JSON:

```python
import logging
import json

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "otelTraceID", ""),
            "span_id": getattr(record, "otelSpanID", ""),
        }
        # Merge extra fields
        for key in ("session_id", "agent_name", "tool_name", "query_type", "user_oid"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        return json.dumps(log_entry)
```

### 5.2 Correlation IDs

Every log entry must include:

| Field | Source | Purpose |
|-------|--------|---------|
| `trace_id` | OpenTelemetry context (auto-injected by `LoggingInstrumentor`) | Correlate with frontend App Insights |
| `span_id` | OpenTelemetry context | Identify specific operation |
| `session_id` | Chat request payload | Group by conversation |
| `user_oid` | JWT claims | Group by user |
| `request_id` | Generated per request | Unique request identifier |

### 5.3 Log Levels by Component

| Logger | Level | Rationale |
|--------|-------|-----------|
| `talent_backend.api` | INFO | Request lifecycle events |
| `talent_backend.auth` | WARNING | Auth failures only (INFO for JWKS refresh) |
| `talent_backend.agent` | INFO | Handoff events, run timing |
| `talent_backend.chat_history` | WARNING | Cosmos failures only |
| `talent_mcp` | INFO | Tool calls, query results, timing |
| `agent_framework` | WARNING | Framework internals (noisy at INFO) |

---

## 6. Custom Dimensions

All telemetry (traces, metrics, logs) should carry these custom dimensions where applicable:

| Dimension | Type | Example Values |
|-----------|------|---------------|
| `session_id` | string | `a1b2c3d4e5f6` |
| `agent_name` | string | `triage_agent`, `talent_query_agent`, `cv_generation_agent` |
| `tool_name` | string | `query_using_sql_cypher`, `vector_search`, `generate_employee_cv` |
| `query_type` | string | `CYPHER`, `FTS`, `VECTOR`, `SQL` |
| `model_deployment` | string | `gpt-4o` |
| `user_oid` | string | Entra ID object ID |
| `endpoint` | string | `/af/graph/responses`, `/api/chat` |
| `status_code` | int | `200`, `401`, `500` |
| `row_count` | int | Number of DB result rows |
| `token_count_prompt` | int | Prompt tokens consumed |
| `token_count_completion` | int | Completion tokens consumed |

---

## 7. Dashboard Recommendations

### 7.1 Azure Monitor Workbook: TalentIQ Operations

| Section | Visualizations | Data Source |
|---------|---------------|-------------|
| **Request Volume** | Time series: requests/min by endpoint | `customMetrics` |
| **Response Latency** | P50/P95/P99 histogram by endpoint | `customMetrics` |
| **Agent Handoffs** | Pie chart: handoffs by agent type | `customMetrics` |
| **Tool Calls** | Bar chart: calls by tool × query type | `customMetrics` |
| **Error Rate** | Time series: errors/min with status codes | `requests` |
| **Active Sessions** | Gauge: concurrent sessions | `customMetrics` |

### 7.2 Azure Monitor Workbook: AI Cost Tracking

| Section | Visualizations | Data Source |
|---------|---------------|-------------|
| **Token Usage** | Stacked area: prompt vs completion tokens over time | `customMetrics` |
| **Cost Estimate** | Table: estimated cost by model deployment | Computed from token counts × pricing |
| **Per-Query Cost** | Histogram: tokens per query | `customMetrics` |
| **Top Users** | Table: token consumption by user | `customMetrics` grouped by `user_oid` |

### 7.3 Azure Monitor Workbook: Database Performance

| Section | Visualizations | Data Source |
|---------|---------------|-------------|
| **Query Latency** | P50/P95 by query type (CYPHER/FTS/VECTOR) | `customMetrics` |
| **Query Volume** | Time series by type | `customMetrics` |
| **Slow Queries** | Table: queries > 2s with SQL text | `traces` filtered by duration |
| **Row Counts** | Distribution of result set sizes | `customMetrics` |

### 7.4 End-to-End Transaction View

Use Application Insights **Transaction Search** / **Application Map** to visualize:

```
Browser → FastAPI → Agent Framework → MCP Server → PostgreSQL
```

Each hop is a span in the distributed trace, visible in the end-to-end transaction detail view.

---

## 8. Cost Telemetry (Azure OpenAI)

### 8.1 Token Tracking

The Agent Framework's `AgentResponse` may include usage metadata. If not, intercept at the `OpenAIChatCompletionClient` level:

```python
# Pseudo-code — exact API depends on agent-framework version
async def _track_token_usage(response, agent_name: str):
    usage = getattr(response, "usage", None)
    if usage:
        token_usage_counter.add(
            usage.prompt_tokens,
            {"agent_name": agent_name, "token_type": "prompt", "model": model_name}
        )
        token_usage_counter.add(
            usage.completion_tokens,
            {"agent_name": agent_name, "token_type": "completion", "model": model_name}
        )
```

### 8.2 Cost Estimation

Maintain a pricing lookup (updated manually or via Azure Pricing API):

| Model | Prompt (per 1K tokens) | Completion (per 1K tokens) |
|-------|----------------------|---------------------------|
| GPT-4o | $0.005 | $0.015 |
| text-embedding-ada-002 | $0.0001 | N/A |

Log estimated cost as a custom metric: `talentiq.openai.cost.estimated` (USD).

---

## 9. SLA Monitoring and Alerting

### 9.1 SLIs (Service Level Indicators)

| SLI | Target | Measurement |
|-----|--------|-------------|
| **Availability** | 99.5% | Successful responses / total requests |
| **Latency (P95)** | < 10s | End-to-end response time (includes LLM) |
| **Error Rate** | < 1% | 5xx responses / total requests |
| **Agent Success Rate** | > 95% | Agent runs completing without error |

### 9.2 Alert Rules

| Alert | Condition | Severity | Action Group |
|-------|-----------|----------|-------------|
| High Error Rate | 5xx rate > 5% over 5 min | Sev 1 | Email + PagerDuty |
| Elevated Latency | P95 > 30s over 5 min | Sev 2 | Email |
| Auth Failures Spike | 401 count > 50 in 5 min | Sev 2 | Email (possible attack) |
| Cosmos DB Unavailable | Fallback-to-memory log count > 0 | Sev 3 | Email |
| Token Budget Exceeded | Daily token count > threshold | Sev 3 | Email |
| Agent Streaming Error | `error` event count > 10 in 5 min | Sev 2 | Email |

### 9.3 Alert KQL Examples

**High Error Rate:**
```kql
requests
| where timestamp > ago(5m)
| summarize total = count(), errors = countif(resultCode >= 500)
| extend error_rate = todouble(errors) / todouble(total)
| where error_rate > 0.05
```

**Slow Agent Responses:**
```kql
customMetrics
| where name == "talentiq.agent.run.duration"
| where timestamp > ago(1h)
| summarize p95 = percentile(value, 95) by bin(timestamp, 5m)
| where p95 > 30000
```

---

## 10. Performance Baselines and Budgets

### 10.1 Baselines (to be measured after instrumentation)

| Operation | Expected Baseline | Budget (P95) |
|-----------|------------------|--------------|
| JWT validation | 1-5ms | 50ms |
| Chat history retrieval | 50-200ms | 500ms |
| Agent triage decision | 500-2000ms (LLM) | 5s |
| Agent specialist run | 2-10s (LLM + tools) | 15s |
| MCP tool: Cypher query | 50-500ms | 2s |
| MCP tool: FTS search | 20-200ms | 1s |
| MCP tool: Vector search | 100-500ms (includes embedding) | 3s |
| MCP tool: CV generation | 2-5s (DOCX rendering) | 10s |
| End-to-end response | 3-15s | 30s |

### 10.2 Performance Budget Enforcement

After baselines are established:
1. Set alert rules for P95 exceeding 2× baseline
2. Review weekly in ops standup
3. Investigate any sustained regression
4. Track budget compliance in monthly report

---

## 11. Migration Path

### Phase 1: Backend OpenTelemetry SDK (Week 1)

| Step | Action | Files |
|------|--------|-------|
| 1.1 | Add OpenTelemetry dependencies to `talent_backend/pyproject.toml` | `pyproject.toml` |
| 1.2 | Add `APPLICATIONINSIGHTS_CONNECTION_STRING` to `app_config/.env` | `.env` |
| 1.3 | Initialize OTel in `__main__.py` with Azure Monitor exporter | `__main__.py` |
| 1.4 | Auto-instrument FastAPI, httpx, psycopg | `__main__.py` |
| 1.5 | Verify traces appear in Application Insights | App Insights portal |

### Phase 2: Custom Instrumentation (Week 2)

| Step | Action | Files |
|------|--------|-------|
| 2.1 | Add custom spans in `agent/__init__.py` for orchestrator and handoffs | `agent/__init__.py` |
| 2.2 | Add custom spans in `mcp_server/graph_tools.py`, `vector_tools.py` | MCP tool files |
| 2.3 | Add custom metrics (counters, histograms) | All instrumented files |
| 2.4 | Add structured logging formatter | `__main__.py` |
| 2.5 | Verify distributed trace stitching (frontend → backend → MCP) | App Insights transaction search |

### Phase 3: MCP Server Instrumentation (Week 2-3)

| Step | Action | Files |
|------|--------|-------|
| 3.1 | Initialize OTel in `mcp_server/__main__.py` | `__main__.py` |
| 3.2 | Auto-instrument psycopg for DB query spans | `__main__.py` |
| 3.3 | Add token usage tracking | Agent callback or response interceptor |
| 3.4 | Verify end-to-end trace: Browser → API → Agent → MCP → DB | App Insights |

### Phase 4: Dashboards and Alerts (Week 3)

| Step | Action |
|------|--------|
| 4.1 | Create TalentIQ Operations workbook |
| 4.2 | Create AI Cost Tracking workbook |
| 4.3 | Create Database Performance workbook |
| 4.4 | Configure alert rules (error rate, latency, token budget) |
| 4.5 | Establish baselines from first week of production data |

### Phase 5: Frontend Correlation (Week 4)

| Step | Action | Files |
|------|--------|-------|
| 5.1 | Verify `traceparent` header is propagated from App Insights JS SDK | Network tab inspection |
| 5.2 | Add `session_id` as custom dimension to frontend events | `telemetry.js` |
| 5.3 | Create end-to-end Application Map in App Insights | Portal configuration |
| 5.4 | Document operational runbook with dashboard links | `docs/runbook.md` |

---

## Appendix A: OpenTelemetry Package Reference

```
opentelemetry-api                          # Core API
opentelemetry-sdk                          # SDK (TracerProvider, MeterProvider)
azure-monitor-opentelemetry-exporter       # Azure Monitor exporter
opentelemetry-instrumentation-fastapi      # Auto-instrument FastAPI
opentelemetry-instrumentation-httpx        # Auto-instrument httpx (JWKS, MCP calls)
opentelemetry-instrumentation-psycopg      # Auto-instrument psycopg (DB queries)
opentelemetry-instrumentation-logging      # Inject trace context into log records
```

## Appendix B: Application Insights Resource Configuration

| Setting | Value |
|---------|-------|
| Workspace-based | Yes (Log Analytics workspace) |
| Sampling | Adaptive (start at 100%, scales down under load) |
| Retention | 90 days (default) |
| Daily cap | 5 GB (adjust based on volume) |
| Data export | None initially (add if needed for compliance) |
