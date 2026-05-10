"""TalentIQ Agent Framework Backend — OpenTelemetry + Azure Monitor instrumentation.

Comprehensive tracing for:
  - Agent orchestration lifecycle (plan generation, handoffs, agent turns)
  - MCP tool calls (cypher generation, query execution)
  - LLM chat completions (model, token counts, latency)
  - Workflow end-to-end duration per user query
  - Server initialization time
  - All exceptions
"""

import logging
import os
import time
from contextlib import contextmanager
from functools import wraps

from opentelemetry import trace, metrics, context as otel_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from azure.monitor.opentelemetry.exporter import (
    AzureMonitorTraceExporter,
    AzureMonitorMetricExporter,
    AzureMonitorLogExporter,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

logger = logging.getLogger(__name__)

# ── Connection string ────────────────────────────────────────
APPINSIGHTS_CONNECTION_STRING = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")

_SERVICE_NAME = "talentiq-agent-framework"
_SERVICE_VERSION = "1.0.0"

_tracer: trace.Tracer | None = None
_meter: metrics.Meter | None = None

# Custom metrics handles
_workflow_duration = None
_agent_turn_duration = None
_handoff_counter = None
_mcp_call_duration = None
_mcp_call_counter = None
_cypher_query_counter = None
_cypher_result_count = None
_llm_call_duration = None
_llm_token_counter = None
_error_counter = None
_orch_plan_counter = None
_request_counter = None
_request_duration = None
_server_init_duration = None
_active_sessions_counter = None


def get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(_SERVICE_NAME, _SERVICE_VERSION)
    return _tracer


def get_meter() -> metrics.Meter:
    global _meter
    if _meter is None:
        _meter = metrics.get_meter(_SERVICE_NAME, _SERVICE_VERSION)
    return _meter


def configure_telemetry(app):
    """Configure OTel tracing, metrics, and log export for the agent framework."""
    global _workflow_duration, _agent_turn_duration, _handoff_counter
    global _mcp_call_duration, _mcp_call_counter, _cypher_query_counter
    global _cypher_result_count, _llm_call_duration, _llm_token_counter
    global _error_counter, _orch_plan_counter, _request_counter
    global _request_duration, _server_init_duration, _active_sessions_counter

    resource = Resource.create({
        SERVICE_NAME: _SERVICE_NAME,
        SERVICE_VERSION: _SERVICE_VERSION,
        "service.namespace": "talentiq",
        "deployment.environment": "development",
    })

    # ── Tracing ──────────────────────────────────────────────
    trace_exporter = AzureMonitorTraceExporter(
        connection_string=APPINSIGHTS_CONNECTION_STRING,
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(tracer_provider)

    # ── Metrics ──────────────────────────────────────────────
    metric_exporter = AzureMonitorMetricExporter(
        connection_string=APPINSIGHTS_CONNECTION_STRING,
    )
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter, export_interval_millis=15000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # ── Logging ──────────────────────────────────────────────
    log_exporter = AzureMonitorLogExporter(
        connection_string=APPINSIGHTS_CONNECTION_STRING,
    )
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    handler = LoggingHandler(logger_provider=logger_provider)
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)

    # Suppress noisy Azure SDK internal loggers from being exported
    for _sdk_logger in (
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.core.pipeline.policies._universal",
        "azure.monitor.opentelemetry.exporter",
        "azure.monitor.opentelemetry.exporter.export._base",
        "azure.identity",
        "urllib3.connectionpool",
        "opentelemetry.sdk",
    ):
        logging.getLogger(_sdk_logger).setLevel(logging.WARNING)

    # ── Auto-instrument FastAPI ──────────────────────────────
    FastAPIInstrumentor.instrument_app(app)
    try:
        RequestsInstrumentor().instrument()
    except Exception:
        pass  # may already be instrumented

    # ── Custom metrics ───────────────────────────────────────
    meter = get_meter()

    _server_init_duration = meter.create_histogram(
        name="talentiq.af.server.init_duration",
        description="Server initialization time in milliseconds",
        unit="ms",
    )
    _request_counter = meter.create_counter(
        name="talentiq.af.request.count",
        description="Total requests to agent framework",
    )
    _request_duration = meter.create_histogram(
        name="talentiq.af.request.duration",
        description="End-to-end request duration in milliseconds",
        unit="ms",
    )
    _workflow_duration = meter.create_histogram(
        name="talentiq.af.workflow.duration",
        description="Agent orchestration workflow duration in milliseconds",
        unit="ms",
    )
    _agent_turn_duration = meter.create_histogram(
        name="talentiq.af.agent.turn_duration",
        description="Individual agent turn duration in milliseconds",
        unit="ms",
    )
    _handoff_counter = meter.create_counter(
        name="talentiq.af.agent.handoff.count",
        description="Total agent handoffs",
    )
    _mcp_call_duration = meter.create_histogram(
        name="talentiq.af.mcp.call_duration",
        description="MCP tool call duration in milliseconds",
        unit="ms",
    )
    _mcp_call_counter = meter.create_counter(
        name="talentiq.af.mcp.call.count",
        description="Total MCP tool calls",
    )
    _cypher_query_counter = meter.create_counter(
        name="talentiq.af.cypher.query.count",
        description="Total Cypher queries generated",
    )
    _cypher_result_count = meter.create_histogram(
        name="talentiq.af.cypher.result_count",
        description="Number of rows returned per Cypher query",
        unit="rows",
    )
    _llm_call_duration = meter.create_histogram(
        name="talentiq.af.llm.call_duration",
        description="LLM chat completion call duration in milliseconds",
        unit="ms",
    )
    _llm_token_counter = meter.create_counter(
        name="talentiq.af.llm.token.count",
        description="Total LLM tokens consumed",
    )
    _orch_plan_counter = meter.create_counter(
        name="talentiq.af.orchestration.plan.count",
        description="Total orchestration plans generated",
    )
    _error_counter = meter.create_counter(
        name="talentiq.af.error.count",
        description="Total errors across agent framework",
    )
    _active_sessions_counter = meter.create_up_down_counter(
        name="talentiq.af.session.active",
        description="Currently active user sessions",
    )

    logger.info("TalentIQ Agent Framework telemetry configured → Azure Monitor")


# ── Recording helpers ────────────────────────────────────────

def record_server_init(duration_ms: float):
    if _server_init_duration:
        _server_init_duration.record(duration_ms)


def record_request_start():
    if _request_counter:
        _request_counter.add(1)


def record_request_end(duration_ms: float, endpoint: str, status_code: int):
    attrs = {"endpoint": endpoint, "status_code": str(status_code)}
    if _request_duration:
        _request_duration.record(duration_ms, attrs)
    if status_code >= 400 and _error_counter:
        _error_counter.add(1, {"error.source": "http", "endpoint": endpoint})


def record_workflow_duration(duration_ms: float, graph_name: str, model: str):
    attrs = {"graph_name": graph_name, "model": model}
    if _workflow_duration:
        _workflow_duration.record(duration_ms, attrs)


def record_agent_turn(agent_name: str, duration_ms: float):
    if _agent_turn_duration:
        _agent_turn_duration.record(duration_ms, {"agent.name": agent_name})


def record_handoff(source: str, target: str):
    if _handoff_counter:
        _handoff_counter.add(1, {"handoff.source": source, "handoff.target": target})


def record_mcp_call(tool_name: str, duration_ms: float, success: bool):
    attrs = {"mcp.tool": tool_name, "mcp.success": str(success)}
    if _mcp_call_counter:
        _mcp_call_counter.add(1, attrs)
    if _mcp_call_duration:
        _mcp_call_duration.record(duration_ms, attrs)


def record_cypher_query(query_text: str, result_count: int, duration_ms: float):
    if _cypher_query_counter:
        _cypher_query_counter.add(1)
    if _cypher_result_count:
        _cypher_result_count.record(result_count)
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute("cypher.query", query_text[:500])
        span.set_attribute("cypher.result_count", result_count)
        span.set_attribute("cypher.duration_ms", duration_ms)


def record_llm_call(model: str, duration_ms: float, prompt_tokens: int = 0, completion_tokens: int = 0):
    attrs = {"llm.model": model}
    if _llm_call_duration:
        _llm_call_duration.record(duration_ms, attrs)
    if _llm_token_counter:
        if prompt_tokens:
            _llm_token_counter.add(prompt_tokens, {"llm.model": model, "token.type": "prompt"})
        if completion_tokens:
            _llm_token_counter.add(completion_tokens, {"llm.model": model, "token.type": "completion"})


def record_orch_plan(plan_type: str):
    if _orch_plan_counter:
        _orch_plan_counter.add(1, {"plan.type": plan_type})


def record_error(source: str, error_type: str, message: str):
    if _error_counter:
        _error_counter.add(1, {"error.source": source, "error.type": error_type})
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute("error.source", source)
        span.set_attribute("error.message", message[:500])


def record_session_start():
    if _active_sessions_counter:
        _active_sessions_counter.add(1)


def record_session_end():
    if _active_sessions_counter:
        _active_sessions_counter.add(-1)


# ── Span context managers ────────────────────────────────────

@contextmanager
def workflow_span(user_query: str, graph_name: str, session_id: str):
    """Create a parent span for the entire workflow execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span("talentiq.workflow") as span:
        span.set_attribute("user.query", user_query[:500])
        span.set_attribute("graph.name", graph_name)
        span.set_attribute("session.id", session_id)
        start = time.perf_counter()
        try:
            yield span
            span.set_status(trace.StatusCode.OK)
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            record_error("workflow", type(exc).__name__, str(exc))
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("workflow.duration_ms", elapsed_ms)


@contextmanager
def agent_span(agent_name: str, action: str = "turn"):
    """Create a child span for an individual agent turn."""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"talentiq.agent.{action}") as span:
        span.set_attribute("agent.name", agent_name)
        start = time.perf_counter()
        try:
            yield span
            span.set_status(trace.StatusCode.OK)
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            record_error("agent", type(exc).__name__, str(exc))
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("agent.duration_ms", elapsed_ms)
            record_agent_turn(agent_name, elapsed_ms)


@contextmanager
def mcp_tool_span(tool_name: str, endpoint: str = ""):
    """Create a child span for an MCP tool call."""
    tracer = get_tracer()
    with tracer.start_as_current_span("talentiq.mcp.tool_call") as span:
        span.set_attribute("mcp.tool", tool_name)
        span.set_attribute("mcp.endpoint", endpoint)
        start = time.perf_counter()
        success = True
        try:
            yield span
            span.set_status(trace.StatusCode.OK)
        except Exception as exc:
            success = False
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            record_error("mcp", type(exc).__name__, str(exc))
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("mcp.duration_ms", elapsed_ms)
            record_mcp_call(tool_name, elapsed_ms, success)


@contextmanager
def cypher_span(query_text: str = ""):
    """Create a child span for Cypher query generation/execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span("talentiq.cypher.query") as span:
        if query_text:
            span.set_attribute("cypher.query", query_text[:500])
        start = time.perf_counter()
        try:
            yield span
            span.set_status(trace.StatusCode.OK)
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            record_error("cypher", type(exc).__name__, str(exc))
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("cypher.duration_ms", elapsed_ms)


@contextmanager
def llm_span(model: str, agent_name: str = ""):
    """Create a child span for an LLM completion call."""
    tracer = get_tracer()
    with tracer.start_as_current_span("talentiq.llm.completion") as span:
        span.set_attribute("llm.model", model)
        if agent_name:
            span.set_attribute("agent.name", agent_name)
        start = time.perf_counter()
        try:
            yield span
            span.set_status(trace.StatusCode.OK)
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            record_error("llm", type(exc).__name__, str(exc))
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("llm.duration_ms", elapsed_ms)
