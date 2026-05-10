"""Generate all synthetic data and write to CSV files in talent_synthetic_data/.

This module is DATABASE-FREE — it only generates data and writes CSVs.
Run standalone: python -m talent_data_pipeline.generate
"""

from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path
from typing import Any

from tqdm import tqdm

from talent_data_pipeline.generators.reference_data import (
    ALL_SKILLS,
    CERTIFICATIONS,
    CLIENTS,
    COUNTRIES,
    LANGUAGES,
    LOCATIONS,
    MANAGERS,
    OFFERINGS,
    PROJECTS,
    SERVICE_LINES,
    SKILL_DOMAINS,
    SUBREGIONS,
    UNIVERSITIES,
    ReferenceDataGenerator,
)
from talent_data_pipeline.generators.employee_generator import EmployeeGenerator
from talent_data_pipeline.generators.edge_generator import EdgeGenerator
from talent_data_pipeline.generators.resume_generator import ResumeGenerator

# Output root — always at repo root / talent_synthetic_data
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = _REPO_ROOT / "talent_synthetic_data"
NODES_DIR = OUTPUT_DIR / "nodes"
EDGES_DIR = OUTPUT_DIR / "edges"

# Employee properties to write (excludes internal _-prefixed fields)
EMPLOYEE_COLUMNS = [
    "name", "first_name", "last_name", "email", "phone", "workday_id",
    "job_title", "job_level", "skill_level", "hire_date", "years_of_experience",
    "employment_status", "is_bench", "bench_start_date", "bench_duration_days",
    "availability_date", "current_project",
    "fte_current_month", "fte_next_month", "fte_next2_month",
    "hourly_cost_usd", "bill_rate_usd",
    "cv_last_updated", "cv_freshness_days", "cv_source",
    "impressiveness_score", "data_source", "delivery_model",
    "eqf_level", "meces_level", "eqf_mapping_status",
    "education_degree", "education_field", "resume_summary",
]


def _ensure_dirs() -> None:
    """Create output directories."""
    NODES_DIR.mkdir(parents=True, exist_ok=True)
    EDGES_DIR.mkdir(parents=True, exist_ok=True)


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> int:
    """Write a list of dicts to CSV. Returns row count."""
    if not rows:
        return 0
    if columns is None:
        columns = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _flatten_edge(edge: dict[str, Any], from_col: str, to_col: str) -> dict[str, Any]:
    """Flatten an edge dict with from_key/to_key tuples into a flat dict."""
    row: dict[str, Any] = {}
    # from_key is a tuple like ("workday_id", "WD-100001")
    fk = edge["from_key"]
    row[from_col] = fk[1] if isinstance(fk, tuple) else fk
    # to_key is a tuple like ("name", "Django")
    tk = edge["to_key"]
    row[to_col] = tk[1] if isinstance(tk, tuple) else tk
    # Merge edge properties
    if "props" in edge:
        row.update(edge["props"])
    return row


def _flatten_edges(
    edges: list[dict[str, Any]], from_col: str, to_col: str
) -> list[dict[str, Any]]:
    """Flatten a list of edges into flat dicts."""
    return [_flatten_edge(e, from_col, to_col) for e in edges]


def _write_edge_csv(
    path: Path,
    edges: list[dict[str, Any]],
    from_col: str,
    to_col: str,
) -> int:
    """Flatten edges and write to CSV."""
    flat = _flatten_edges(edges, from_col, to_col)
    return _write_csv(path, flat)


def generate_all() -> None:
    """Generate all synthetic data and write to talent_synthetic_data/."""
    t0 = time.time()
    print("=" * 70)
    print("  TalentIQ Synthetic Data Generator")
    print("  Output: talent_synthetic_data/")
    print("=" * 70)
    print()

    _ensure_dirs()

    # ── Node data ──────────────────────────────────────────────────
    print("━" * 70)
    print("PHASE 1: Reference Node Data")
    print("━" * 70)

    node_files = {
        "countries": (NODES_DIR / "countries.csv", COUNTRIES),
        "subregions": (NODES_DIR / "subregions.csv", SUBREGIONS),
        "locations": (NODES_DIR / "locations.csv", LOCATIONS),
        "skills": (NODES_DIR / "skills.csv", ALL_SKILLS),
        "skill_domains": (NODES_DIR / "skill_domains.csv", SKILL_DOMAINS),
        "certifications": (NODES_DIR / "certifications.csv", CERTIFICATIONS),
        "languages": (NODES_DIR / "languages.csv", LANGUAGES),
        "service_lines": (NODES_DIR / "service_lines.csv", SERVICE_LINES),
        "offerings": (NODES_DIR / "offerings.csv", OFFERINGS),
        "managers": (NODES_DIR / "managers.csv", MANAGERS),
        "universities": (NODES_DIR / "universities.csv", UNIVERSITIES),
        "clients": (NODES_DIR / "clients.csv", CLIENTS),
        "projects": (NODES_DIR / "projects.csv", PROJECTS),
    }

    for label, (path, data) in node_files.items():
        n = _write_csv(path, data)
        print(f"  ✓ {label}: {n:,} rows → {path.name}")

    print()

    # ── Employee generation ────────────────────────────────────────
    print("━" * 70)
    print("PHASE 2: Employee Generation (130,000)")
    print("━" * 70)

    emp_gen = EmployeeGenerator()
    employees = emp_gen.generate_all()

    # Add resume summaries
    print("\nGenerating resume summaries...")
    resume_gen = ResumeGenerator()
    employees = resume_gen.generate_summaries(employees)

    # Write employees (exclude _-prefixed internal fields)
    n = _write_csv(NODES_DIR / "employees.csv", employees, columns=EMPLOYEE_COLUMNS)
    print(f"  ✓ employees: {n:,} rows → employees.csv")
    print()

    # ── Edge generation ────────────────────────────────────────────
    print("━" * 70)
    print("PHASE 3: Edge Generation (~2.6M edges)")
    print("━" * 70)

    # IN_COUNTRY edges (from reference data)
    ref_gen = ReferenceDataGenerator()
    in_country_raw = ref_gen.generate_location_country_edges()
    in_country = [
        {"location_city": e["from_key"][1], "country_code": e["to_key"][1]}
        for e in in_country_raw
    ]
    n = _write_csv(EDGES_DIR / "in_country.csv", in_country)
    print(f"  ✓ in_country: {n:,} edges → in_country.csv")

    # Employee edges
    edge_gen = EdgeGenerator(employees)

    edge_tasks = [
        ("located_in",      edge_gen.generate_located_in,       "employee_workday_id", "location_city"),
        ("specializes_in",  edge_gen.generate_specializes_in,   "employee_workday_id", "skill_domain_name"),
        ("has_skill",       edge_gen.generate_has_skill,         "employee_workday_id", "skill_name"),
        ("holds_cert",      edge_gen.generate_holds_cert,        "employee_workday_id", "certification_name"),
        ("speaks",          edge_gen.generate_speaks,             "employee_workday_id", "language_name"),
        ("belongs_to_sl",   edge_gen.generate_belongs_to_sl,     "employee_workday_id", "service_line_name"),
        ("works_in_offering", edge_gen.generate_works_in_offering, "employee_workday_id", "offering_name"),
        ("reports_to",      edge_gen.generate_reports_to,        "employee_workday_id", "manager_employee_id"),
        ("studied_at",      edge_gen.generate_studied_at,        "employee_workday_id", "university_name"),
        ("worked_for",      edge_gen.generate_worked_for,        "employee_workday_id", "client_name"),
        ("worked_on",       edge_gen.generate_worked_on,         "employee_workday_id", "project_name"),
    ]

    total_edges = 0
    for edge_name, gen_func, from_col, to_col in edge_tasks:
        edges = gen_func()
        path = EDGES_DIR / f"{edge_name}.csv"
        n = _write_edge_csv(path, edges, from_col, to_col)
        total_edges += n
        print(f"  ✓ {edge_name}: {n:,} edges → {edge_name}.csv")

    elapsed = time.time() - t0
    print()
    print("=" * 70)
    print(f"  Generation complete in {elapsed / 60:.1f} minutes")
    print(f"  Total edge count: {total_edges:,}")
    print(f"  Output directory: {OUTPUT_DIR}")
    print("=" * 70)


def main() -> None:
    """Entry point for python -m talent_data_pipeline.generate."""
    generate_all()


if __name__ == "__main__":
    main()
