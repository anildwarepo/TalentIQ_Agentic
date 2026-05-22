"""Post-load validation: count nodes/edges, verify indexes, spot-check data quality."""

from __future__ import annotations

import sys

import psycopg2

from talent_data_pipeline.config import db_config, pipeline_config
from talent_data_pipeline.pg_entra import pg_connect

EXPECTED_COUNTS = {
    "Employee": 130000,
    "Location": 46,
    "Country": 19,
    "Subregion": 15,
    "Skill": 96,
    "SkillDomain": 13,
    "Certification": 39,
    "Language": 18,
    "ServiceLine": 8,
    "Offering": 8,
    "Manager": 80,
    "University": 75,
    "Client": 36,
    "Project": 22,
}


def _count_nodes(cur, graph: str, label: str) -> int:
    """Count nodes of a given label."""
    try:
        cur.execute("SET search_path = ag_catalog, '$user', public;")
        cur.execute(
            f"SELECT count(*) FROM ag_catalog.cypher('{graph}', $$ "
            f"MATCH (n:{label}) RETURN count(n) $$) AS (cnt agtype);"
        )
        row = cur.fetchone()
        if row:
            return int(str(row[0]).strip('"'))
    except Exception:
        pass
    return -1


def _count_edges(cur, graph: str, label: str) -> int:
    """Count edges of a given label."""
    try:
        cur.execute("SET search_path = ag_catalog, '$user', public;")
        cur.execute(
            f"SELECT count(*) FROM ag_catalog.cypher('{graph}', $$ "
            f"MATCH ()-[r:{label}]->() RETURN count(r) $$) AS (cnt agtype);"
        )
        row = cur.fetchone()
        if row:
            return int(str(row[0]).strip('"'))
    except Exception:
        pass
    return -1


def _count_table(cur, table: str) -> int:
    try:
        cur.execute(f"SELECT count(*) FROM {table};")
        return cur.fetchone()[0]
    except Exception:
        return -1


def _list_indexes(cur, schema: str) -> list[str]:
    try:
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = %s ORDER BY indexname;",
            (schema,),
        )
        return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def run_validation() -> bool:
    """Run all post-load validation checks."""
    print("=" * 60)
    print("Post-Load Validation")
    print("=" * 60)

    conn = pg_connect()
    cur = conn.cursor()
    graph = pipeline_config.graph_name
    all_ok = True

    # 1. Node counts
    print("\n[1] Node Counts")
    for label, expected in EXPECTED_COUNTS.items():
        actual = _count_nodes(cur, graph, label)
        status = "OK" if actual == expected else f"MISMATCH (expected {expected})"
        if actual != expected:
            all_ok = False
        print(f"  {label:20s}: {actual:>8,} — {status}")

    # 2. Edge counts
    print("\n[2] Edge Counts")
    edge_labels = [
        "LOCATED_IN", "IN_COUNTRY", "SPECIALIZES_IN", "HAS_SKILL",
        "HOLDS_CERT", "SPEAKS", "BELONGS_TO_SL", "WORKS_IN_OFFERING",
        "REPORTS_TO", "STUDIED_AT", "WORKED_FOR", "WORKED_ON",
    ]
    for label in edge_labels:
        count = _count_edges(cur, graph, label)
        print(f"  {label:25s}: {count:>10,}")

    # 3. Relational table counts
    print("\n[3] Relational Table Counts")
    for table in ["employee_embeddings", "employee_fts"]:
        count = _count_table(cur, table)
        print(f"  {table:30s}: {count:>10,}")

    # 4. Index verification
    print("\n[4] Index Verification")
    for schema in ["public", graph]:
        indexes = _list_indexes(cur, schema)
        print(f"  Schema '{schema}': {len(indexes)} indexes")
        for idx in indexes[:10]:
            print(f"    - {idx}")
        if len(indexes) > 10:
            print(f"    ... and {len(indexes) - 10} more")

    # 5. Spot checks
    print("\n[5] Spot Checks")
    try:
        cur.execute("SET search_path = ag_catalog, '$user', public;")
        # Check bench rate
        cur.execute(
            f"SELECT count(*) FROM ag_catalog.cypher('{graph}', $$ "
            f"MATCH (e:Employee) WHERE e.is_bench = true RETURN count(e) $$) AS (cnt agtype);"
        )
        bench = int(str(cur.fetchone()[0]).strip('"'))
        bench_pct = bench / 130000 * 100 if bench > 0 else 0
        print(f"  Bench employees: {bench:,} ({bench_pct:.1f}%) — target ~25%")
    except Exception as exc:
        print(f"  Bench check failed: {exc}")

    cur.close()
    conn.close()

    print()
    print("=" * 60)
    if all_ok:
        print("VALIDATION PASSED")
    else:
        print("VALIDATION WARNINGS — review output above")
    print("=" * 60)
    return all_ok


def main() -> None:
    success = run_validation()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
