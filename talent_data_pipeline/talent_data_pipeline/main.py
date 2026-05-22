"""Main orchestrator — runs the complete TalentIQ data pipeline end-to-end."""

from __future__ import annotations

import argparse
import os
import sys
import time

import psycopg2

from talent_data_pipeline.config import apply_host_override, db_config, pipeline_config
from talent_data_pipeline.pg_entra import pg_connect
from talent_data_pipeline.connectivity_test import run_connectivity_test
from talent_data_pipeline.schema.create_relational_tables import run_schema_creation
from talent_data_pipeline.schema.create_indexes import (
    run_age_label_indexes,
    run_index_creation,
)
from talent_data_pipeline.generators.reference_data import ReferenceDataGenerator
from talent_data_pipeline.generators.employee_generator import EmployeeGenerator
from talent_data_pipeline.generators.edge_generator import EdgeGenerator
from talent_data_pipeline.generators.resume_generator import ResumeGenerator
from talent_data_pipeline.generators.embedding_generator import EmbeddingGenerator
from talent_data_pipeline.loaders.graph_loader import GraphLoader
from talent_data_pipeline.loaders.vector_loader import VectorLoader
from talent_data_pipeline.loaders.fts_loader import FTSLoader
from talent_data_pipeline.loaders.entity_search_loader import EntitySearchLoader
from talent_data_pipeline.validate import run_validation


_VALID_MODES = ("env", "manual")
_MAX_HOST_PROMPT_ATTEMPTS = 3


def _resolve_mode(cli_mode: str | None) -> str:
    """Resolve the dataload mode using the documented precedence.

    Order: ``--mode`` CLI flag > ``DATALOAD_MODE`` env var > default ``"env"``.
    Invalid env-var values produce a fatal error rather than silently falling
    back, so an automation typo does not accidentally trigger a prompt path
    (or skip one that was expected).
    """
    if cli_mode is not None:
        return cli_mode
    env_mode = os.getenv("DATALOAD_MODE", "").strip().lower()
    if env_mode:
        if env_mode not in _VALID_MODES:
            print(
                f"FATAL: DATALOAD_MODE={env_mode!r} is invalid. "
                f"Expected one of: {', '.join(_VALID_MODES)}."
            )
            sys.exit(2)
        return env_mode
    return "env"


def _resolve_manual_host() -> str:
    """Prompt the operator for the PG hostname.

    Shows the current ``PGHOST`` value (if any) as the default in square
    brackets. Pressing Enter accepts the default; otherwise the typed value
    (whitespace-trimmed) is used. Re-prompts on empty input when no default
    is available, up to ``_MAX_HOST_PROMPT_ATTEMPTS`` total attempts before
    exiting non-zero.
    """
    current = os.getenv("PGHOST", "").strip()
    prompt_suffix = f" [{current}]" if current else ""
    for attempt in range(_MAX_HOST_PROMPT_ATTEMPTS):
        raw = input(f"PG host{prompt_suffix}: ").strip()
        if raw:
            return raw
        if current:
            return current
        remaining = _MAX_HOST_PROMPT_ATTEMPTS - attempt - 1
        if remaining > 0:
            print(
                f"  ERROR: empty input and no PGHOST default in .env. "
                f"({remaining} attempt(s) remaining)"
            )
    print(
        "FATAL: no PG host provided after "
        f"{_MAX_HOST_PROMPT_ATTEMPTS} attempts. Exiting."
    )
    sys.exit(2)


def _data_already_loaded() -> tuple[bool, dict[str, int]]:
    """Check whether the graph + embeddings tables already contain the expected data.

    Returns (is_loaded, counts) where counts is a dict of probe → row count.
    Considered "loaded" when:
        - Employee node count >= 90% of configured EMPLOYEE_COUNT, AND
        - employee_embeddings row count >= 90% of configured EMPLOYEE_COUNT.
    Any probe failure returns (False, {...}) so the pipeline falls back to a full run.
    """
    counts = {"employees": -1, "embeddings": -1, "has_skill": -1}
    threshold = int(pipeline_config.employee_count * 0.9)
    graph = pipeline_config.graph_name
    try:
        conn = pg_connect()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET search_path = ag_catalog, '$user', public;")
            try:
                cur.execute(
                    f"SELECT (cnt::text)::bigint FROM ag_catalog.cypher('{graph}', $$ "
                    f"MATCH (n:Employee) RETURN count(n) $$) AS (cnt agtype);"
                )
                row = cur.fetchone()
                if row:
                    counts["employees"] = int(row[0])
            except Exception:
                pass
            try:
                cur.execute(
                    f"SELECT (cnt::text)::bigint FROM ag_catalog.cypher('{graph}', $$ "
                    f"MATCH ()-[r:HAS_SKILL]->() RETURN count(r) $$) AS (cnt agtype);"
                )
                row = cur.fetchone()
                if row:
                    counts["has_skill"] = int(row[0])
            except Exception:
                pass
            try:
                cur.execute("SELECT count(*) FROM employee_embeddings;")
                row = cur.fetchone()
                if row:
                    counts["embeddings"] = int(row[0])
            except Exception:
                pass
        conn.close()
    except Exception as e:
        print(f"  WARNING: could not probe existing data ({e}). Will run full pipeline.")
        return False, counts

    loaded = (
        counts["employees"] >= threshold
        and counts["embeddings"] >= threshold
    )
    return loaded, counts


def main(force: bool = False) -> None:
    """Run the full data pipeline.

    Args:
        force: If True, regenerate and re-load data even when it already exists.
               Otherwise the pipeline skips Phase 3 (generation) and Phase 4 (loading)
               when the graph + embeddings tables look populated, jumping straight to
               Phase 5 (indexes, idempotent) and Phase 6 (validation).
    """
    t0 = time.time()
    print("=" * 70)
    print("  TalentIQ Data Pipeline — Full Run")
    print("=" * 70)
    print()

    # ── Phase 1: Connectivity ─────────────────────────────────────
    print("━" * 70)
    print("PHASE 1: Connectivity Test")
    print("━" * 70)
    if not run_connectivity_test():
        print("FATAL: Connectivity test failed. Aborting.")
        sys.exit(1)
    print()

    # ── Phase 2: Schema Creation ──────────────────────────────────
    print("━" * 70)
    print("PHASE 2: Schema & Label Creation")
    print("━" * 70)
    run_schema_creation()
    # AGE label property indexes — created NOW (empty tables, instant) so that
    # Phase 4 Cypher MERGE uses an index instead of seq-scanning a growing
    # label table (which would make the load O(N²)).
    run_age_label_indexes()
    print()

    # ── Phase 3: Data Generation ──────────────────────────────────
    print("━" * 70)
    print("PHASE 3: Data Generation")
    print("━" * 70)

    # Skip Phase 3 + Phase 4 if data is already loaded (unless --force).
    loaded, counts = _data_already_loaded()
    if loaded and not force:
        print(
            f"\n  Existing data detected — skipping Phase 3 (generation) and "
            f"Phase 4 (loading)."
        )
        print(
            f"    Employees in graph : {counts['employees']:>10,}"
        )
        print(
            f"    HAS_SKILL edges    : {counts['has_skill']:>10,}"
        )
        print(
            f"    employee_embeddings: {counts['embeddings']:>10,}"
        )
        print(
            "    Use --force (or set FORCE_REGENERATE=true) to regenerate from scratch."
        )
        print()
    else:
        if force and (counts["employees"] > 0 or counts["embeddings"] > 0):
            print(
                f"\n  --force specified — regenerating despite existing data "
                f"(employees={counts['employees']:,}, "
                f"embeddings={counts['embeddings']:,})."
            )
        _run_generation_and_loading()

    # ── Phase 5: Index Creation ───────────────────────────────────
    print("━" * 70)
    print("PHASE 5: Index Creation")
    print("━" * 70)
    run_index_creation()
    print()

    # ── Phase 6: Validation ───────────────────────────────────────
    print("━" * 70)
    print("PHASE 6: Post-Load Validation")
    print("━" * 70)
    run_validation()

    elapsed = time.time() - t0
    print()
    print("=" * 70)
    print(f"  Pipeline complete in {elapsed / 60:.1f} minutes")
    print("=" * 70)


def _run_generation_and_loading() -> None:
    """Run Phase 3 (generate in-memory data) and Phase 4 (load to graph + tables)."""

    # 3a. Reference data
    print("\n[3a] Reference data...")
    ref_gen = ReferenceDataGenerator()
    ref_data = ref_gen.generate_all()
    location_country_edges = ref_gen.generate_location_country_edges()

    # 3b. Employees
    print("\n[3b] Employees...")
    emp_gen = EmployeeGenerator()
    employees = emp_gen.generate_all()

    # 3c. Resume summaries
    print("\n[3c] Resume summaries...")
    resume_gen = ResumeGenerator()
    employees = resume_gen.generate_summaries(employees)

    # 3d. Edges
    print("\n[3d] Edges...")
    edge_gen = EdgeGenerator(employees)

    located_in = edge_gen.generate_located_in()
    specializes_in = edge_gen.generate_specializes_in()
    has_skill = edge_gen.generate_has_skill()
    holds_cert = edge_gen.generate_holds_cert()
    speaks = edge_gen.generate_speaks()
    belongs_to_sl = edge_gen.generate_belongs_to_sl()
    works_in_offering = edge_gen.generate_works_in_offering()
    reports_to = edge_gen.generate_reports_to()
    studied_at = edge_gen.generate_studied_at()
    worked_for = edge_gen.generate_worked_for()
    worked_on = edge_gen.generate_worked_on()
    has_role = edge_gen.generate_has_role()

    # 3e. Embeddings
    print("\n[3e] Embeddings...")
    emb_gen = EmbeddingGenerator()
    embeddings = emb_gen.generate_embeddings(employees, has_skill)

    print()

    # ── Phase 4: Data Loading ─────────────────────────────────────
    print("━" * 70)
    print("PHASE 4: Data Loading")
    print("━" * 70)

    graph_loader = GraphLoader()

    # 4a. Reference nodes
    print("\n[4a] Reference nodes...")
    graph_loader.load_reference_nodes_direct(ref_data)

    # 4b. Location → Country edges (small — Cypher MERGE is fine here).
    # Phase 4a truncated Location/Country and reassigned graphids, so any
    # pre-existing IN_COUNTRY rows now reference dead vertices. Truncate
    # before the MERGE so the table only holds valid edges.
    print("\n[4b] Location → Country edges...")
    if "--no-truncate" not in sys.argv:
        graph_loader.truncate_label("IN_COUNTRY")
    graph_loader.load_edges(
        "IN_COUNTRY", "Location", "Country",
        location_country_edges,
        from_key_prop="city", to_key_prop="code",
    )

    # 4c. Employee nodes (direct SQL INSERT — fast path)
    print("\n[4c] Employee nodes...")
    graph_loader.load_employees_direct(employees)

    # 4c.5 Build {label → {key → graphid}} lookups for direct edge INSERT.
    # Done once after all nodes are in place; reused for every edge type.
    print("\n[4c.5] Building node lookups...")
    lookups = graph_loader.build_all_lookups()

    # 4d. All employee edges (direct SQL INSERT — fast path)
    print("\n[4d] Employee edges...")
    edge_configs = [
        ("LOCATED_IN",        "Employee", "Location",    located_in,        "workday_id", "city"),
        ("SPECIALIZES_IN",    "Employee", "SkillDomain", specializes_in,    "workday_id", "name"),
        ("HAS_SKILL",         "Employee", "Skill",       has_skill,         "workday_id", "name"),
        ("HOLDS_CERT",        "Employee", "Certification",holds_cert,       "workday_id", "name"),
        ("SPEAKS",            "Employee", "Language",     speaks,           "workday_id", "name"),
        ("BELONGS_TO_SL",     "Employee", "ServiceLine",  belongs_to_sl,   "workday_id", "name"),
        ("WORKS_IN_OFFERING", "Employee", "Offering",     works_in_offering,"workday_id", "name"),
        ("REPORTS_TO",        "Employee", "Manager",      reports_to,       "workday_id", "employee_id"),
        ("STUDIED_AT",        "Employee", "University",   studied_at,       "workday_id", "name"),
        ("WORKED_FOR",        "Employee", "Client",       worked_for,       "workday_id", "name"),
        ("WORKED_ON",         "Employee", "Project",      worked_on,        "workday_id", "name"),
        ("HAS_ROLE",          "Employee", "Role",         has_role,         "workday_id", "name"),
    ]

    for edge_label, from_l, to_l, edges, _fk, _tk in edge_configs:
        graph_loader.load_edges_direct(
            edge_label, from_l, to_l, edges,
            from_lookup=lookups[from_l],
            to_lookup=lookups[to_l],
            phase_key=f"edges:{edge_label}",
        )

    graph_loader.close()

    # 4e. Vectors
    print("\n[4e] Vector embeddings...")
    vec_loader = VectorLoader()
    vec_loader.load_embeddings(embeddings)
    vec_loader.close()

    # 4f. Full-text search
    print("\n[4f] Full-text search...")
    fts_loader = FTSLoader()
    fts_loader.load_fts_data(employees, has_skill, holds_cert)
    fts_loader.close()

    # 4g. Entity search (reference entities)
    print("\n[4g] Entity search...")
    entity_loader = EntitySearchLoader()
    entity_loader.load_entity_search()

    # 4h. Entity embeddings
    print("\n[4h] Entity embeddings...")
    entity_loader.embed_entities()
    entity_loader.close()

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="talent_data_pipeline",
        description="Run the TalentIQ data generation + loading pipeline.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=os.getenv("FORCE_REGENERATE", "").lower() in ("1", "true", "yes"),
        help=(
            "Regenerate and re-load data even when the graph and embeddings "
            "tables already look populated. Defaults to false (skip if loaded). "
            "Can also be enabled via the FORCE_REGENERATE environment variable."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("env", "manual"),
        default=None,
        help=(
            "Dataload mode selecting how the PostgreSQL host is resolved. "
            "'env' (default) reads PGHOST and all other connection settings "
            "from .env / environment with no prompts. 'manual' prompts the "
            "operator interactively for the PG hostname at startup (everything "
            "else still comes from .env). Resolution order: --mode flag > "
            "DATALOAD_MODE env var > 'env'."
        ),
    )
    args = parser.parse_args()

    mode = _resolve_mode(args.mode)
    if mode == "manual":
        if not sys.stdin.isatty():
            print(
                "FATAL: --mode manual requires an interactive terminal "
                "(stdin is not a TTY)."
            )
            print(
                "For non-interactive automation, use --mode env or set "
                "DATALOAD_MODE=env."
            )
            sys.exit(2)
        override_host = _resolve_manual_host()
        apply_host_override(override_host)
        host_origin = "overridden via prompt"
    else:
        host_origin = "from .env"

    print(
        f"[pipeline] mode={mode}  host={db_config.host}  ({host_origin})"
    )

    main(force=args.force)

