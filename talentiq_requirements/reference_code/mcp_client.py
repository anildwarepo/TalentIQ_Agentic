import asyncio
import uuid
import re
import json
import sys
import os
from contextlib import AsyncExitStack
from typing import Optional

from fastapi import params
import httpx
from mcp import ClientSession, ListToolsResult
from mcp.client.streamable_http import streamablehttp_client
from collections import defaultdict
from sse_bus import SESSIONS, sse_event, JSONRPC, publish_progress, publish_message, publish_mcplog, associate_user_session, session_for_user, publish_elicitation
from shared.models import parse_notification_json, ProgressNotification, MessageNotification
import mcp.types as types
from mcp.shared.session import RequestResponder   

class MCPClient:
    def __init__(self, mcp_endpoint: str):
        self.mcp_endpoint = mcp_endpoint
        self.exit_stack: Optional[AsyncExitStack] = None
        self.session: Optional[ClientSession] = None
        self.session_id: Optional[str] = None
        self.mcp_tools: Optional[ListToolsResult] = None
        self._sse_task: Optional[asyncio.Task] = None
        self._broadcast_session_id: str | None = None


    async def _on_incoming(
        self,
        msg: RequestResponder[types.ServerRequest, types.ClientResult]
            | types.ServerNotification
            | Exception,
    ) -> None:
        # Errors from the stream
        if isinstance(msg, Exception):
            print(f"[mcp] incoming exception: {msg!r}", file=sys.stderr)
            return

        # Server requests (sampling/elicitation/etc).
        if isinstance(msg, RequestResponder):
            # Elicitation requests are handled by elicitation_callback (see connect()).
            # Other server requests (sampling, etc.) — ignore.
            return

        # Server notifications (what you want)
        if isinstance(msg, types.ServerNotification):
            root = msg.root
            method = getattr(root, "method", None)
            params = getattr(root, "params", None)

            # Build the JSON shape your existing parser expects
            if hasattr(params, "model_dump"):
                params_json = params.model_dump(mode="json")
            else:
                params_json = params

            payload = {"jsonrpc": "2.0", "method": method, "params": params_json}

            try:
                notif = parse_notification_json(json.dumps(payload))
            except Exception as e:
                print(f"[mcp] notification parse error: {e}", file=sys.stderr)
                return

            # PROGRESS
            if isinstance(notif, ProgressNotification):
                pct   = float(notif.params.progress)
                token = notif.params.progressToken
                target = session_for_user(notif.user_id) or self._broadcast_session_id
                if target:
                    await self._broadcast_progress(pct, target, token)
                return

            # MESSAGE
            if isinstance(notif, MessageNotification):
                target = session_for_user(notif.user_id) or self._broadcast_session_id
                texts  = [d.text for d in notif.params.data]
                level  = notif.params.level
                if target:
                    await self._broadcast_assistant(" ".join(t for t in texts if t), level, target)
                    await self._broadcast_mcplog(" ".join(t for t in texts if t), level, target)
                return

    async def _broadcast_progress(self, progress: float, target: Optional[str] = None, token: Optional[str] = None) -> None:
        target = target or self._broadcast_session_id
        print(f"mcp_client.py _broadcast_progress session_id {target}")
        if target:
            await publish_progress(target, token, progress)

    async def _broadcast_assistant(self, text: str, level: Optional[str] = None, target: Optional[str] = None) -> None:
        target = target or self._broadcast_session_id
        print(f"mcp_client.py _broadcast_assistant session_id {target}")
        if target:
            await publish_message(target, text, level)

    async def _broadcast_mcplog(self, text: str, level: Optional[str] = None, target: Optional[str] = None) -> None:
        target = target or self._broadcast_session_id
        print(f"mcp_client.py _broadcast_mcplog session_id {target}")
        if target:
            await publish_mcplog(target, text, level or "info")

    def set_broadcast_session(self, session_id: str) -> None:
        self._broadcast_session_id = session_id

    async def _handle_elicitation(self, context, params) -> types.ElicitResult:
        """
        Handle MCP elicitation/create requests from the server.
        Auto-accepts with the first valid option from the schema.
        Broadcasts the elicitation message to the UI for visibility.
        """
        message = params.message
        schema = params.requestedSchema or {}

        # Broadcast the elicitation message so the user sees it in the UI
        target = self._broadcast_session_id
        if target:
            await self._broadcast_mcplog(f"[elicitation] {message}", "info", target)

        # Auto-accept: pick the first option from enum schema if available
        content = {}
        props = schema.get("properties", {})
        for key, prop_schema in props.items():
            if "enum" in prop_schema and prop_schema["enum"]:
                content[key] = prop_schema["enum"][0]
            elif prop_schema.get("type") == "boolean":
                content[key] = True
            elif prop_schema.get("type") == "string":
                content[key] = prop_schema.get("default", "")
            elif prop_schema.get("type") in ("number", "integer"):
                content[key] = prop_schema.get("default", 0)

        if target:
            await self._broadcast_mcplog(
                f"[elicitation] Auto-accepted: {content}", "info", target
            )

        return types.ElicitResult(action="accept", content=content)

    async def connect(self, session_id: str, start_sse: bool = False) -> None:
        """
        Open the Streamable HTTP JSON-RPC channel (and optional SSE listener)
        and list tools. Must be closed via `await aclose()` from the same task.
        """
        self.exit_stack = AsyncExitStack()
        await self.exit_stack.__aenter__()  # enter now; we'll explicitly aclose later
        self.session_id = session_id #str(uuid.uuid4())
        headers = {"Mcp-Session-Id": self.session_id}

        # JSON-RPC duplex channel over Streamable HTTP
        streamable_http_client = streamablehttp_client(url=self.mcp_endpoint, headers=headers)
        read, write, _ = await self.exit_stack.enter_async_context(streamable_http_client)

        # Create the JSON-RPC session on the same exit stack
        #self.session = await self.exit_stack.enter_async_context(ClientSession(read, write))
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(
                read, write,
                message_handler=self._on_incoming,
                elicitation_callback=self._handle_elicitation,
            )
        )
        
        await self.session.initialize()
        await self.session.send_ping()

        self.session._message_handler
        # Discover tools
        self.mcp_tools = await self.session.list_tools()

    async def aclose(self) -> None:
        """
        Close SSE (if running) and the AsyncExitStack that owns the stream,
        **from the same task** that created it.
        """
        # Stop SSE first so the HTTP GET isn’t dangling
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            finally:
                self._sse_task = None

        if self.exit_stack is not None:
            # This ensures the async generator context is closed in the same task
            await self.exit_stack.aclose()
            self.exit_stack = None


# ---------------------------------------------------------------------------
# MCPStreamableHTTPTool subclass that routes ctx.info() / ctx.warning() etc.
# from the MCP server to the SSE bus so the frontend MCP log panel can show them.
# ---------------------------------------------------------------------------

from agent_framework import MCPStreamableHTTPTool
import mcp.types as _mcp_types
from mcp import ClientSession as _ClientSession
from datetime import timedelta as _timedelta


class LoggingMCPStreamableHTTPTool(MCPStreamableHTTPTool):
    """MCPStreamableHTTPTool that forwards MCP server log messages to the SSE bus
    and adds elicitation support."""

    def __init__(self, *args, broadcast_session_id: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._broadcast_session_id = broadcast_session_id

    def set_broadcast_session(self, session_id: str) -> None:
        self._broadcast_session_id = session_id

    async def _handle_elicitation(self, context, params: _mcp_types.ElicitRequestParams) -> _mcp_types.ElicitResult:
        """Handle MCP elicitation/create requests from the server.
        Pushes the elicitation to the browser UI and waits for user response."""
        import uuid, re as _re

        message = params.message
        schema = params.requestedSchema or {}

        # Extract the "provided" graph name from the message
        _provided_match = _re.search(r"provided:\s*'([^']+)'", message)
        _provided_name = _provided_match.group(1) if _provided_match else None

        # Extract enum options from schema
        options: list[str] = []
        _value_key: str | None = None
        props = schema.get("properties", {})
        for key, prop_schema in props.items():
            enum_values = prop_schema.get("enum", [])
            if enum_values:
                options = enum_values
                _value_key = key
                break

        if self._broadcast_session_id and options:
            # Route to browser — user must confirm
            elicitation_id = str(uuid.uuid4())
            await publish_mcplog(
                self._broadcast_session_id,
                f"[elicitation] Waiting for user to confirm graph: {message}",
                "info",
            )
            chosen = await publish_elicitation(
                session_id=self._broadcast_session_id,
                elicitation_id=elicitation_id,
                message=message,
                options=options,
                provided=_provided_name,
            )
            if chosen is not None:
                await publish_mcplog(
                    self._broadcast_session_id,
                    f"[elicitation] User confirmed: {chosen}",
                    "info",
                )
                content = {_value_key: chosen} if _value_key else {"value": chosen}
                return _mcp_types.ElicitResult(action="accept", content=content)
            else:
                await publish_mcplog(
                    self._broadcast_session_id,
                    "[elicitation] User cancelled.",
                    "warning",
                )
                return _mcp_types.ElicitResult(action="decline")

        # Fallback: no broadcast session or no options — auto-accept with provided name
        content: dict[str, str | int | float | bool | None] = {}
        for key, prop_schema in props.items():
            enum_values = prop_schema.get("enum", [])
            if enum_values:
                if _provided_name and _provided_name in enum_values:
                    content[key] = _provided_name
                else:
                    content[key] = enum_values[0]
            elif prop_schema.get("type") == "string":
                content[key] = prop_schema.get("default", "")

        return _mcp_types.ElicitResult(action="accept", content=content)

    async def connect(self) -> None:
        """Override connect to inject elicitation_callback into the ClientSession."""
        if not self.session:
            from agent_framework._tools import ToolException
            try:
                transport = await self._exit_stack.enter_async_context(self.get_mcp_client())
            except Exception as ex:
                await self._exit_stack.aclose()
                error_msg = f"Failed to connect to MCP server: {ex}"
                raise ToolException(error_msg, inner_exception=ex) from ex
            try:
                session = await self._exit_stack.enter_async_context(
                    _ClientSession(
                        read_stream=transport[0],
                        write_stream=transport[1],
                        read_timeout_seconds=_timedelta(seconds=self.request_timeout) if self.request_timeout else None,
                        message_handler=self.message_handler,
                        logging_callback=self.logging_callback,
                        sampling_callback=self.sampling_callback,
                        elicitation_callback=self._handle_elicitation,
                    )
                )
            except Exception as ex:
                await self._exit_stack.aclose()
                raise ToolException(
                    message="Failed to create MCP session.", inner_exception=ex
                ) from ex
            try:
                await session.initialize()
            except Exception as ex:
                await self._exit_stack.aclose()
                raise ToolException(
                    message=f"MCP server failed to initialize: {ex}", inner_exception=ex
                ) from ex
            self.session = session
        elif self.session._request_id == 0:
            await self.session.initialize()
        self.is_connected = True
        if self.load_tools_flag:
            await self.load_tools()
        if self.load_prompts_flag:
            await self.load_prompts()

    async def logging_callback(self, params: _mcp_types.LoggingMessageNotificationParams) -> None:
        # Keep the default behaviour (Python logging)
        await super().logging_callback(params)
        # Also push to the SSE bus for the frontend panel
        if self._broadcast_session_id:
            # params.data is typically a dict like {'msg': '...', 'extra': ...}
            # or a plain string — extract the readable message
            data = params.data
            if isinstance(data, dict):
                text = data.get("msg") or data.get("message") or str(data)
            elif isinstance(data, str):
                text = data
            else:
                text = str(data) if data else ""
            level = str(params.level) if params.level else "info"
            await publish_mcplog(self._broadcast_session_id, text, level)





