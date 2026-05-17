"""Per-question pipeline logger.

Captures the full pipeline trace for each user question — triage decision,
agent handoffs, MCP tool calls (query text, result count, duration), errors,
and final response — then writes everything to a per-question subfolder
under ``PIPELINE_LOG_DIR`` (default: ``query_logs/`` at the repo root).

Toggle via env var ``ENABLE_PIPELINE_LOGGING=true``.

Usage in a streaming endpoint::

    pl = PipelineLogger(session_id, user_question, user_id=user_oid)
    pl.add_event("triage", detail="handoff_to_query_agent")
    pl.add_query("cypher", sql_text, rows=25, duration_ms=1112)
    pl.set_response(full_text)
    await pl.flush()          # writes files; non-blocking (threadpool I/O)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("talent_backend.pipeline_logger")

# ── PII mask ─────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}")


def _mask_emails(text: str) -> str:
    """Replace email addresses with a masked version, e.g. j***@example.com."""
    def _replace(m: re.Match) -> str:
        addr = m.group(0)
        local, domain = addr.rsplit("@", 1)
        if len(local) <= 1:
            masked_local = "*"
        else:
            masked_local = local[0] + "***"
        return f"{masked_local}@{domain}"
    return _EMAIL_RE.sub(_replace, text)


def _sanitize(obj):
    """Deep-sanitize a JSON-serialisable object, masking emails in strings."""
    if isinstance(obj, str):
        return _mask_emails(obj)
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


# ── PipelineLogger ───────────────────────────────────────────

class PipelineLogger:
    """Collects pipeline events for a single user question and flushes to disk."""

    def __init__(
        self,
        session_id: str,
        question: str,
        *,
        user_id: str | None = None,
        log_dir: str | Path | None = None,
    ):
        self._enabled: bool = os.getenv("ENABLE_PIPELINE_LOGGING", "").lower() in ("true", "1", "yes")
        if not self._enabled:
            return

        self._session_id = session_id
        self._question = question
        self._user_id = user_id
        self._start = time.perf_counter()
        self._timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

        # Build folder path
        q_hash = hashlib.sha256(question.encode()).hexdigest()[:8]
        sid_short = (session_id or "nosession")[:12]
        folder_name = f"{self._timestamp}_{sid_short}_{q_hash}"

        base_dir = Path(log_dir) if log_dir else self._default_log_dir()
        self._folder = base_dir / folder_name
        self._queries_dir = self._folder / "queries"

        # Event list — ordered by wall-clock time
        self._events: list[dict] = []
        self._query_counter = 0
        self._response_text: str | None = None

    # ── Configuration ────────────────────────────────────────

    @staticmethod
    def _default_log_dir() -> Path:
        env = os.getenv("PIPELINE_LOG_DIR")
        if env:
            return Path(env)
        # Default: query_logs/ at the repo root (two levels up from this file)
        return Path(__file__).resolve().parents[2] / "query_logs"

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── Event collection ─────────────────────────────────────

    def add_event(
        self,
        step: str,
        *,
        detail: str = "",
        duration_ms: float | None = None,
        error: str | None = None,
        metadata: dict | None = None,
    ):
        """Record a pipeline step (triage, handoff, tool call, etc.)."""
        if not self._enabled:
            return
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        event: dict = {
            "seq": len(self._events) + 1,
            "elapsed_ms": round(elapsed_ms, 1),
            "step": step,
        }
        if detail:
            event["detail"] = detail
        if duration_ms is not None:
            event["duration_ms"] = round(duration_ms, 1)
        if error:
            event["error"] = error
        if metadata:
            event["metadata"] = metadata
        self._events.append(event)

    def add_query(
        self,
        query_type: str,
        query_text: str,
        *,
        params: dict | None = None,
        rows: int | None = None,
        duration_ms: float | None = None,
        success: bool = True,
        error: str | None = None,
    ):
        """Record a query (Cypher, SQL, vector search, FTS)."""
        if not self._enabled:
            return
        self._query_counter += 1
        query_record = {
            "query_number": self._query_counter,
            "query_type": query_type,
            "query_text": query_text,
            "success": success,
        }
        if params:
            query_record["params"] = params
        if rows is not None:
            query_record["result_count"] = rows
        if duration_ms is not None:
            query_record["duration_ms"] = round(duration_ms, 1)
        if error:
            query_record["error"] = error

        # Also add as a pipeline event
        self.add_event(
            f"query_{query_type.lower()}",
            detail=query_text[:200],
            duration_ms=duration_ms,
            error=error,
            metadata={"result_count": rows, "query_number": self._query_counter},
        )

        # Store separately for the queries/ subfolder
        if not hasattr(self, "_query_records"):
            self._query_records: list[dict] = []
        self._query_records.append(query_record)

    def set_response(self, text: str):
        """Set the final agent response text."""
        if not self._enabled:
            return
        self._response_text = text

    # ── Flush to disk ────────────────────────────────────────

    async def flush(self):
        """Write all log files to disk. Runs file I/O in a thread pool."""
        if not self._enabled:
            return
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._write_files)
        except Exception:
            logger.exception("Pipeline logger flush failed (non-fatal)")

    def _write_files(self):
        """Synchronous file writes — called from thread pool."""
        total_ms = (time.perf_counter() - self._start) * 1000

        # Create directories
        self._folder.mkdir(parents=True, exist_ok=True)
        self._queries_dir.mkdir(parents=True, exist_ok=True)

        # ── question.json ────────────────────────────────────
        question_data = _sanitize({
            "question": self._question,
            "session_id": self._session_id,
            "user_id": self._user_id,
            "timestamp": self._timestamp,
            "total_duration_ms": round(total_ms, 1),
        })
        self._write_json(self._folder / "question.json", question_data)

        # ── pipeline.json ────────────────────────────────────
        pipeline_data = _sanitize({
            "question": self._question[:200],
            "session_id": self._session_id,
            "timestamp": self._timestamp,
            "total_duration_ms": round(total_ms, 1),
            "step_count": len(self._events),
            "query_count": self._query_counter,
            "response_length": len(self._response_text) if self._response_text else 0,
            "steps": self._events,
        })
        self._write_json(self._folder / "pipeline.json", pipeline_data)

        # ── queries/ subfolder ───────────────────────────────
        query_records = getattr(self, "_query_records", [])
        for qr in query_records:
            ext = ".sql" if qr["query_type"] in ("CYPHER", "SQL", "FTS") else ".json"
            filename = f"query_{qr['query_number']:02d}_{qr['query_type'].lower()}{ext}"
            sanitized = _sanitize(qr)
            if ext == ".sql":
                # Write as commented SQL with metadata header
                header_lines = [
                    f"-- Query #{qr['query_number']}",
                    f"-- Type: {qr['query_type']}",
                    f"-- Success: {qr['success']}",
                ]
                if qr.get("result_count") is not None:
                    header_lines.append(f"-- Results: {qr['result_count']}")
                if qr.get("duration_ms") is not None:
                    header_lines.append(f"-- Duration: {qr['duration_ms']}ms")
                if qr.get("error"):
                    header_lines.append(f"-- Error: {_mask_emails(qr['error'])}")
                header_lines.append("")
                content = "\n".join(header_lines) + _mask_emails(qr["query_text"]) + "\n"
                (self._queries_dir / filename).write_text(content, encoding="utf-8")
            else:
                self._write_json(self._queries_dir / filename, sanitized)

        logger.info(
            "Pipeline log written: %s (%d steps, %d queries, %.0fms)",
            self._folder.name,
            len(self._events),
            self._query_counter,
            total_ms,
        )

    @staticmethod
    def _write_json(path: Path, data: dict):
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )


# ── Log-message parser ───────────────────────────────────────
# Hooks into the existing _AgentLogHandler messages to extract
# structured pipeline events without modifying the agent framework.

def parse_log_event(msg: str, pipeline: PipelineLogger):
    """Parse an agent_framework log message and add events to the pipeline logger."""
    if not pipeline.enabled:
        return

    # Handoff detection
    if "handoff_to_" in msg:
        m = re.search(r"handoff_to_(\w+)", msg)
        agent_name = m.group(1) if m else "unknown"
        if "succeeded" in msg:
            pipeline.add_event("handoff_complete", detail=agent_name)
        else:
            pipeline.add_event("handoff", detail=agent_name)
        return

    # Query events from MCP tools (structured tags)
    if "[QUERY]" in msg:
        # Extract query type and text: "[QUERY] CYPHER: SELECT ..."
        m = re.match(r".*\[QUERY\]\s*(\w+):\s*(.*)", msg, re.DOTALL)
        if m:
            pipeline.add_query(
                m.group(1),
                m.group(2).strip(),
                success=True,  # will be updated on [RESULT]
            )
        else:
            pipeline.add_event("query_start", detail=msg)
        return

    if "[RESULT]" in msg:
        # "[RESULT] CYPHER returned 25 rows (1112ms)"
        m = re.match(r".*\[RESULT\]\s*(\w+)[:\s]+returned?\s*(\d+)\s*(?:rows|results).*?(\d+(?:\.\d+)?)ms", msg)
        if m:
            pipeline.add_event(
                "query_result",
                detail=f"{m.group(1)}: {m.group(2)} rows",
                duration_ms=float(m.group(3)),
                metadata={"query_type": m.group(1), "result_count": int(m.group(2))},
            )
            # Update the last query record with result info
            query_records = getattr(pipeline, "_query_records", [])
            if query_records:
                last = query_records[-1]
                last["rows"] = int(m.group(2))
                last["result_count"] = int(m.group(2))
                last["duration_ms"] = float(m.group(3))
        else:
            pipeline.add_event("query_result", detail=msg)
        return

    if "[REWRITE]" in msg:
        pipeline.add_event("query_rewrite", detail=msg)
        return

    if "[REJECTED]" in msg:
        pipeline.add_event("query_rejected", detail=msg, error=msg)
        return

    # Tool calls
    if "Function name:" in msg:
        m = re.search(r"Function name:\s*(\S+)", msg)
        tool = m.group(1) if m else "unknown"
        pipeline.add_event("tool_call", detail=tool)
        return

    if "succeeded" in msg:
        m = re.search(r"Function\s+(\S+)\s+succeeded", msg)
        if m:
            pipeline.add_event("tool_success", detail=m.group(1))
        return

    # Generic
    pipeline.add_event("log", detail=msg[:200])
