# Session Log — 2026-05-09: Agent Framework Rewrite + MCP Server

**Requested by:** Anil
**Agents:** Kane (Backend Dev), Parker (Data Engineer)
**Duration:** Background parallel execution

## Summary

Kane and Parker worked in parallel to migrate the TalentIQ agent from raw OpenAI function calling to the Microsoft Agent Framework SDK, backed by a new MCP server.

### Kane — Agent Framework Rewrite + Chat History
- Rewrote `talent_agent.py` — replaced manual 9-tool OpenAI function calling with `Agent` + `MCPStreamableHTTPTool` + `OpenAIChatCompletionClient`
- Removed `azure-ai-projects`, added `agent-framework>=1.3.0`
- Stripped `tools.py` to just `generate_embedding()` (search endpoints still need it)
- Added `MCP_ENDPOINT` config var (default: `http://localhost:3002/mcp`)
- Copied agent instructions locally to `talent_backend/talent_backend/agent/instructions/`
- Added Cosmos DB chat history: `ChatHistoryService` with session management, graceful degradation
- New endpoints: `GET /sessions`, `GET /sessions/{id}`, `DELETE /sessions/{id}`

### Parker — MCP Server
- Created `talent_backend/talent_backend/mcp_server/` (4 files)
- FastMCP server on port 3002 with streamable-http transport
- 8 tools: fetch_ontology, save_ontology, query_using_sql_cypher, discover_nodes, search_graph, resolve_entity_ids, build_query_context, analyze_graph_statistics
- Pre-loaded talent_graph ontology (14 node labels, 12 edge labels)
- Existing data_access layer preserved for structured API endpoints

## Decisions Captured
1. Agent Framework rewrite — raw OpenAI → agent_framework SDK
2. Chat history via Cosmos DB with graceful degradation
3. MCP Server architecture — standalone FastMCP process, additive to data_access layer
