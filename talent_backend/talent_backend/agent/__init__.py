"""TalentIQ Agent — Handoff Orchestrator.

Uses Agent Framework agent-as-tool pattern to orchestrate between:
  - Document Extraction Agent: processes uploaded documents
  - Query Agent: searches the talent graph via MCP
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_framework import Agent, AgentResponseUpdate, AgentResponse, AgentSession, Message, MCPStreamableHTTPTool, InMemoryHistoryProvider
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity.aio import DefaultAzureCredential

from talent_backend.config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_CHAT_DEPLOYMENT_NAME,
    GRAPH_NAME,
    MCP_ENDPOINT,
)

logger = logging.getLogger("talent_backend.agent")

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
            return OpenAIChatCompletionClient(
                model=AZURE_OPENAI_CHAT_DEPLOYMENT_NAME,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                credential=self._credential,
            )

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
            middleware=[history_provider],
        )

        # Query Agent — uses MCP tools for graph search
        query_instructions = _read_instructions("TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md")
        query_agent = Agent(
            name="talent_query_agent",
            description="Searches the DXC talent graph for employees by skills, certifications, location, bench status, and more.",
            instructions=query_instructions,
            client=_make_client(),
            tools=mcp_tool,
            middleware=[InMemoryHistoryProvider()],
        )

        # CV Generation Agent — uses MCP tools for template listing and CV generation
        cv_instructions = _read_instructions("CV_GENERATION_AGENT.md")
        cv_agent = Agent(
            name="cv_generation_agent",
            description="Generates professional CV/resume documents for employees with template selection.",
            instructions=cv_instructions,
            client=_make_client(),
            tools=mcp_tool,
            middleware=[InMemoryHistoryProvider()],
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
                description="Hand off to the Query Agent to search the talent graph for employees matching criteria.",
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
            middleware=[InMemoryHistoryProvider()],
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
