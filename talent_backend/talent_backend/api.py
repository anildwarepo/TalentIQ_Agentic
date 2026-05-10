"""TalentIQ Backend API — FastAPI with SSE streaming.

Single endpoint ``POST /api/chat`` that streams agent responses
as Server-Sent Events.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from agent_framework import AgentResponse, AgentResponseUpdate, Message
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from talent_backend.agent import create_orchestrator
from talent_backend.auth import get_current_user
from talent_backend.file_handler import extract_text
from talent_backend.chat_history import ChatHistoryStore
from talent_backend.config import BACKEND_HOST, BACKEND_PORT

logger = logging.getLogger("talent_backend.api")

# ── Runtime state ────────────────────────────────────────────

_agent = None
_history: ChatHistoryStore | None = None


# ── Lifespan ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    global _agent, _history
    init_start = time.perf_counter()
    _history = ChatHistoryStore()
    _agent = await create_orchestrator()
    init_ms = (time.perf_counter() - init_start) * 1000
    logger.info("TalentIQ backend ready — agent init %.0fms", init_ms)
    yield


# ── FastAPI app ──────────────────────────────────────────────

app = FastAPI(
    title="TalentIQ Backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Request / Response models ────────────────────────────────

class FileContext(BaseModel):
    filename: str
    content: str
    matches: list = []


class ChatRequest(BaseModel):
    input: str
    session_id: str | None = None
    file_context: FileContext | None = None


# ── SSE helpers ──────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Session history ──────────────────────────────────────────

def _build_chat_history(session_id: str, user_message: str) -> tuple[list[Message], str]:
    """Build agent_framework Message list from Cosmos history + new user message."""
    if not session_id:
        session_id = uuid.uuid4().hex[:16]

    # Store user message in Cosmos
    _history.add_message(session_id, "user", user_message)

    # Retrieve full history (capped at 20 messages)
    history = _history.get_history(session_id, limit=20)
    messages = [Message(role=m["role"], contents=[m["text"]]) for m in history]
    return messages, session_id


def _record_response(session_id: str, text: str):
    """Store assistant response in Cosmos."""
    _history.add_message(session_id, "assistant", text)


# ── CV template choice augmentation ──────────────────────────

def _augment_cv_template_choice(session_id: str | None, user_input: str) -> str:
    """If the user sends a short reply after a CV template list, augment it.

    Scans recent chat history for a template list prompt and an email.
    If found, rewrites e.g. "1" → "Generate CV for X using template Y".
    """
    if not session_id or len(user_input.strip()) > 40:
        return user_input  # not a short reply

    # Only trigger for very short inputs (numbers, template names, "default")
    stripped = user_input.strip().lower()
    if stripped not in ("1", "2", "3", "default", "any") and "cv" not in stripped and "coordinador" not in stripped and "template" not in stripped and "talentai" not in stripped:
        return user_input

    history = _history.get_history(session_id, limit=6)
    if not history:
        return user_input

    # Look for a recent assistant message with template list
    email = None
    templates = []
    for msg in reversed(history):
        text = msg.get("text", "")
        if msg.get("role") == "assistant" and "choose a template" in text.lower():
            # Extract email from the template list message
            email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', text)
            if email_match:
                email = email_match.group(0)
            # Extract template filenames (.docx only)
            templates = re.findall(r'`([^`]+\.docx)`', text)
            break
        # Also check user messages for the original email
        if msg.get("role") == "user" and not email:
            email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', text)
            if email_match:
                email = email_match.group(0)

    if not email or not templates:
        return user_input

    # Map user choice to template filename
    template = None
    if stripped in ("1", "default", "any") and len(templates) >= 1:
        template = templates[0]
    elif stripped == "2" and len(templates) >= 2:
        template = templates[1]
    elif stripped == "3" and len(templates) >= 3:
        template = templates[2]
    else:
        # Check if user typed a template name fragment
        for t in templates:
            if stripped.replace(" ", "") in t.lower().replace(" ", "").replace("_", ""):
                template = t
                break

    if template:
        augmented = f"Generate CV for {email} using template {template}"
        logger.info("CV template choice augmented: '%s' → '%s'", user_input.strip(), augmented)
        return augmented

    return user_input


# ── Streaming endpoint ───────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    """Stream agent response as Server-Sent Events."""
    logger.info("Chat request from %s (%s)", user.get("email"), user.get("oid"))
    response_id = f"msg_{uuid.uuid4().hex[:16]}"
    messages, session_id = _build_chat_history(req.session_id, req.input)

    return StreamingResponse(
        _stream_agent(messages, response_id, session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_agent(messages: list[Message], response_id: str, session_id: str):
    """Run the agent with streaming and yield SSE events."""
    # Start event
    yield _sse("start", {"id": response_id, "session_id": session_id})

    full_text = ""

    try:
        result = await _agent.run(messages, stream=True)
        async for event in result:
            if isinstance(event, AgentResponseUpdate):
                # Streaming token delta
                text = event.text or ""
                if text:
                    full_text += text
                    yield _sse("delta", {
                        "id": response_id,
                        "text": text,
                    })

            elif isinstance(event, AgentResponse):
                # Complete response — extract final messages
                for msg in getattr(event, "messages", []):
                    if msg.text:
                        full_text = msg.text
                        yield _sse("message", {
                            "id": response_id,
                            "role": "assistant",
                            "text": msg.text,
                        })

    except Exception as e:
        logger.exception("Agent streaming error")
        yield _sse("error", {"message": str(e)})

    # Record response in session history
    if full_text.strip():
        _record_response(session_id, full_text.strip())

    yield _sse("done", {"id": response_id, "session_id": session_id})


# ── Health ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "agent": _agent is not None}


# ── Graph responses endpoint (NDJSON) ────────────────────────

@app.post("/af/upload")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Upload a document and extract text. The agent handles analysis."""
    logger.info("File upload from %s: %s (%s)", user.get("email"), file.filename, file.content_type)

    content_bytes = await file.read()
    text = await extract_text(file.filename, content_bytes)

    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    # Truncate if too long (keep first 5000 chars for agent context)
    truncated = text[:5000] if len(text) > 5000 else text

    return {
        "content": truncated,
        "summary": f"Document '{file.filename}' processed ({len(text)} characters extracted).",
        "filename": file.filename,
        "char_count": len(text),
    }


@app.post("/af/graph/responses")
async def graph_responses(req: ChatRequest, user: dict = Depends(get_current_user)):
    """Stream agent response as NDJSON for the graph search frontend."""
    logger.info("Graph request from %s (%s): %s", user.get("email"), user.get("oid"), req.input[:100])
    response_id = f"msg_{uuid.uuid4().hex[:16]}"

    user_input = req.input
    if req.file_context:
        # Embed document content in the user message so it enters chat history
        user_input = (
            f"[Document context from '{req.file_context.filename}']\n"
            f"---BEGIN DOCUMENT---\n"
            f"{req.file_context.content[:4000]}\n"
            f"---END DOCUMENT---\n\n"
            f"User question: {req.input}"
        )

    # ── CV template choice augmentation ──────────────────────
    # If the user sends a short reply (number, template name) after a CV template
    # list was shown, augment the message with the email and template filename
    # so the triage agent can construct a proper handoff.
    user_input = _augment_cv_template_choice(req.session_id, user_input)

    messages, session_id = _build_chat_history(req.session_id, user_input)

    return StreamingResponse(
        _stream_graph(messages, response_id, session_id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_graph(messages: list[Message], response_id: str, session_id: str):
    """Run the agent and yield NDJSON events matching the frontend's expected format.

    The frontend expects:
      - OrchestratorEvent / AgentEvent → run log panel (ORCH/QUERY/RESULT badges)
      - WorkflowOutputEvent → chat bubble
      - done → signals completion

    AgentResponseUpdate only carries text tokens — no tool call info.
    We capture agent_framework log messages to surface tool calls in the run log.
    """

    def _ndjson(msg: dict) -> str:
        return json.dumps({"response_message": msg}, ensure_ascii=False) + "\n"

    full_text = ""

    # ── Capture agent_framework logs for tool call events ────
    import queue
    log_queue: queue.Queue[str] = queue.Queue()

    class _AgentLogHandler(logging.Handler):
        """Forward agent_framework log messages to the NDJSON stream."""
        def emit(self, record: logging.LogRecord):
            # Handle dict-format log records (agent_framework._mcp logs dicts)
            if hasattr(record, "msg") and isinstance(record.msg, dict):
                inner = record.msg.get("msg", "")
                if isinstance(inner, str) and inner:
                    msg = inner
                else:
                    return
            else:
                msg = record.getMessage()

            # Only capture interesting messages (tool calls, MCP events, structured tags)
            if any(kw in msg for kw in (
                "Function name:", "Function ",
                "[QUERY]", "[RESULT]", "[query]", "[search]",
                "handoff_to_", "succeeded", "failed",
            )):
                log_queue.put(msg)

    handler = _AgentLogHandler()
    handler.setLevel(logging.DEBUG)
    # Attach to agent_framework loggers
    af_logger = logging.getLogger("agent_framework")
    af_logger.addHandler(handler)

    # Handoff name mapping
    _handoff_names = {
        "document_agent": "Document Agent",
        "query_agent": "Query Agent",
        "cv_agent": "CV Agent",
        "search_agent": "Search Agent",
    }

    def _friendly_handoff(raw: str) -> str:
        """Extract agent name from handoff_to_xxx and return human-friendly label."""
        m = re.search(r"handoff_to_(\w+)", raw)
        if m:
            key = m.group(1)
            return _handoff_names.get(key, key.replace("_", " ").title())
        return "Agent"

    def _drain_log_events():
        """Yield NDJSON for any queued log messages."""
        events = []
        while not log_queue.empty():
            try:
                msg = log_queue.get_nowait()

                # ── Handoff detection (highest priority) ──
                if "handoff_to_" in msg:
                    agent_label = _friendly_handoff(msg)
                    if "succeeded" in msg:
                        delta = f"[HANDOFF] {agent_label} completed"
                    elif "Function name:" in msg:
                        delta = f"[HANDOFF] → {agent_label}"
                    else:
                        delta = f"[HANDOFF] → {agent_label}"
                    events.append(_ndjson({"type": "AgentEvent", "delta": delta}))

                # ── Structured [QUERY] / [RESULT] / [HANDOFF] tags ──
                elif "[QUERY]" in msg:
                    events.append(_ndjson({"type": "AgentEvent", "delta": msg}))
                elif "[RESULT]" in msg:
                    events.append(_ndjson({"type": "AgentEvent", "delta": msg}))
                elif "[HANDOFF]" in msg:
                    events.append(_ndjson({"type": "AgentEvent", "delta": msg}))

                # ── Legacy tool-call messages (only for tools WITHOUT structured logging) ──
                elif "Function name:" in msg:
                    # MCP tools emit their own [QUERY]/[RESULT] via ctx.info — skip duplicates
                    if not any(t in msg for t in ("vector_search", "query_using_sql_cypher", "search_graph", "analyze_graph_statistics", "generate_employee_cv", "list_cv_templates")):
                        events.append(_ndjson({"type": "AgentEvent", "delta": f"[QUERY] {msg}"}))
                elif "succeeded" in msg:
                    if not any(t in msg for t in ("vector_search", "query_using_sql_cypher", "search_graph", "analyze_graph_statistics", "generate_employee_cv", "list_cv_templates")):
                        events.append(_ndjson({"type": "AgentEvent", "delta": f"[RESULT] {msg}"}))

                # ── Everything else ──
                else:
                    events.append(_ndjson({"type": "OrchestratorEvent", "delta": msg}))
            except queue.Empty:
                break
        return events

    try:
        result = await _agent.run(messages, session_id=session_id, stream=True)
        async for event in result:
            # Drain any log events captured during processing
            for log_event in _drain_log_events():
                yield log_event

            if isinstance(event, AgentResponseUpdate):
                text = event.text or ""
                if text:
                    full_text += text
                    # Don't emit individual tokens — they flood the run log.
                    # The final text is sent as WorkflowOutputEvent below.

            elif isinstance(event, AgentResponse):
                for msg in getattr(event, "messages", []):
                    if msg.text:
                        full_text = msg.text

        # Drain any remaining log events
        for log_event in _drain_log_events():
            yield log_event

    except Exception as e:
        logger.exception("Graph streaming error")
        yield _ndjson({"type": "error", "message": str(e)})
    finally:
        af_logger.removeHandler(handler)

    # Send the final response to the chat bubble
    if full_text.strip():
        _record_response(session_id, full_text.strip())
        yield _ndjson({
            "type": "WorkflowOutputEvent",
            "delta": full_text.strip(),
        })

    yield _ndjson({
        "type": "done",
        "result": full_text.strip() or "(no response)",
        "session_id": session_id,
    })


# ── CV templates ─────────────────────────────────────────────

@app.get("/af/cv/templates")
async def list_cv_templates():
    """List available CV templates."""
    template_dir = Path(__file__).resolve().parent / "agent" / "template_docs"
    templates = []
    if template_dir.exists():
        for f in sorted(template_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in (".docx", ".pdf"):
                templates.append({
                    "id": f.stem,
                    "name": f.stem.replace("_", " ").replace("01 ", ""),
                    "filename": f.name,
                    "format": f.suffix.lower().lstrip("."),
                    "usable": f.suffix.lower() == ".docx",
                })
    return {"templates": templates}


@app.get("/af/cv/templates/{filename}")
async def download_template(filename: str):
    """Download/preview a CV template file."""
    template_dir = Path(__file__).resolve().parent / "agent" / "template_docs"
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = template_dir / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if filepath.suffix.lower() == ".pdf":
        media_type = "application/pdf"

    return FileResponse(path=str(filepath), filename=filename, media_type=media_type)


# ── CV download ──────────────────────────────────────────────

@app.get("/af/cv/files/{filename}")
async def download_cv(filename: str):
    """Download a generated CV file."""
    if not re.match(r'^CV_[\w]+_[a-f0-9]+\.docx$', filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    cv_dir = Path(os.getenv("CV_OUTPUT_DIR", "/tmp/talentiq_cvs"))
    filepath = cv_dir / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="CV not found")

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ── Session management ───────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    """List all chat sessions."""
    logger.info("List sessions for %s", user.get("email"))
    return _history.list_sessions()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    """Get conversation history for a session."""
    logger.info("Get session %s for %s", session_id, user.get("email"))
    return _history.get_history(session_id)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    """Delete a session and its history."""
    logger.info("Delete session %s by %s", session_id, user.get("email"))
    _history.delete_session(session_id)
    return {"deleted": session_id}
