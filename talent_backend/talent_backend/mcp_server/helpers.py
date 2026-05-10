"""Shared helpers for the MCP server tools.

Pure functions — no FastMCP or database dependencies.
"""

from __future__ import annotations

from talent_backend.config import GRAPH_NAME

# ── Ontology cache ───────────────────────────────────────────
ONTOLOGY_MEMORY: dict[str, str] = {}

TALENT_GRAPH_ONTOLOGY = """
Graph: talent_graph (130,000 DXC employees)

NODE LABELS (14):
  Employee (130,000) — payload: name, first_name, last_name, email, phone, workday_id, job_title, job_level (int 3-14), skill_level (Junior/Mid/Senior/Lead/Principal/Architect), hire_date, years_of_experience (int), employment_status (Active/Bench/Notice Period/Long-term Leave), is_bench (bool), bench_start_date, bench_duration_days (int), availability_date, current_project, fte_current_month (int %), fte_next_month, fte_next2_month, hourly_cost_usd (float), bill_rate_usd (float), cv_last_updated, cv_freshness_days (int), cv_source, impressiveness_score (float 0-100), data_source, delivery_model (onshore/nearshore/offshore), eqf_level (int 5-8), meces_level (int 1-4), eqf_mapping_status, education_degree, education_field, resume_summary (free text)
  Location (46) — payload: city, country, country_code, region, subregion, zip, address, timezone, delivery_model
  Country (19) — payload: name, code, region
  Subregion (15) — payload: name, region
  Skill (96) — payload: name
  SkillDomain (13) — payload: name (Python, Java, C#/.NET, JavaScript/TS, Cloud (Azure), Cloud (AWS), DevOps/SRE, Data Engineering, AI/ML, SAP, Salesforce, Cybersecurity, ServiceNow)
  Certification (39) — payload: name
  Language (18) — payload: name
  ServiceLine (8) — payload: name
  Offering (8) — payload: name
  Manager (80) — payload: name, email, employee_id
  University (75) — payload: name
  Client (36) — payload: name
  Project (22) — payload: name

EDGE LABELS (12):
  LOCATED_IN: Employee -> Location (no props)
  IN_COUNTRY: Location -> Country (no props)
  SPECIALIZES_IN: Employee -> SkillDomain (no props)
  HAS_SKILL: Employee -> Skill (payload: level, years_of_experience, active, is_primary)
  HOLDS_CERT: Employee -> Certification (payload: issue_date, expiry_date, status [Valid/Expiring/Expired], credential_id, has_evidence)
  SPEAKS: Employee -> Language (payload: level [CEFR: A1-C2], is_native)
  BELONGS_TO_SL: Employee -> ServiceLine (no props)
  WORKS_IN_OFFERING: Employee -> Offering (no props)
  REPORTS_TO: Employee -> Manager (no props)
  STUDIED_AT: Employee -> University (payload: degree, field, graduation_year, eqf_level, meces_level)
  WORKED_FOR: Employee -> Client (payload: role, project, start_date, end_date, is_current)
  WORKED_ON: Employee -> Project (payload: role, start_date, end_date)

AGE QUERY PATTERN (use WITH for aggregation ORDER BY):
  WRONG:  RETURN c.payload.name AS country, count(e) AS cnt ORDER BY cnt DESC
  CORRECT: WITH c.payload.name AS country, count(e) AS cnt RETURN country, cnt ORDER BY cnt DESC

PROPERTY ACCESS: All via payload.* (e.g., e.payload.name, hs.payload.level)
""".strip()

# Pre-load the talent_graph ontology
ONTOLOGY_MEMORY[GRAPH_NAME] = TALENT_GRAPH_ONTOLOGY


# ── Name / search helpers ────────────────────────────────────

NAME_SKIP_TITLES = frozenset({
    "dr", "mr", "mrs", "ms", "prof", "sir", "dame", "rev",
    "the", "of", "and", "for", "at", "in",
    "lead", "senior", "junior", "principal", "architect",
    "manager", "director", "engineer", "developer", "consultant",
})


def strip_agtype(val) -> str:
    """Strip AGE agtype formatting: '["Label"]' -> 'Label', '"rel"' -> 'rel'."""
    if not isinstance(val, str):
        return str(val)
    val = val.strip()
    if val.startswith('["') and val.endswith('"]'):
        val = val[2:-2]
    elif val.startswith('"') and val.endswith('"') and len(val) > 1:
        val = val[1:-1]
    return val


def extract_search_words(search_term: str) -> list[str]:
    """Extract significant words from a search term, skipping titles and short words."""
    return [
        w.lower().strip(".,;:")
        for w in search_term.split()
        if w.lower().strip(".,;:") not in NAME_SKIP_TITLES and len(w.strip(".,;:")) >= 2
    ]


def name_matches_search(name: str, search_words: list[str]) -> bool:
    """Check if a name contains ALL significant search words."""
    if not search_words or not name:
        return True
    name_lower = name.lower()
    return all(w in name_lower for w in search_words)


def strip_titles_for_search(search_term: str) -> str:
    """Strip known titles/honorifics from a search term to maximise FTS recall."""
    words = search_term.split()
    stripped = [w for w in words if w.lower().strip(".,;:") not in NAME_SKIP_TITLES]
    if len(stripped) < 2 and len(words) >= 2:
        return search_term
    if not stripped:
        return search_term
    return " ".join(stripped)
