"""TalentIQ Agent — Handoff Orchestrator.

Uses Agent Framework agent-as-tool pattern to orchestrate between:
  - Document Extraction Agent: processes uploaded documents
  - Query Agent: searches the talent graph via MCP
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from agent_framework import (
    Agent,
    AgentResponseUpdate,
    AgentResponse,
    AgentSession,
    ChatContext,
    InMemoryHistoryProvider,
    MCPStreamableHTTPTool,
    Message,
    chat_middleware,
)
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity.aio import DefaultAzureCredential

from talent_backend.config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_CHAT_DEPLOYMENT_NAME,
    GRAPH_NAME,
    MCP_ENDPOINT,
)

logger = logging.getLogger("talent_backend.agent")


# ── Diagnostic middleware ────────────────────────────────────
#
# Why this exists: when the LLM generates a tool_call whose name is unknown or
# whose arguments fail schema validation, agent_framework's
# ``_auto_invoke_function`` returns a function_result with ``exception`` set
# *before* the "Function name: X" log line fires. After 3 such silent
# rejections in a row the agent loop aborts with
# "Maximum consecutive function call errors reached (3)" and the user gets a
# generic "Sorry…" message — with no record of *what* the LLM tried to call.
#
# This middleware walks every assistant message produced by the chat client
# (both non-streaming responses and per-update streaming deltas) and logs the
# raw tool_call name + arguments. That gives us a forensic record of the
# LLM's actual output even when dispatch is rejected.


def _log_function_calls(messages: Iterable[Any] | None, source: str) -> None:
    """Log only the *first* fragment of each tool_call.

    In streaming mode the LLM emits one ``function_call`` content per
    argument token (``name`` and ``call_id`` are populated on the first
    fragment, then empty on the rest). We deduplicate by only logging
    fragments whose ``name`` is set, which gives us exactly one log line
    per LLM tool-call attempt.
    """
    if not messages:
        return
    for msg in messages:
        contents = getattr(msg, "contents", None) or ()
        for content in contents:
            if getattr(content, "type", None) != "function_call":
                continue
            name = getattr(content, "name", None)
            if not name:
                continue
            logger.info(
                "LLM tool_call (%s) name=%s call_id=%s args=%r",
                source,
                name,
                getattr(content, "call_id", None),
                getattr(content, "arguments", None),
            )


@chat_middleware
async def log_llm_tool_calls(
    context: ChatContext, call_next: Callable[[], Awaitable[None]]
) -> None:
    """Log every LLM-emitted tool_call so we can diagnose silent dispatch errors."""

    if context.stream:
        def _hook(update: Any) -> Any:
            try:
                _log_function_calls([update], "stream")
            except Exception as exc:  # pragma: no cover — never break the loop
                logger.debug("log_llm_tool_calls stream hook failed: %s", exc)
            return update

        context.stream_transform_hooks.append(_hook)

    await call_next()

    if not context.stream and context.result is not None:
        try:
            _log_function_calls(getattr(context.result, "messages", None), "response")
        except Exception as exc:  # pragma: no cover
            logger.debug("log_llm_tool_calls response inspect failed: %s", exc)

# ── Agent instructions ───────────────────────────────────────

_INSTRUCTIONS_DIR = Path(__file__).resolve().parent / "instructions"


def _read_instructions(filename: str) -> str:
    """Read an instruction file, substituting {{GRAPH_NAME}}."""
    path = _INSTRUCTIONS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Agent instruction file not found: {path}")
    text = path.read_text(encoding="utf-8-sig")
    return text.replace("{{GRAPH_NAME}}", GRAPH_NAME).replace("{GRAPH_NAME}", GRAPH_NAME)


# ── Handoff Orchestrator ─────────────────────────────────────

class TalentIQOrchestrator:
    """Handoff orchestrator using agent-as-tool pattern."""

    def __init__(self):
        self._triage_agent = None
        self._credential = None

    async def initialize(self):
        """Build the agent graph at startup."""
        self._credential = DefaultAzureCredential()

        def _make_client():
            client = OpenAIChatCompletionClient(
                model=AZURE_OPENAI_CHAT_DEPLOYMENT_NAME,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                credential=self._credential,
            )
            # Forward the underlying exception text back to the LLM so it can
            # self-correct schema/argument errors instead of silently retrying
            # the same bad call. Without this the model only sees
            # "Error: Argument parsing failed." and tends to repeat itself
            # until the consecutive-error guard aborts the loop.
            client.function_invocation_configuration["include_detailed_errors"] = True
            # Give the model one extra retry beyond the default of 3 — enough
            # for it to recover from a transient bad call after seeing the
            # detailed error, without allowing runaway loops.
            client.function_invocation_configuration[
                "max_consecutive_errors_per_request"
            ] = 5
            return client

        # MCP tool for graph queries
        mcp_tool = MCPStreamableHTTPTool(
            name="talent_graph_mcp",
            url=MCP_ENDPOINT,
        )

        # History provider — gives each agent per-session chat memory
        history_provider = InMemoryHistoryProvider()

        # Document Extraction Agent — no MCP tools, works on text
        doc_instructions = _read_instructions("DOCUMENT_EXTRACTION_AGENT.md")
        document_agent = Agent(
            name="document_extraction_agent",
            description="Extracts roles, skills, certifications, and requirements from uploaded documents.",
            instructions=doc_instructions,
            client=_make_client(),
            middleware=[history_provider, log_llm_tool_calls],
        )

        # Query Agent — uses MCP tools for graph search
        query_instructions = _read_instructions("TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md")
        query_agent = Agent(
            name="talent_query_agent",
            description="Searches the DXC talent graph for employees by skills, certifications, location, bench status, and more.",
            instructions=query_instructions,
            client=_make_client(),
            tools=mcp_tool,
            middleware=[InMemoryHistoryProvider(), log_llm_tool_calls],
        )

        # CV Generation Agent — uses MCP tools for template listing and CV generation
        cv_instructions = _read_instructions("CV_GENERATION_AGENT.md")
        cv_agent = Agent(
            name="cv_generation_agent",
            description="Generates professional CV/resume documents for employees with template selection.",
            instructions=cv_instructions,
            client=_make_client(),
            tools=mcp_tool,
            middleware=[InMemoryHistoryProvider(), log_llm_tool_calls],
        )

        # Triage Agent — orchestrates handoffs
        triage_instructions = _read_instructions("TRIAGE_AGENT.md")
        specialist_tools = [
            document_agent.as_tool(
                name="handoff_to_document_agent",
                description="Hand off to the Document Extraction Agent to analyze an uploaded document and extract requirements.",
                propagate_session=True,
            ),
            query_agent.as_tool(
                name="handoff_to_query_agent",
                description="Hand off to the Query Agent to search the talent graph for employees matching explicit criteria. RFP/tender matching requires uploaded document context or previously extracted requirements.",
                propagate_session=True,
            ),
            cv_agent.as_tool(
                name="handoff_to_cv_agent",
                description="Hand off to the CV Generation Agent to generate a professional CV/resume for an employee. Handles template selection.",
                propagate_session=True,
            ),
        ]

        self._triage_agent = Agent(
            name="triage_agent",
            description="Routes talent requests to the appropriate specialist agent.",
            instructions=triage_instructions,
            client=_make_client(),
            tools=specialist_tools,
            middleware=[InMemoryHistoryProvider(), log_llm_tool_calls],
        )

        logger.info(
            "Orchestrator initialized: model=%s mcp=%s graph=%s",
            AZURE_OPENAI_CHAT_DEPLOYMENT_NAME,
            MCP_ENDPOINT,
            GRAPH_NAME,
        )

    async def run(self, messages: list[Message], session_id: str | None = None, stream: bool = True):
        """Run the orchestrator. Returns an async generator of events."""
        if not self._triage_agent:
            raise RuntimeError("Orchestrator not initialized — call initialize() first")
        session = AgentSession(session_id=session_id) if session_id else None
        return self._triage_agent.run(messages, stream=stream, session=session)


async def create_orchestrator() -> TalentIQOrchestrator:
    """Create and initialize the orchestrator."""
    orch = TalentIQOrchestrator()
    await orch.initialize()
    return orch
