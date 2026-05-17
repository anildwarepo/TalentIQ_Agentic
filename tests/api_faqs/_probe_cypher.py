"""One-off probe: run the find_employees-style Cypher directly against AGE.

Used to isolate whether the runner hang is at the DB layer or above.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "app_config" / ".env")

import psycopg  # noqa: E402

CONN = (
    f"host={os.environ['PGHOST']} "
    f"port={os.environ.get('PGPORT', '5432')} "
    f"dbname={os.environ['PGDATABASE']} "
    f"user={os.environ['PGUSER']} "
    f"password={os.environ['PGPASSWORD']} "
    f"sslmode={os.environ.get('PGSSLMODE', 'require')}"
)

SQL_FULL = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
  MATCH (e:Employee),
        (e)-[:HAS_SKILL]->(s:Skill),
        (e)-[:LOCATED_IN]->(l:Location)-[:IN_COUNTRY]->(c:Country)
  WHERE s.name =~ '(?i).*(python).*' AND c.name = 'India'
  RETURN e.name, c.name
  LIMIT 5
$$) AS (name ag_catalog.agtype, country ag_catalog.agtype);"""

SQL_NO_REGEX = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
  MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
  WHERE s.name = 'Python'
  MATCH (e)-[:LOCATED_IN]->(:Location)-[:IN_COUNTRY]->(c:Country)
  WHERE c.name = 'India'
  RETURN e.name, c.name
  LIMIT 5
$$) AS (name ag_catalog.agtype, country ag_catalog.agtype);"""

SQL_COUNTS = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
  MATCH (e:Employee) RETURN count(e)
$$) AS (n ag_catalog.agtype);"""

SQL_AGENT_VERBATIM = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
  MATCH (e:Employee),
        (e)-[:HAS_SKILL]->(s:Skill),
        (e)-[:LOCATED_IN]->(l:Location)-[:IN_COUNTRY]->(c:Country)
  WHERE s.name =~ '(?i).*(python).*' AND c.name = 'India'
  WITH e.name AS name_, e.email AS email_, e.job_title AS title_, e.years_of_experience AS yoe, e.bench_duration_days AS bench_days_, l.city AS city_, c.name AS country_, collect(DISTINCT s.name) AS skills_
  OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)
  WHERE hc.status = 'Valid'
  WITH name_, email_, title_, yoe, bench_days_, city_, country_, skills_, collect(DISTINCT cert.name) AS certs_
  WITH name_, email_, title_, yoe, bench_days_, city_, country_, skills_, certs_, [] AS langs_
  RETURN name_, email_, title_, yoe, bench_days_, city_, country_, skills_, certs_, langs_
  ORDER BY yoe DESC
  LIMIT 25
$$) AS (name_ ag_catalog.agtype, email_ ag_catalog.agtype, title_ ag_catalog.agtype, yoe ag_catalog.agtype, bench_days_ ag_catalog.agtype, city_ ag_catalog.agtype, country_ ag_catalog.agtype, skills_ ag_catalog.agtype, certs_ ag_catalog.agtype, langs_ ag_catalog.agtype);"""

SQL_FIXED_PUSHDOWN = """SELECT * FROM ag_catalog.cypher('talent_graph_dev', $$
  MATCH (e:Employee),
        (e)-[:HAS_SKILL]->(s:Skill),
        (e)-[:LOCATED_IN]->(l:Location)-[:IN_COUNTRY]->(c:Country)
  WHERE s.name =~ '(?i).*(python).*' AND c.name = 'India'
  WITH e, l, c, collect(DISTINCT s.name) AS skills_
  ORDER BY e.years_of_experience DESC
  LIMIT 25
  OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)
  WHERE hc.status = 'Valid'
  WITH e, l, c, skills_, collect(DISTINCT cert.name) AS certs_
  WITH e, l, c, skills_, certs_, [] AS langs_
  WITH e.name AS name_, e.email AS email_, e.job_title AS title_, e.years_of_experience AS yoe, e.bench_duration_days AS bench_days_, l.city AS city_, c.name AS country_, skills_, certs_, langs_
  RETURN name_, email_, title_, yoe, bench_days_, city_, country_, skills_, certs_, langs_
  ORDER BY yoe DESC
  LIMIT 25
$$) AS (name_ ag_catalog.agtype, email_ ag_catalog.agtype, title_ ag_catalog.agtype, yoe ag_catalog.agtype, bench_days_ ag_catalog.agtype, city_ ag_catalog.agtype, country_ ag_catalog.agtype, skills_ ag_catalog.agtype, certs_ ag_catalog.agtype, langs_ ag_catalog.agtype);"""


def run(label: str, sql: str, timeout_ms: int = 60000) -> None:
    print(f"\n--- {label} (statement_timeout={timeout_ms}ms) ---")
    with psycopg.connect(CONN, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute('SET search_path = ag_catalog, "$user", public;')
            cur.execute(f"SET statement_timeout = {timeout_ms};")
            t0 = time.perf_counter()
            try:
                cur.execute(sql)
                rows = cur.fetchall()
                print(f"  OK in {time.perf_counter()-t0:.2f}s, rows={len(rows)}")
                for r in rows[:5]:
                    print("   ", r)
            except Exception as ex:  # noqa: BLE001
                print(f"  FAIL after {time.perf_counter()-t0:.2f}s: {type(ex).__name__}: {ex}")


if __name__ == "__main__":
    run("count Employees (sanity)", SQL_COUNTS, timeout_ms=15000)
    run("FIXED: pushdown LIMIT before OPTIONAL MATCH certs", SQL_FIXED_PUSHDOWN, timeout_ms=60000)
