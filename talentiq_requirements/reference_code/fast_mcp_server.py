"""
TalentIQ MCP Server

Provides talent search tools for AI agents via the Model Context Protocol.
Connects to Azure AI Search and Cosmos DB using DefaultAzureCredential.
Supports Foundry MSI, Managed Identity, Service Principal, and az login.

Tools:
  - search_candidates: Search by skill, location, region, organization
  - match_candidates_for_demand: Find candidates matching a demand ID
  - get_bench_count: Bench analytics by organization
  - search_demands: Search demands by location, skill, status
  - get_demand: Get demand details by ID

Usage:
  uv run python server.py                              # streamable-http (default)
  uv run python server.py --transport stdio             # stdio for local clients
  uv run python server.py --port 8080                   # custom port
"""

import argparse
import json
import os
import sys
import time

from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from fastmcp import FastMCP

try:
    from mcp_server.search_service import SearchService
    from mcp_server.cosmos_service import CosmosService
    from mcp_server.telemetry import (
        configure_mcp_telemetry, record_server_init, record_tool_call,
        record_search_call, record_error, tool_span, search_span,
    )
except ImportError:
    from search_service import SearchService
    from cosmos_service import CosmosService
    from telemetry import (
        configure_mcp_telemetry, record_server_init, record_tool_call,
        record_search_call, record_error, tool_span, search_span,
    )

# Load env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

# ── Shared credential ───────────────────────────────────────
# DefaultAzureCredential picks up (in order):
#   1. Environment vars (AZURE_CLIENT_ID/TENANT_ID/SECRET) — service principal
#   2. Managed Identity (MSI) — Foundry, App Service, Container App
#   3. Azure CLI (az login) — local development
credential = DefaultAzureCredential()

# ── Azure AI Search ──────────────────────────────────────────
_search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
_candidates_index = os.environ.get("AZURE_SEARCH_CANDIDATES_INDEX", "candidates-index")
_demands_index = os.environ.get("AZURE_SEARCH_DEMANDS_INDEX", "demands-index")

if not _search_endpoint:
    print("Error: AZURE_SEARCH_ENDPOINT not set", file=sys.stderr)
    sys.exit(1)

candidate_search = SearchService(_search_endpoint, _candidates_index, credential)
demand_search = SearchService(_search_endpoint, _demands_index, credential)

# ── Azure Cosmos DB ──────────────────────────────────────────
_cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "")
_cosmos_database = os.environ.get("COSMOS_DATABASE", "talentiq")
_cosmos_candidates = os.environ.get("COSMOS_CANDIDATES_CONTAINER", "candidates")
_cosmos_demands = os.environ.get("COSMOS_DEMANDS_CONTAINER", "demands")

candidates_cosmos = None
demands_cosmos = None
if _cosmos_endpoint:
    candidates_cosmos = CosmosService(_cosmos_endpoint, _cosmos_database, _cosmos_candidates, credential)
    demands_cosmos = CosmosService(_cosmos_endpoint, _cosmos_database, _cosmos_demands, credential)
    print(f"Cosmos DB: {_cosmos_endpoint} / {_cosmos_database}", file=sys.stderr)
else:
    print("Warning: COSMOS_ENDPOINT not set, Cosmos DB queries disabled", file=sys.stderr)

print(f"AI Search: {_search_endpoint}", file=sys.stderr)
print(f"Auth: DefaultAzureCredential (MSI / az login / service principal)", file=sys.stderr)

# ── Telemetry ────────────────────────────────────────────────
_init_start = time.perf_counter()
configure_mcp_telemetry("talentiq-mcp-search-server")

mcp = FastMCP(
    "TalentIQ",
    instructions="Talent matching tools for searching candidates, demands, and bench analytics.",
)

record_server_init((time.perf_counter() - _init_start) * 1000)


# ── Candidate Tools ──────────────────────────────────────────

@mcp.tool()
def search_candidates(
    query: str = "*",
    skill: str | None = None,
    country: str | None = None,
    region: str | None = None,
    organization: str | None = None,
    top: int = 10,
) -> str:
    """Search for candidates by skill, location, region, organization, or free text.

    Use for queries like 'find people with python skills in Serbia' or
    'find 5 people with java skills in Europe'.

    Args:
        query: Free text search query
        skill: Primary skill to filter by (e.g., Python, Java, React)
        country: Country to filter by (e.g., Serbia, Poland, India)
        region: Region to filter by (e.g., Europe, Asia, Americas)
        organization: Organization to filter by (e.g., DXC Technology)
        top: Maximum number of results (default 10, max 50)
    """
    top = min(top, 50)

    filter_parts = []
    if skill:
        filter_parts.append(f"primary_skill eq '{skill}'")
    if country:
        filter_parts.append(f"location_country eq '{country}'")
    if region:
        filter_parts.append(f"location_region eq '{region}'")
    if organization:
        filter_parts.append(f"organization eq '{organization}'")

    filters = " and ".join(filter_parts) if filter_parts else None

    with tool_span("search_candidates") as span:
        search_start = time.perf_counter()
        results = candidate_search.search(query, filters=filters, top=top)
        search_ms = (time.perf_counter() - search_start) * 1000
        record_search_call(_candidates_index, len(results), search_ms)
        span.set_attribute("search.result_count", len(results))
        span.set_attribute("search.filters", filters or "none")

    summary = f"Found {len(results)} candidates"
    if skill:
        summary += f" with {skill} skills"
    if country:
        summary += f" in {country}"
    if region:
        summary += f" in {region}"

    candidates = [
        {
            "id": r.get("candidate_id"),
            "name": f"{r.get('first_name', '')} {r.get('last_name', '')}",
            "skill": r.get("primary_skill"),
            "level": r.get("skill_level"),
            "location": f"{r.get('location_city')}, {r.get('location_country')}",
            "experience": r.get("years_of_experience"),
            "status": r.get("employment_status"),
            "organization": r.get("organization"),
            "job_title": r.get("job_title"),
        }
        for r in results
    ]

    return json.dumps({"summary": summary, "candidates": candidates}, indent=2)


@mcp.tool()
def match_candidates_for_demand(demand_id: str, top: int = 10) -> str:
    """Find candidates that match a specific demand by demand ID.

    Looks up the demand to get required skill and location, then searches
    for matching candidates.

    Use for queries like 'find candidates for demand RR-05010'.

    Args:
        demand_id: Demand ID (e.g., RR-05010 or RR-0051010)
        top: Maximum number of candidates to return (default 10, max 50)
    """
    top = min(top, 50)

    with tool_span("match_candidates_for_demand") as span:
        span.set_attribute("demand.id", demand_id)
        demand = demand_search.get_by_id(demand_id)
        if not demand:
            return json.dumps({"error": f"Demand {demand_id} not found"})

        skill = demand.get("required_skill", "")
        country = demand.get("location_country", "")

        filters = f"primary_skill eq '{skill}'"
        if country:
            filters += f" and location_country eq '{country}'"

        search_start = time.perf_counter()
        results = candidate_search.search("*", filters=filters, top=top)
        search_ms = (time.perf_counter() - search_start) * 1000
        record_search_call(_candidates_index, len(results), search_ms)
        span.set_attribute("search.result_count", len(results))

    demand_info = {
        "demand_id": demand.get("demand_id"),
        "title": demand.get("title"),
        "skill": skill,
        "location": f"{demand.get('location_city')}, {country}",
        "client": demand.get("client"),
        "status": demand.get("status"),
        "experience_range": f"{demand.get('experience_min', '?')}-{demand.get('experience_max', '?')} years",
    }

    candidates = [
        {
            "id": r.get("candidate_id"),
            "name": f"{r.get('first_name', '')} {r.get('last_name', '')}",
            "skill": r.get("primary_skill"),
            "level": r.get("skill_level"),
            "location": f"{r.get('location_city')}, {r.get('location_country')}",
            "experience": r.get("years_of_experience"),
            "status": r.get("employment_status"),
        }
        for r in results
    ]

    return json.dumps({
        "demand": demand_info,
        "matched_candidates": len(candidates),
        "candidates": candidates,
    }, indent=2)


@mcp.tool()
def get_bench_count(organization: str | None = None) -> str:
    """Get count and details of people on the bench, optionally filtered by organization.

    Use for queries like 'how many people on the bench in DXC' or 'show bench resources'.

    Args:
        organization: Organization to filter by (e.g., DXC Technology)
    """
    filters = "is_bench eq true"
    if organization:
        filters += f" and organization eq '{organization}'"

    with tool_span("get_bench_count") as span:
        search_start = time.perf_counter()
        results = candidate_search.search("*", filters=filters, top=1000)
        search_ms = (time.perf_counter() - search_start) * 1000
        record_search_call(_candidates_index, len(results), search_ms)
        span.set_attribute("search.result_count", len(results))

    by_skill: dict[str, int] = {}
    by_location: dict[str, int] = {}
    by_org: dict[str, int] = {}
    for r in results:
        s = r.get("primary_skill", "Unknown")
        by_skill[s] = by_skill.get(s, 0) + 1
        c = r.get("location_country", "Unknown")
        by_location[c] = by_location.get(c, 0) + 1
        o = r.get("organization", "Unknown")
        by_org[o] = by_org.get(o, 0) + 1

    return json.dumps({
        "total_bench": len(results),
        "by_skill": dict(sorted(by_skill.items(), key=lambda x: -x[1])),
        "by_location": dict(sorted(by_location.items(), key=lambda x: -x[1])),
        "by_organization": dict(sorted(by_org.items(), key=lambda x: -x[1])),
    }, indent=2)


# ── Demand Tools ─────────────────────────────────────────────

@mcp.tool()
def search_demands(
    query: str = "*",
    country: str | None = None,
    region: str | None = None,
    skill: str | None = None,
    status: str | None = None,
    top: int = 20,
) -> str:
    """Search for demands by location, skill, status, or free text.

    Use for queries like 'show me demands for Poland' or 'find open Java demands in Europe'.

    Args:
        query: Free text search query
        country: Country to filter by
        region: Region to filter by
        skill: Required skill to filter by
        status: Demand status (Open, Filled, Cancelled, On Hold)
        top: Max results (default 20, max 100)
    """
    top = min(top, 100)

    filter_parts = []
    if country:
        filter_parts.append(f"location_country eq '{country}'")
    if region:
        filter_parts.append(f"location_region eq '{region}'")
    if skill:
        filter_parts.append(f"required_skill eq '{skill}'")
    if status:
        filter_parts.append(f"status eq '{status}'")

    filters = " and ".join(filter_parts) if filter_parts else None

    with tool_span("search_demands") as span:
        search_start = time.perf_counter()
        results = demand_search.search(query, filters=filters, top=top)
        search_ms = (time.perf_counter() - search_start) * 1000
        record_search_call(_demands_index, len(results), search_ms)
        span.set_attribute("search.result_count", len(results))

    demands = [
        {
            "demand_id": r.get("demand_id"),
            "title": r.get("title"),
            "client": r.get("client"),
            "skill": r.get("required_skill"),
            "location": f"{r.get('location_city')}, {r.get('location_country')}",
            "status": r.get("status"),
            "priority": r.get("priority"),
            "positions": r.get("positions_count"),
        }
        for r in results
    ]

    return json.dumps({"total": len(demands), "demands": demands}, indent=2)


@mcp.tool()
def get_demand(demand_id: str) -> str:
    """Get details of a specific demand by its ID.

    Use when the user provides a demand ID like RR-05010.

    Args:
        demand_id: Demand ID (e.g., RR-05010)
    """
    demand = demand_search.get_by_id(demand_id)
    if not demand:
        return json.dumps({"error": f"Demand {demand_id} not found"})
    return json.dumps(demand, indent=2, default=str)


# ── Entry point ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TalentIQ MCP Server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="streamable-http",
                        help="Transport type (default: streamable-http)")
    parser.add_argument("--port", type=int, default=8080, help="Port for HTTP transport")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host for HTTP transport")
    args = parser.parse_args()

    mcp.run(transport=args.transport, host=args.host, port=args.port)
