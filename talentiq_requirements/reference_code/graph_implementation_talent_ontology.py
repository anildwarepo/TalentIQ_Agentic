# sequential_pipeline.py — Generator → Format via SequentialBuilder
import asyncio
from agent_framework import (
    Agent,
    ChatContext,
    Message,
    ChatMiddleware,
    MCPStreamableHTTPTool,
    WorkflowEvent,
    AgentResponse,
    AgentResponseUpdate,
)
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity.aio import AzureCliCredential
import json
from enum import Enum
from dataclasses import dataclass, asdict, is_dataclass
from agent_framework import Message
from typing import Any, Awaitable, Callable, List, Optional
import time
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Monkey-patch: sanitize empty JSON-Schema sub-schemas (`{}`) that some
# models (e.g. gpt-oss-120b) reject.  Bare `list` fields in Pydantic
# produce `"items": {}` which triggers:
#   "JSON Schema not supported: could not understand the instance `{}`."
# ---------------------------------------------------------------------------
_SCHEMA_VALUED_KEYS = frozenset({
    "items", "additionalProperties", "contains",
    "if", "then", "else", "not",
    "propertyNames", "unevaluatedItems", "unevaluatedProperties",
})

def _sanitize_schema(obj: Any, _key: str | None = None) -> Any:
    """Recursively replace bare `{}` sub-schema values that strict endpoints reject."""
    if isinstance(obj, dict):
        if obj == {} and _key in _SCHEMA_VALUED_KEYS:
            return {"type": "string"}
        return {k: _sanitize_schema(v, _key=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_schema(item, _key=_key) for item in obj]
    return obj

# Schema sanitizer for strict endpoints (kept as utility, monkey-patch removed in 1.0.1)
# ---------------------------------------------------------------------------

logger = logging.getLogger("uvicorn.error")
_aoai_api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()

# Use AzureCliCredential for local development (skips IMDS probe delay)
try:
    credential = AzureCliCredential()
    _aoai_api_key = ""
    os.environ.pop("AZURE_OPENAI_API_KEY", None)
except Exception:
    credential = None
if not credential and not _aoai_api_key:
    logger.warning("Azure credentials not configured. Graph workflow (generic) will be unavailable.")
MCP_ENDPOINT = os.environ.get("MCP_ENDPOINT")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
GRAPH_NAME = os.environ.get("GRAPH_NAME", "talent_graph")


print("Using MCP_ENDPOINT:", MCP_ENDPOINT)
print("Using AZURE_OPENAI_ENDPOINT:", AZURE_OPENAI_ENDPOINT)
print("Using AZURE_DEPLOYMENT_NAME:", AZURE_DEPLOYMENT_NAME)
print("Using GRAPH_NAME:", GRAPH_NAME)

if not MCP_ENDPOINT:
    raise ValueError("MCP_ENDPOINT environment variable must be set")

def create_message_store():
    return None


def _read_instruction_file(file_name: str, graph_name: str) -> str:
    # Look in repo-root agent_instructions/ (one level up from af-backend/)
    instructions_path = Path(__file__).resolve().parent.parent / "agent_instructions" / file_name
    if not instructions_path.exists():
        # Fallback: same directory
        instructions_path = Path(__file__).resolve().parent / "agent_instructions" / file_name
    instructions = instructions_path.read_text(encoding="utf-8-sig")
    return instructions.replace("{{GRAPH_NAME}}", graph_name).replace("{GRAPH_NAME}", graph_name)


def _resolve_instruction_file(base_name: str, suffix: str, graph_name: str) -> str:
    """Try talent-graph-specific file first, then domain-specific, then generic."""
    instructions_dir = Path(__file__).resolve().parent.parent / "agent_instructions"
    if not instructions_dir.exists():
        instructions_dir = Path(__file__).resolve().parent / "agent_instructions"

    # Priority 1: Talent-graph-specific (e.g., TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md)
    if graph_name == "talent_graph":
        talent_file = instructions_dir / f"TALENT_GRAPH_{base_name.replace('CYPHER_', '')}{suffix}"
        if talent_file.exists():
            logger.info(f"Using talent-graph instructions: {talent_file.name}")
            return _read_instruction_file(talent_file.name, graph_name)

    # Priority 2: Domain-specific (e.g., *_meetings_graph_v2_v1.md)
    domain_file = instructions_dir / f"{base_name}_{graph_name}{suffix}"
    if domain_file.exists():
        logger.info(f"Using domain-specific instructions: {domain_file.name}")
        return _read_instruction_file(domain_file.name, graph_name)

    # Priority 3: Generic fallback
    generic_file = f"{base_name}_GENERIC{suffix}"
    logger.info(f"Using generic instructions: {generic_file}")
    return _read_instruction_file(generic_file, graph_name)


import re as _re

def _sanitize_output(text: str) -> str:
    """Clean up OSS model output: fix Unicode, strip leaked metadata, remove object refs."""
    if not text:
        return text

    # 1. Replace fancy Unicode whitespace/punctuation with ASCII
    text = (text
        .replace("\u202f", " ")   # narrow no-break space
        .replace("\u00a0", " ")   # no-break space
        .replace("\u2003", " ")   # em space
        .replace("\u2002", " ")   # en space
        .replace("\u2011", "-")   # non-breaking hyphen
        .replace("\u2010", "-")   # hyphen
        .replace("\u2013", "-")   # en dash
        .replace("\u2014", "-")   # em dash
        .replace("\u2018", "'")   # left single quote
        .replace("\u2019", "'")   # right single quote
        .replace("\u201c", '"')   # left double quote
        .replace("\u201d", '"')   # right double quote
        .replace("\u2026", "...")  # ellipsis
        .replace("\u2190", "<-")  # left arrow
        .replace("\u2192", "->")  # right arrow
    )

    # 2. Strip CJK bracket citations with JSON: 【{...}】 or 〔{...}〕 or ã€...ã€'
    text = _re.sub(r'[\u3010\u3014]\s*\{[^}]*\}\s*[\u3011\u3015]', '', text)
    # Also handle the garbled versions: ã€{...}ã€' ã€[...]ã€'
    text = _re.sub(r'\u3010[^\u3011]*\u3011', '', text)
    text = _re.sub(r'\u3014[^\u3015]*\u3015', '', text)
    # Catch remaining ã€...ã€' patterns (entity refs, numbers, ellipsis)
    text = _re.sub(r'\u3010[^\u3011]{0,200}\u3011', '', text)

    # 3. Strip raw Python object references
    text = _re.sub(r'<agent_framework\._types\.\w+ object at 0x[0-9a-fA-F]+>', '', text)

    # 4. Strip leaked function/source metadata in parens or brackets
    text = _re.sub(r'\{"source"\s*:\s*"functions\.[^"]*"[^}]*\}', '', text)

    # 5. Clean up extra whitespace left behind
    text = _re.sub(r'  +', ' ', text)
    text = _re.sub(r'\n\n\n+', '\n\n', text)

    # 6. Fix collapsed markdown tables — LLM sometimes emits all rows on one line
    #    Pattern: "|| Name | Email |" (double pipe = row boundary without newline)
    #    Also fix: "| value1 | value2 || value3 | value4 |" (missing newline between rows)
    if '||' in text and '|' in text:
        # Split on || that represents row boundaries (not inside code blocks)
        lines = text.split('\n')
        fixed_lines = []
        for line in lines:
            stripped = line.strip()
            # If line looks like a collapsed table (multiple || separators)
            if '||' in stripped and stripped.count('|') > 4:
                # Replace || with newline+| but preserve leading |
                parts = stripped.split('||')
                for j, part in enumerate(parts):
                    p = part.strip()
                    if not p:
                        continue
                    if not p.startswith('|'):
                        p = '| ' + p
                    if not p.endswith('|'):
                        p = p + ' |'
                    fixed_lines.append(p)
            else:
                fixed_lines.append(line)
        text = '\n'.join(fixed_lines)
    # 7. Ensure markdown table has separator row (|---|---|)
    #    react-markdown won't render a table without it
    lines = text.split('\n')
    new_lines = []
    for i, line in enumerate(lines):
        new_lines.append(line)
        stripped = line.strip()
        # If this looks like a header row (has pipes) and next line is NOT a separator
        if (stripped.startswith('|') and stripped.endswith('|')
                and stripped.count('|') >= 3):
            # Check if next line is a separator row
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if next_line and not _re.match(r'^\|[\s:\-|]+\|$', next_line):
                # Only add separator if we're the first pipe-row (header)
                # and the previous line is NOT also a pipe-row
                prev_line = new_lines[-2].strip() if len(new_lines) >= 2 else ''
                if not (prev_line.startswith('|') and prev_line.endswith('|')):
                    col_count = stripped.count('|') - 1
                    separator = '| ' + ' | '.join(['---'] * col_count) + ' |'
                    new_lines.append(separator)
    text = '\n'.join(new_lines)
    return text.strip()


# Keep backward compat alias
_sanitize_unicode = _sanitize_output


def _json_default(o):
    # Make dataclasses, Enums, and bytes JSON-serializable
    if is_dataclass(o) and not isinstance(o, type):
        return asdict(o)
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, bytes):
        return o.decode("utf-8", errors="replace")
    # Fallback: string representation
    return str(o)

def _ndjson(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, default=_json_default) + "\n").encode("utf-8")


@dataclass
class ResponseMessage:
    type: str
    delta: str | None = None
    message: str | None = None
    result: str | None = None


class LoggingChatMiddleware(ChatMiddleware):
    """Chat middleware that logs AI interactions."""

    async def process(
        self,
        context: ChatContext,
        next: Callable[[ChatContext], Awaitable[None]],
    ) -> None:
        # Pre-processing: Log before AI call
        print(f"[Chat Class] Sending {len(context.messages)} messages to AI")

        # Continue to next middleware or AI service
        await next(context)

        for i, message in enumerate(context.messages):
            content = message.text if message.text else str(message.contents)
            print(f"  Message {i + 1} ({message.role.value}): {content}")
        # Post-processing: Log after AI response
        print("[Chat Class] AI response received")

class GraphWorkflow():
    def __init__(self, graph_name: str | None = None, model_name: str | None = None, session_id: str | None = None):
        # stream state
        self._last_stream_agent_id: Optional[str] = None
        self._stream_line_open: bool = False
        self._output: Optional[str] = None

        # lazily populated runtime state
        self._access_token = None          
        self._graph_query_generator_agent = None      
        self._graph_query_validator_agent = None 
        self._response_generator_agent = None           
        self._graph_name = graph_name or GRAPH_NAME
        self._deployment_name = model_name or AZURE_DEPLOYMENT_NAME
        # Derive nano model name for non-critical agents
        self._nano_deployment_name = (self._deployment_name or "").replace("-mini", "-nano").replace("-nano-nano", "-nano")
        self._session_id = session_id


    async def logging_chat_middleware(
            context: ChatContext,
            next: Callable[[ChatContext], Awaitable[None]],
        ) -> None:
            """Chat middleware that logs AI interactions."""
            # Pre-processing: Log before AI call
            print(f"[Chat] Sending {len(context.messages)} messages to AI")

            # Continue to next middleware or AI service
            await next(context)

            # Post-processing: Log after AI response
            print("[Chat] AI response received")
    
    async def _get_fresh_token(self):
        """Fetch or refresh an access token (buffers 60s before expiry). Skipped when using API key."""
        if _aoai_api_key:
            return None
        now = int(time.time())
        logger.info(f"Fetching fresh token at time {now}")
        if self._access_token is None or (getattr(self._access_token, "expires_on", 0) - 60) <= now:
            self._access_token = await credential.get_token("https://cognitiveservices.azure.com/.default")
        return self._access_token

    def _chat_client_kwargs(self, token, **extra):
        """Build kwargs for OpenAIChatCompletionClient depending on auth mode."""
        base = dict(
            model=self._deployment_name,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            **extra,
        )
        if _aoai_api_key:
            base["api_key"] = _aoai_api_key
        else:
            base["credential"] = credential
        return base

    def _nano_client_kwargs(self, token, **extra):
        """Build kwargs using the nano model for non-critical agents."""
        base = dict(
            model=self._nano_deployment_name,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            **extra,
        )
        if _aoai_api_key:
            base["api_key"] = _aoai_api_key
        else:
            base["credential"] = credential
        return base
    
    async def _ensure_clients(self):
        """Create agents and the workflow exactly once (or after token refresh if you choose)."""
        logger.info("Ensuring clients are created or refreshed")
        token = await self._get_fresh_token()
        graph_age_mcp_server = MCPStreamableHTTPTool(
            name="graph age mcp server",
            url=MCP_ENDPOINT,
        ) 
        

        if self._graph_query_generator_agent is None or self._graph_query_validator_agent is None or self._response_generator_agent is None:
            
            # Select instruction files based on model capability
            _is_oss = any(kw in (self._deployment_name or "").lower() for kw in ("oss", "llama", "phi", "mistral", "deepseek", "codestral"))
            _instr_suffix = "_OSS_v1.md" if _is_oss else "_v1.md"
            logger.info(f"Model '{self._deployment_name}' (critical) / '{self._nano_deployment_name}' (non-critical)")
            logger.info(f"Graph: {self._graph_name}")

            # For talent_graph, use talent-specific instructions directly
            if self._graph_name == "talent_graph" and not _is_oss:
                graph_query_generator_instructions = _read_instruction_file(
                    "TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md", self._graph_name
                )
            else:
                graph_query_generator_instructions = _resolve_instruction_file(
                    "CYPHER_QUERY_GENERATION_AGENT", _instr_suffix, self._graph_name
                )

            self._graph_query_generator_agent = Agent(
                name="talent_graph_query_generator" if self._graph_name == "talent_graph" else "graph query generator agent",
                description="Generates Cypher queries for the DXC talent graph to search employees by skills, certifications, location, bench status, and more." if self._graph_name == "talent_graph" else "Graph query generator agent that can answer questions about the graph using a graph query tool.",
                instructions=graph_query_generator_instructions,
                client=OpenAIChatCompletionClient(**self._chat_client_kwargs(token)),
                tools=graph_age_mcp_server
            )

            # For talent_graph, use talent-specific validation instructions
            if self._graph_name == "talent_graph" and not _is_oss:
                graph_query_validator_instructions = _read_instruction_file(
                    "TALENT_GRAPH_QUERY_VALIDATION_AGENT_v1.md", self._graph_name
                )
            else:
                graph_query_validator_instructions = _resolve_instruction_file(
                    "CYPHER_QUERY_VALIDATION_AGENT", _instr_suffix, self._graph_name
                )

            self._graph_query_validator_agent = Agent(
                name="talent_graph_query_validator" if self._graph_name == "talent_graph" else "graph_query_validator",
                description="Validates and executes Cypher queries against the DXC talent graph, fixing AGE syntax issues." if self._graph_name == "talent_graph" else "Graph query validator agent that can validate and refine graph queries using a graph query tool.",
                instructions=graph_query_validator_instructions,
                client=OpenAIChatCompletionClient(**self._chat_client_kwargs(token)),
                tools=graph_age_mcp_server
            )

            self._response_generator_agent = Agent(
                name="response_generator_agent",
                description="Final response agent that formats talent search results into a concise answer.",
                instructions=_read_instruction_file(
                    "TALENT_GRAPH_RESPONSE_GENERATOR_AGENT_v1.md", self._graph_name
                ),
                client=OpenAIChatCompletionClient(**self._nano_client_kwargs(token)),
            )

            logger.info("Agents created successfully")

    async def run_workflow(self, chat_history: List[Message]):
        """Single-agent pipeline: generator generates Cypher, executes via MCP, formats results.

        Streams NDJSON events for the UI run-log.
        """
        await self._ensure_clients()
        user_query = chat_history[-1].text
        logger.info(f"Running single-agent pipeline for: {user_query}")

        yield _ndjson({"response_message": ResponseMessage(
            type="OrchestratorEvent",
            delta="[ORCH] Single-agent pipeline: generate → execute → format",
        )})

        output = None
        output_parts = []
        last_sent_len = 0
        start_time = time.time()

        try:
            result = self._graph_query_generator_agent.run(chat_history, stream=True)
            async for event in result:
                # Agent.run(stream=True) yields AgentResponseUpdate objects directly
                # (not WorkflowEvent wrappers). Text is on event.text.
                if isinstance(event, AgentResponseUpdate):
                    text = event.text or ""
                    if text:
                        output_parts.append(text)
                        current_len = sum(len(p) for p in output_parts)
                        if current_len - last_sent_len >= 100 or "\n" in text:
                            partial = _sanitize_output("".join(output_parts))
                            if partial:
                                yield _ndjson({"response_message": ResponseMessage(
                                    type="WorkflowOutputEvent", delta=partial,
                                )})
                                last_sent_len = current_len

                elif isinstance(event, AgentResponse):
                    # Complete response — extract final text and run-log items
                    for msg in (event.messages if hasattr(event, "messages") else []):
                        if msg and msg.text:
                            msg_text = msg.text
                            if "SELECT * FROM ag_catalog.cypher" in msg_text:
                                cypher_match = _re.search(
                                    r"(SELECT \* FROM ag_catalog\.cypher\(.+?\);)",
                                    msg_text, _re.DOTALL,
                                )
                                if cypher_match:
                                    yield _ndjson({"response_message": ResponseMessage(
                                        type="AgentEvent",
                                        delta=f"[QUERY] Cypher:\n```sql\n{cypher_match.group(1)}\n```",
                                    )})
                            if "Query returned" in msg_text:
                                row_match = _re.search(r"Query returned (\d+) rows", msg_text)
                                if row_match:
                                    yield _ndjson({"response_message": ResponseMessage(
                                        type="AgentEvent",
                                        delta=f"[RESULT] Query returned {row_match.group(1)} rows",
                                    )})
                            if not msg_text.startswith("SELECT") and "FINAL_SQL" not in msg_text:
                                output_parts = [msg_text]

            # Final output
            elapsed_s = time.time() - start_time
            if output_parts:
                output = _sanitize_output("".join(output_parts))
            logger.info(f"Sequential workflow done in {elapsed_s:.1f}s — output {len(output or '')} chars")

            if output:
                yield _ndjson({"response_message": ResponseMessage(
                    type="WorkflowOutputEvent", delta=output,
                )})

            yield _ndjson({"response_message": ResponseMessage(
                type="OrchestratorEvent",
                delta=f"[ORCH] Completed in {elapsed_s:.1f}s",
            )})
            yield _ndjson({"response_message": ResponseMessage(
                type="done", result=output,
            )})

        except asyncio.CancelledError:
            logger.warning("Sequential workflow cancelled (client disconnected).")
            return
        except BaseException as e:
            logger.exception("Sequential workflow failed")
            error_message = f"Workflow execution failed: {e}"
            yield _ndjson({"response_message": ResponseMessage(type="error", message=error_message)})
            yield _ndjson({"response_message": ResponseMessage(type="done", result=output)})



