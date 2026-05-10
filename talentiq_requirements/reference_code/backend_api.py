"""TalentIQ Agent Framework Backend — Main Entry Point.

Uses HandoffBuilder for orchestrator → subagent routing and streams
intermediate agent messages to the UI via Server-Sent Events (SSE).

Usage:
    python main.py                    # Start on port 8088
"""

import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager

from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv(override=False)

# Add af-backend root to path so local modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_framework import Agent, AgentResponseUpdate
from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import HandoffBuilder
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.subagents import create_agents
from config import load_settings
from services.search_service import SearchService
from graph_implementation_talent_ontology import GraphWorkflow
from telemetry import (
    configure_telemetry,
    record_server_init,
    record_request_start,
    record_request_end,
    record_workflow_duration,
    record_handoff,
    record_orch_plan,
    record_error,
    record_session_start,
    record_session_end,
    workflow_span,
    agent_span,
    get_tracer,
)
from opentelemetry import trace

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("talentiq-af")

# Initialized at startup
_client: FoundryChatClient | None = None
_credential: DefaultAzureCredential | None = None

# Per-session conversation history: session_id → list of {role, text}
_sessions: dict[str, list[dict]] = {}


class ResponsesRequest(BaseModel):
    input: str
    stream: bool = False
    session_id: str | None = None


def _init_services(settings):
    """Initialize Azure AI Search services (only needed if using local tools)."""
    logger.info("Foundry: %s", settings.foundry_project_endpoint)
    logger.info("Model: %s", settings.foundry_model)


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _client, _credential

    init_start = time.perf_counter()
    settings = load_settings()
    _credential = DefaultAzureCredential()

    _init_services(settings)

    _client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.foundry_model,
        credential=_credential,
    )

    init_ms = (time.perf_counter() - init_start) * 1000
    record_server_init(init_ms)
    logger.info("TalentIQ Agent Framework backend ready (HandoffBuilder) — init %.0fms", init_ms)
    yield
    if _credential:
        await _credential.close()


def _create_workflow():
    """Create a fresh workflow per request to avoid stale tool-call state."""
    orchestrator, candidate_agent, demand_agent, matching_agent = create_agents(_client)
    return (
        HandoffBuilder(
            name="talentiq-handoff",
            participants=[orchestrator, candidate_agent, demand_agent, matching_agent],
        )
        .with_start_agent(orchestrator)
        .build()
    )


app = FastAPI(title="TalentIQ Agent Framework Backend", version="1.0.0", lifespan=lifespan)

# ── Telemetry ────────────────────────────────────────────────
configure_telemetry(app)


@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    """Capture per-request duration, status, and trace context."""
    record_request_start()
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        record_request_end(duration_ms, request.url.path, response.status_code)
        response.headers["X-Request-Duration-Ms"] = f"{duration_ms:.1f}"
        return response
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        record_request_end(duration_ms, request.url.path, 500)
        record_error("http", type(exc).__name__, str(exc))
        raise


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Request-Context", "X-Request-Duration-Ms"],
)


def _format_sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_input_with_history(session_id: str | None, user_message: str) -> tuple[str, str]:
    """Build input with conversation history and return (full_input, session_id)."""
    if not session_id:
        session_id = uuid.uuid4().hex[:16]

    if session_id not in _sessions:
        _sessions[session_id] = []

    history = _sessions[session_id]

    # Record user message
    history.append({"role": "user", "text": user_message})

    # Build context from history (exclude the current message — it's the input)
    if len(history) <= 1:
        return user_message, session_id

    # Format prior turns as context
    context_parts = ["[Conversation history]"]
    for msg in history[:-1]:
        role = msg["role"].capitalize()
        context_parts.append(f"{role}: {msg['text']}")
    context_parts.append("[Current question]")
    context_parts.append(user_message)

    return "\n".join(context_parts), session_id


def _record_response(session_id: str, response_text: str):
    """Record assistant response in session history."""
    if session_id in _sessions:
        _sessions[session_id].append({"role": "assistant", "text": response_text})


@app.post("/responses")
async def responses(req: ResponsesRequest):
    """OpenAI Responses API compatible endpoint with optional SSE streaming."""
    response_id = f"resp_{uuid.uuid4().hex[:24]}"
    full_input, session_id = _build_input_with_history(req.session_id, req.input)

    if req.stream:
        return StreamingResponse(
            _stream_workflow(full_input, response_id, session_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming: collect all output
    workflow = _create_workflow()
    try:
        result = workflow.run(full_input, stream=True)
        texts: list[str] = []
        current_text = ""
        current_speaker = None
        async for event in result:
            if event.type == "output":
                data = event.data
                if isinstance(data, AgentResponseUpdate):
                    speaker = data.author_name or data.role or "assistant"
                    if current_speaker and speaker != current_speaker and current_text.strip():
                        texts.append(current_text.strip())
                        current_text = ""
                    current_speaker = speaker
                    if data.text:
                        current_text += data.text
                elif hasattr(data, "messages"):
                    if current_text.strip():
                        texts.append(current_text.strip())
                        current_text = ""
                    for msg in data.messages:
                        if msg.text:
                            texts.append(msg.text)
                elif isinstance(data, list):
                    if current_text.strip():
                        texts.append(current_text.strip())
                        current_text = ""
                    for msg in data:
                        text = getattr(msg, "text", None)
                        role = getattr(msg, "role", "assistant")
                        if text and role != "user":
                            texts.append(text)
        if current_text.strip():
            texts.append(current_text.strip())

        output_text = "\n\n".join(texts) if texts else "(no response)"
    except Exception as e:
        logger.exception("Workflow error")
        output_text = f"Error processing request: {e}"

    _record_response(session_id, output_text)

    return {
        "id": response_id,
        "object": "response",
        "session_id": session_id,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output_text}],
            }
        ],
        "output_text": output_text,
    }


async def _stream_workflow(input_text: str, response_id: str, session_id: str):
    """Stream workflow events as SSE to the client.

    AgentResponseUpdate objects are streaming token deltas. We accumulate
    text per speaker and emit a complete message SSE when the speaker changes
    or the stream ends.
    """
    workflow = _create_workflow()
    current_speaker = None
    current_text = ""

    def _flush():
        """Yield accumulated text as an SSE message event."""
        nonlocal current_speaker, current_text
        if current_text.strip():
            msg = _format_sse("message", {
                "id": response_id,
                "role": "assistant",
                "speaker": current_speaker or "assistant",
                "text": current_text.strip(),
            })
            current_speaker = None
            current_text = ""
            return msg
        current_speaker = None
        current_text = ""
        return None

    try:
        result = workflow.run(input_text, stream=True)
        async for event in result:
            if event.type == "handoff_sent":
                # Flush any accumulated text before handoff
                flushed = _flush()
                if flushed:
                    yield flushed
                yield _format_sse("handoff", {
                    "source": event.data.source,
                    "target": event.data.target,
                })

            elif event.type == "output":
                data = event.data

                # AgentResponseUpdate — streaming token delta
                if isinstance(data, AgentResponseUpdate):
                    speaker = data.author_name or data.role or "assistant"
                    # If speaker changed, flush previous
                    if current_speaker and speaker != current_speaker:
                        flushed = _flush()
                        if flushed:
                            yield flushed
                    current_speaker = speaker
                    if data.text:
                        current_text += data.text

                # AgentResponse — complete message
                elif hasattr(data, "messages"):
                    flushed = _flush()
                    if flushed:
                        yield flushed
                    for msg in data.messages:
                        if msg.text:
                            speaker = getattr(msg, "author_name", None) or getattr(msg, "role", "assistant")
                            yield _format_sse("message", {
                                "id": response_id,
                                "role": "assistant",
                                "speaker": speaker,
                                "text": msg.text,
                            })

                # List[Message] — final conversation snapshot
                elif isinstance(data, list):
                    flushed = _flush()
                    if flushed:
                        yield flushed
                    for msg in data:
                        text = getattr(msg, "text", None)
                        role = getattr(msg, "role", "assistant")
                        speaker = getattr(msg, "author_name", None) or role
                        if text and role != "user":
                            yield _format_sse("message", {
                                "id": response_id,
                                "role": "assistant",
                                "speaker": speaker,
                                "text": text,
                            })

    except Exception as e:
        logger.exception("Workflow streaming error")
        yield _format_sse("error", {"message": str(e)})

    # Flush any remaining text
    flushed = _flush()
    if flushed:
        yield flushed

    # Record full response in session history
    if current_text.strip():
        _record_response(session_id, current_text.strip())

    yield _format_sse("done", {"id": response_id, "session_id": session_id})


# ---- Graph Workflow (talent_graph via MCP + AGE) ----

# Per-session graph workflows
_graph_sessions: dict[str, GraphWorkflow] = {}


class GraphRequest(BaseModel):
    input: str
    session_id: str | None = None
    graph_name: str | None = None
    model_name: str | None = None


@app.post("/graph/responses")
async def graph_responses(req: GraphRequest):
    """Stream graph query workflow results via NDJSON."""
    session_id = req.session_id or uuid.uuid4().hex[:16]

    # Reuse or create GraphWorkflow per session
    if session_id not in _graph_sessions:
        _graph_sessions[session_id] = GraphWorkflow(
            graph_name=req.graph_name,
            model_name=req.model_name,
            session_id=session_id,
        )
    gw = _graph_sessions[session_id]

    from agent_framework import Message
    chat_history = [Message(role="user", contents=[req.input])]

    async def _stream():
        record_session_start()
        tracer = get_tracer()
        with tracer.start_as_current_span("talentiq.graph.workflow") as span:
            span.set_attribute("user.query", req.input[:500])
            span.set_attribute("session.id", session_id)
            span.set_attribute("graph.name", req.graph_name or "talent_graph")
            span.set_attribute("model.name", req.model_name or "default")
            wf_start = time.perf_counter()
            try:
                async for chunk in gw.run_workflow(chat_history):
                    yield chunk
                span.set_status(trace.StatusCode.OK)
            except Exception as exc:
                span.set_status(trace.StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                record_error("graph_workflow", type(exc).__name__, str(exc))
                raise
            finally:
                wf_ms = (time.perf_counter() - wf_start) * 1000
                span.set_attribute("workflow.duration_ms", wf_ms)
                record_workflow_duration(wf_ms, req.graph_name or "talent_graph", req.model_name or "default")
                record_session_end()

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {"status": "healthy", "backend": "agent-framework"}


def main():
    import uvicorn

    port = int(os.environ.get("AF_BACKEND_PORT", "8088"))
    logger.info("Starting TalentIQ Agent Framework backend on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
