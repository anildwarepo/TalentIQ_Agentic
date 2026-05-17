"""Tests for the AGE Cypher query rewriter.

Run from repo root:
    pytest tests/database_test/test_cypher_rewriter.py -v

Uses only stdlib + pytest — no DB connection required.
"""

from __future__ import annotations

import re

import pytest

from talent_backend.mcp_server.cypher_rewriter import optimize_sql


# ── Real-world slow query the agent generated for                       ─
# ── "Find Python developers in India" (17.5s on 130k Employees)         ─
SLOW_QUERY_REAL = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WHERE s.name =~ '(?i).*(terraform|ansible|bicep|kubernetes|python).*'
WITH e, e.name AS name, e.email AS email, e.job_title AS job_title,
     e.skill_level AS skill_level, e.years_of_experience AS yoe,
     e.employment_status AS status, e.is_bench AS is_bench,
     e.bench_duration_days AS bench_days,
     e.availability_date AS availability_date, e.current_project AS current_project,
     collect(DISTINCT s.name) AS matched_skills
OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)
WHERE hc.status = 'Valid'
WITH name, email, job_title, skill_level, yoe, status, is_bench,
     bench_days, availability_date, current_project, matched_skills,
     collect(DISTINCT cert.name) AS certs
RETURN name AS name, email AS email, job_title AS job_title,
       skill_level AS skill_level, yoe AS years_experience,
       status AS employment_status, is_bench AS is_bench,
       bench_days AS bench_duration_days,
       availability_date AS availability_date,
       current_project AS current_project,
       matched_skills AS matched_skills, certs AS certifications
ORDER BY is_bench DESC, size(matched_skills) DESC, yoe DESC
LIMIT 25
$$) AS (name ag_catalog.agtype, email ag_catalog.agtype, job_title ag_catalog.agtype,
        skill_level ag_catalog.agtype, years_experience ag_catalog.agtype,
        employment_status ag_catalog.agtype, is_bench ag_catalog.agtype,
        bench_duration_days ag_catalog.agtype, availability_date ag_catalog.agtype,
        current_project ag_catalog.agtype, matched_skills ag_catalog.agtype,
        certifications ag_catalog.agtype);"""


def test_rewrites_real_slow_query():
    """The exact query that took 17.5s should be rewritten to push LIMIT."""
    new_sql, reason = optimize_sql(SLOW_QUERY_REAL)
    assert reason is not None and "limit-pushdown" in reason
    assert new_sql != SLOW_QUERY_REAL

    # The injected ORDER BY+LIMIT must appear BEFORE the OPTIONAL MATCH.
    opt_pos = new_sql.upper().find("OPTIONAL MATCH")
    # Find the LAST `LIMIT 25` occurrence — there should be two now (the
    # injected one before OPTIONAL MATCH, plus the original final one).
    limit_positions = [m.start() for m in re.finditer(r"\bLIMIT\s+25\b", new_sql, re.IGNORECASE)]
    assert len(limit_positions) == 2, f"expected 2 LIMIT 25 clauses, got {len(limit_positions)}"
    assert limit_positions[0] < opt_pos < limit_positions[1]


def test_rewrites_simple_optional_match_pattern():
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WHERE s.name =~ '(?i).*python.*'
WITH e, collect(DISTINCT s.name) AS skills_
OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)
WITH e, skills_, collect(DISTINCT cert.name) AS certs
RETURN e.name AS name, skills_, certs
ORDER BY size(skills_) DESC
LIMIT 10
$$) AS (name ag_catalog.agtype, skills_ ag_catalog.agtype, certs ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason is not None and "limit-pushdown" in reason
    # The injected LIMIT should appear before OPTIONAL MATCH.
    opt_pos = new_sql.upper().find("OPTIONAL MATCH")
    first_limit_pos = re.search(r"\bLIMIT\s+10\b", new_sql, re.IGNORECASE).start()
    assert first_limit_pos < opt_pos


def test_skips_already_optimised_query():
    """If LIMIT is already pushed down, leave it alone."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WHERE s.name =~ '(?i).*python.*'
WITH e, collect(DISTINCT s.name) AS skills_
ORDER BY size(skills_) DESC
LIMIT 25
OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)
WITH e, skills_, collect(DISTINCT cert.name) AS certs
RETURN e.name AS name, skills_, certs
ORDER BY size(skills_) DESC
LIMIT 25
$$) AS (name ag_catalog.agtype, skills_ ag_catalog.agtype, certs ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    # Structural pushdown is skipped (already present), but the alias
    # deref pass still injects a pass-through WITH.
    assert reason == "deref-agg-alias"
    # Importantly: should NOT have inserted a third LIMIT.
    limit_count = len(re.findall(r"\bLIMIT\s+25\b", new_sql, re.IGNORECASE))
    assert limit_count == 2


def test_skips_no_optional_match():
    """No OPTIONAL MATCH → no rewrite needed."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WHERE s.name =~ '(?i).*python.*'
WITH e, collect(DISTINCT s.name) AS skills_
RETURN e.name AS name, skills_
ORDER BY size(skills_) DESC
LIMIT 25
$$) AS (name ag_catalog.agtype, skills_ ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason is None
    assert new_sql == sql


def test_skips_no_aggregation_with():
    """If the WITH before OPTIONAL MATCH has no aggregation, leave it alone."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee {name: 'Alice'})
WITH e
OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)
RETURN e.name AS name, collect(cert.name) AS certs
LIMIT 1
$$) AS (name ag_catalog.agtype, certs ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason is None


def test_skips_no_node_var_carried():
    """If the agg WITH doesn't carry the OPTIONAL MATCH's node var, leave it."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WHERE s.name =~ '(?i).*python.*'
WITH e.name AS name, collect(DISTINCT s.name) AS skills_
OPTIONAL MATCH (other:Employee)-[hc:HOLDS_CERT]->(cert:Certification)
WITH name, skills_, collect(DISTINCT cert.name) AS certs
RETURN name, skills_, certs
ORDER BY size(skills_) DESC
LIMIT 10
$$) AS (name ag_catalog.agtype, skills_ ag_catalog.agtype, certs ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    # `e` is not carried, and `other` isn't bound earlier — should not rewrite.
    assert reason is None


def test_skips_non_cypher_sql():
    """Plain SQL with no ag_catalog.cypher() — passthrough."""
    sql = "SELECT * FROM employees WHERE country = 'India' LIMIT 25"
    new_sql, reason = optimize_sql(sql)
    assert reason is None
    assert new_sql == sql


def test_skips_multiple_cypher_calls():
    """Two ag_catalog.cypher() calls in one statement → safer to skip."""
    sql = (
        "SELECT * FROM ag_catalog.cypher('g', $$ MATCH (a) RETURN a $$) AS (a ag_catalog.agtype) "
        "UNION "
        "SELECT * FROM ag_catalog.cypher('g', $$ MATCH (b) RETURN b $$) AS (b ag_catalog.agtype)"
    )
    new_sql, reason = optimize_sql(sql)
    assert reason is None


def test_does_not_raise_on_garbage():
    """Malformed input must never raise — just passthrough."""
    for garbage in ["", "   ", "not sql at all", "SELECT", "ag_catalog.cypher("]:
        new_sql, reason = optimize_sql(garbage)
        assert reason is None
        assert new_sql == garbage


# ── AGE syntax cleanup ────────────────────────────────────────────────


def test_strips_nulls_last_in_order_by():
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee) WHERE e.country = 'India'
RETURN e.name AS name, e.years_of_experience AS yoe
ORDER BY yoe DESC NULLS LAST, name ASC NULLS FIRST
LIMIT 10
$$) AS (name ag_catalog.agtype, yoe ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason is not None and "strip-nulls-last" in reason
    assert "NULLS LAST" not in new_sql.upper()
    assert "NULLS FIRST" not in new_sql.upper()
    # Expected shape: ORDER BY yoe DESC, name ASC
    assert re.search(r"ORDER\s+BY\s+yoe\s+DESC\s*,\s*name\s+ASC", new_sql, re.IGNORECASE)


def test_does_not_strip_nulls_inside_string_literal():
    """A regex literal mentioning 'nulls' must not be touched."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee) WHERE e.notes =~ '(?i).*nulls last.*'
RETURN e.name AS name
LIMIT 5
$$) AS (name ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason is None
    assert "nulls last" in new_sql


def test_combines_cleanup_and_pushdown():
    """Both passes can fire on the same query; reasons are joined with '+'."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WHERE s.name =~ '(?i).*python.*'
WITH e, collect(DISTINCT s.name) AS skills_
OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)
WITH e, skills_, collect(DISTINCT cert.name) AS certs
RETURN e.name AS name, skills_, certs
ORDER BY size(skills_) DESC NULLS LAST
LIMIT 25
$$) AS (name ag_catalog.agtype, skills_ ag_catalog.agtype, certs ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason is not None
    assert "strip-nulls-last" in reason
    assert "limit-pushdown" in reason
    assert "NULLS LAST" not in new_sql.upper()


def test_cleanup_only_when_no_optional_match():
    """Cleanup still fires even if pushdown doesn't apply."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee) WHERE e.is_bench = true
RETURN e.name AS name, e.bench_duration_days AS days
ORDER BY days DESC NULLS LAST
LIMIT 10
$$) AS (name ag_catalog.agtype, days ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason == "strip-nulls-last(1)"
    assert "NULLS" not in new_sql.upper().split("ORDER BY")[1].split("LIMIT")[0]


# ── AGE aggregation-WITH alias resolution ─────────────────────────────


def test_fixes_agg_order_alias():
    """Pass-through WITH injected between agg WITH and ORDER BY (AGE rte fix)."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WHERE s.name =~ '(?i).*python.*'
WITH e, e.years_of_experience AS yoe, collect(DISTINCT s.name) AS skills
ORDER BY yoe DESC, size(skills) DESC
LIMIT 10
$$) AS (name ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason == "deref-agg-alias"
    # The rewritten body should have two WITHs (agg + pass-through).
    body = new_sql.split("$$")[1]
    with_count = len(re.findall(r"\bWITH\b", body, re.IGNORECASE))
    assert with_count == 2, f"expected 2 WITHs, got {with_count}"
    # Pass-through WITH must carry e, yoe, and skills.
    second_with = body.upper().split("WITH", 2)[2].split("\n")[0]
    for var in ["E", "YOE", "SKILLS"]:
        assert var in second_with, f"'{var}' missing from pass-through WITH"


def test_no_deref_for_non_agg_with():
    """ORDER BY after non-agg WITH needs no pass-through."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)
WITH e, e.name AS name
ORDER BY name
LIMIT 10
$$) AS (name ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason is None
    assert new_sql == sql


def test_deref_combines_with_pushdown():
    """Pushdown + alias deref both fire; pass-through WITH appears before ORDER BY."""
    sql = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WHERE s.name =~ '(?i).*python.*'
WITH e, e.years_of_experience AS yoe, collect(DISTINCT s.name) AS skills
OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)
WHERE hc.status = 'Valid'
WITH e.name AS name, yoe, skills, collect(DISTINCT cert.name) AS certs
RETURN name, yoe, skills, certs
ORDER BY yoe DESC, size(skills) DESC
LIMIT 25
$$) AS (name ag_catalog.agtype, yoe ag_catalog.agtype, skills ag_catalog.agtype, certs ag_catalog.agtype);"""
    new_sql, reason = optimize_sql(sql)
    assert reason is not None
    assert "limit-pushdown" in reason
    assert "deref-agg-alias" in reason
    # Pass-through WITH must appear before OPTIONAL MATCH.
    opt_pos = new_sql.upper().find("OPTIONAL MATCH")
    body = new_sql.split("$$")[1]
    # Count WITHs — agg + pass-through + second WITH after OPTIONAL MATCH.
    with_count = len(re.findall(r"\bWITH\b", body, re.IGNORECASE))
    assert with_count == 3, f"expected 3 WITHs, got {with_count}"

