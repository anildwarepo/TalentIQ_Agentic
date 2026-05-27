"""Fetch sample rows from Talent Search source tables in Unity Catalog and save
each one as a local CSV.

Auth: Databricks OAuth U2M (browser-based). On first run a browser tab opens for
sign-in; subsequent runs reuse the cached token.

Setup (one-time):
    uv pip install "databricks-sql-connector>=3.0.0"

Optional env-var overrides (defaults are baked in below):
    DATABRICKS_SERVER_HOSTNAME
    DATABRICKS_HTTP_PATH

Run:
    python .scratch/fetch_employee_skills.py
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

from databricks import sql

SERVER_HOSTNAME = os.environ.get(
    "DATABRICKS_SERVER_HOSTNAME",
    "adb-1783757028296930.10.azuredatabricks.net",
)
HTTP_PATH = os.environ.get(
    "DATABRICKS_HTTP_PATH",
    "/sql/1.0/warehouses/1cd917431a048624",
)

ROW_LIMIT = 1000
OUTPUT_DIR = Path(__file__).parent / "talent_search_samples"

# (schema, table). Catalog is resolved at runtime via discover_catalog_map().
TABLES = [
    ("datawarehouse_gld",              "gold_internal_mobility_data_gras"),
    ("datawarehouse_gld",              "gold_luxskill_benchiq_employee"),
    ("datawarehouse_gld",              "gold_luxskill_benchiq_employee_domain"),
    ("datawarehouse_gld",              "gold_luxskill_benchiq_employee_language_proficiency"),
    ("datawarehouse_gld",              "gold_luxskill_benchiq_employee_skill"),
    ("datawarehouse_gld",              "gold_luxskill_benchiq_job_experience"),
    ("service_project_management_gld", "assignment_allocation"),
    ("service_project_management_gld", "contact"),
    ("service_project_management_gld", "pse_assignment"),
    ("service_project_management_gld", "pse_holidays"),
    ("service_project_management_gld", "pse_practice"),
    ("service_project_management_gld", "pse_project"),
    ("service_project_management_gld", "pse_region"),
    ("service_project_management_gld", "pse_resource_request"),
    ("service_project_management_gld", "pse_resource_skill_request"),
    ("service_project_management_gld", "pse_skill"),
    ("service_project_management_gld", "pse_work_calendar"),
    ("workforce_gld",                  "employee_skills"),
    ("workforce_gld",                  "workermaster"),
]


def discover_catalog_map(cursor, schemas_needed: set[str]) -> dict[str, str]:
    """Map each schema name to the first catalog that contains it.

    Walks `SHOW CATALOGS` then `SHOW SCHEMAS IN <catalog>`. Skips catalogs the
    caller can't list (insufficient privileges raise and are swallowed).
    """
    cursor.execute("SHOW CATALOGS")
    catalogs = [r[0] for r in cursor.fetchall()]
    print(f"Discovering catalogs for {len(schemas_needed)} schema(s) across {len(catalogs)} catalog(s)...")

    mapping: dict[str, str] = {}
    remaining = set(schemas_needed)
    for cat in catalogs:
        if not remaining:
            break
        try:
            cursor.execute(f"SHOW SCHEMAS IN `{cat}`")
            cat_schemas = {r[0] for r in cursor.fetchall()}
        except Exception:
            continue
        hits = remaining & cat_schemas
        for s in hits:
            mapping[s] = cat
            print(f"  {s}  ->  {cat}")
        remaining -= hits

    if remaining:
        print(f"  [WARN] no catalog found containing schema(s): {sorted(remaining)}")
    return mapping


def export_table(cursor, catalog: str, schema: str, table: str) -> tuple[int, Path]:
    fq = f"`{catalog}`.`{schema}`.`{table}`"
    cursor.execute(f"SELECT * FROM {fq} LIMIT {ROW_LIMIT}")
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()

    out_path = OUTPUT_DIR / f"{schema}__{table}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    return len(rows), out_path


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Host:        {SERVER_HOSTNAME}")
    print(f"HTTP path:   {HTTP_PATH}")
    print(f"Output dir:  {OUTPUT_DIR}")
    print("Auth:        Databricks OAuth U2M (browser will open on first run)\n")

    schemas_needed = {schema for schema, _ in TABLES}

    failures: list[tuple[str, str]] = []
    with sql.connect(
        server_hostname=SERVER_HOSTNAME,
        http_path=HTTP_PATH,
        auth_type="databricks-oauth",
    ) as conn:
        with conn.cursor() as cur:
            schema_to_catalog = discover_catalog_map(cur, schemas_needed)
            print()

            for schema, table in TABLES:
                catalog = schema_to_catalog.get(schema)
                fq_label = f"{catalog or '?'}.{schema}.{table}"
                if catalog is None:
                    failures.append((fq_label, "no catalog discovered for schema"))
                    print(f"SKIP {fq_label:80s} no catalog discovered for schema")
                    continue
                try:
                    n, path = export_table(cur, catalog, schema, table)
                    print(f"OK   {fq_label:80s} rows={n:>5}  ->  {path.name}")
                except Exception as e:
                    failures.append((fq_label, str(e)))
                    print(f"FAIL {fq_label:80s} {e}")

    print(f"\nDone. {len(TABLES) - len(failures)}/{len(TABLES)} tables exported.")
    if failures:
        print("\nFailures:")
        for fq, err in failures:
            print(f"  {fq}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
