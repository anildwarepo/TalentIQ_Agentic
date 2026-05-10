"""Load pre-generated CSV data into PostgreSQL/AGE — no regeneration.

Reads from talent_synthetic_data/ and loads into the graph database,
vector tables, and FTS tables.  Supports checkpoint/resume so that
interrupted runs pick up where they left off.

Run standalone: python -m talent_data_pipeline.load [--reset]
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from typing import Any

from tqdm import tqdm

from talent_data_pipeline.checkpoint import LoadCheckpoint
from talent_data_pipeline.config import pipeline_config
from talent_data_pipeline.connectivity_test import run_connectivity_test
from talent_data_pipeline.schema.create_relational_tables import run_schema_creation
from talent_data_pipeline.schema.create_indexes import run_index_creation
from talent_data_pipeline.loaders.graph_loader import GraphLoader
from talent_data_pipeline.loaders.vector_loader import VectorLoader
from talent_data_pipeline.loaders.fts_loader import FTSLoader
from talent_data_pipeline.generators.embedding_generator import EmbeddingGenerator
from talent_data_pipeline.validate import run_validation

# CSV root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _REPO_ROOT / "talent_synthetic_data"
NODES_DIR = DATA_DIR / "nodes"
EDGES_DIR = DATA_DIR / "edges"


# ── CSV Readers ───────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into a list of dicts (all values as strings)."""
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _coerce_node(row: dict[str, str]) -> dict[str, Any]:
    """Best-effort type coercion for node properties."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v == "":
            out[k] = ""
        elif v in ("True", "False"):
            out[k] = v == "True"
        elif _is_int(v):
            out[k] = int(v)
        elif _is_float(v):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except ValueError:
        return False


def _is_float(s: str) -> bool:
    try:
        float(s)
        return "." in s  # only treat as float if decimal point present
    except ValueError:
        return False


def _read_nodes(filename: str) -> list[dict[str, Any]]:
    """Read a node CSV and coerce types."""
    path = NODES_DIR / filename
    if not path.exists():
        print(f"  WARNING: {path} not found, skipping")
        return []
    return [_coerce_node(row) for row in _read_csv(path)]


def _read_edge_csv(
    filename: str, from_col: str, to_col: str,
    from_key_name: str = "workday_id", to_key_name: str = "name",
) -> list[dict[str, Any]]:
    """Read an edge CSV and convert to the from_key/to_key/props format
    expected by GraphLoader.load_edges().

    from_col/to_col: CSV column names (e.g., 'employee_workday_id', 'skill_name')
    from_key_name/to_key_name: property names for the graph MATCH (e.g., 'workday_id', 'name')
    """
    path = EDGES_DIR / filename
    if not path.exists():
        print(f"  WARNING: {path} not found, skipping")
        return []

    rows = _read_csv(path)
    edges: list[dict[str, Any]] = []
    for row in rows:
        from_val = row.pop(from_col, "")
        to_val = row.pop(to_col, "")
        # Remaining columns are edge properties
        props = _coerce_node(row)
        edges.append({
            "from_key": (from_key_name, from_val),
            "to_key": (to_key_name, to_val),
            "props": props,
        })
    return edges


# ── Main Load Pipeline ────────────────────────────────────────────

def load_all() -> None:
    """Load all pre-generated CSV data into the database.

    Creates a checkpoint at the start so that interrupted runs can resume
    from the last successfully completed batch.
    """
    t0 = time.time()
    print("=" * 70)
    print("  TalentIQ Data Loader — From CSV")
    print(f"  Source: {DATA_DIR}")
    print("=" * 70)
    print()

    # Handle --reset flag
    if "--reset" in sys.argv:
        ckpt = LoadCheckpoint()
        ckpt.reset()
        EmbeddingGenerator.clear_checkpoint()
        print("🗑️  Checkpoint deleted — starting fresh load\n")

    # Create checkpoint
    ckpt = LoadCheckpoint()
    if ckpt.has_progress:
        print("📋 Resuming from checkpoint:")
        ckpt.print_summary()
        print()

    # Verify CSVs exist
    if not NODES_DIR.exists() or not EDGES_DIR.exists():
        print("FATAL: talent_synthetic_data/ not found. Run 'python -m talent_data_pipeline.generate' first.")
        sys.exit(1)

    emp_csv = NODES_DIR / "employees.csv"
    if not emp_csv.exists():
        print("FATAL: employees.csv not found. Run 'python -m talent_data_pipeline.generate' first.")
        sys.exit(1)

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
    if ckpt.is_phase_done("schema"):
        print("  ⏭️  schema — already created (checkpoint), skipping")
    else:
        run_schema_creation()
        ckpt.mark_phase_done("schema")
    print()

    # ── Phase 3: Read CSVs ────────────────────────────────────────
    print("━" * 70)
    print("PHASE 3: Reading CSV Data")
    print("━" * 70)

    # Reference nodes
    ref_data: dict[str, list[dict[str, Any]]] = {}
    ref_files = {
        "Country": "countries.csv",
        "Subregion": "subregions.csv",
        "Location": "locations.csv",
        "Skill": "skills.csv",
        "SkillDomain": "skill_domains.csv",
        "Certification": "certifications.csv",
        "Language": "languages.csv",
        "ServiceLine": "service_lines.csv",
        "Offering": "offerings.csv",
        "Manager": "managers.csv",
        "University": "universities.csv",
        "Client": "clients.csv",
        "Project": "projects.csv",
    }
    for label, filename in ref_files.items():
        nodes = _read_nodes(filename)
        ref_data[label] = nodes
        print(f"  ✓ {label}: {len(nodes):,} rows")

    # Employees
    employees = _read_nodes("employees.csv")
    print(f"  ✓ Employees: {len(employees):,} rows")

    # Edges — read with correct column mappings
    print()
    in_country = _read_edge_csv("in_country.csv", "location_city", "country_code",
                                 from_key_name="city", to_key_name="code")
    print(f"  ✓ in_country: {len(in_country):,} edges")

    # (csv_file, csv_from_col, csv_to_col, graph_from_key, graph_to_key)
    edge_files = [
        ("located_in.csv",        "employee_workday_id", "location_city",      "workday_id", "city"),
        ("specializes_in.csv",    "employee_workday_id", "skill_domain_name",  "workday_id", "name"),
        ("has_skill.csv",         "employee_workday_id", "skill_name",         "workday_id", "name"),
        ("holds_cert.csv",        "employee_workday_id", "certification_name", "workday_id", "name"),
        ("speaks.csv",            "employee_workday_id", "language_name",      "workday_id", "name"),
        ("belongs_to_sl.csv",     "employee_workday_id", "service_line_name",  "workday_id", "name"),
        ("works_in_offering.csv", "employee_workday_id", "offering_name",      "workday_id", "name"),
        ("reports_to.csv",        "employee_workday_id", "manager_employee_id","workday_id", "employee_id"),
        ("studied_at.csv",        "employee_workday_id", "university_name",    "workday_id", "name"),
        ("worked_for.csv",        "employee_workday_id", "client_name",        "workday_id", "name"),
        ("worked_on.csv",         "employee_workday_id", "project_name",       "workday_id", "name"),
    ]

    edge_data: dict[str, list[dict[str, Any]]] = {}
    for filename, from_col, to_col, fk_name, tk_name in edge_files:
        name = filename.replace(".csv", "")
        edges = _read_edge_csv(filename, from_col, to_col, fk_name, tk_name)
        edge_data[name] = edges
        print(f"  ✓ {name}: {len(edges):,} edges")

    print()

    # ── Phase 4: Load into AGE Graph ──────────────────────────────
    print("━" * 70)
    print("PHASE 4: Graph Loading")
    print("━" * 70)

    graph_loader = GraphLoader()

    # [4a] Reference nodes (Cypher MERGE — ~500 nodes, fast)
    print("\n[4a] Reference nodes...")
    graph_loader.load_reference_nodes(ref_data, checkpoint=ckpt)

    # [4b] Employee nodes (Cypher MERGE — checkpointed)
    print("\n[4b] Employee nodes...")
    graph_loader.load_employees(employees, checkpoint=ckpt)

    # [4c] Build node ID lookups for direct SQL edge loading
    print("\n[4c] Building node ID lookups...")
    lookups = graph_loader.build_all_lookups()
    for label, lookup in sorted(lookups.items()):
        print(f"  ✓ {label}: {len(lookup):,} IDs")

    # [4d] ALL edges via direct SQL batch INSERT (10-100x faster than Cypher)
    print("\n[4d] Loading edges (direct SQL batch INSERT)...")
    edge_data["in_country"] = in_country

    edge_configs = [
        ("IN_COUNTRY",        "Location",  "Country",       "in_country"),
        ("LOCATED_IN",        "Employee",  "Location",      "located_in"),
        ("SPECIALIZES_IN",    "Employee",  "SkillDomain",   "specializes_in"),
        ("HAS_SKILL",         "Employee",  "Skill",         "has_skill"),
        ("HOLDS_CERT",        "Employee",  "Certification", "holds_cert"),
        ("SPEAKS",            "Employee",  "Language",       "speaks"),
        ("BELONGS_TO_SL",     "Employee",  "ServiceLine",   "belongs_to_sl"),
        ("WORKS_IN_OFFERING", "Employee",  "Offering",      "works_in_offering"),
        ("REPORTS_TO",        "Employee",  "Manager",       "reports_to"),
        ("STUDIED_AT",        "Employee",  "University",    "studied_at"),
        ("WORKED_FOR",        "Employee",  "Client",        "worked_for"),
        ("WORKED_ON",         "Employee",  "Project",       "worked_on"),
    ]

    for edge_label, from_l, to_l, edge_name in edge_configs:
        graph_loader.load_edges_direct(
            edge_label, from_l, to_l,
            edge_data[edge_name],
            from_lookup=lookups[from_l],
            to_lookup=lookups[to_l],
            checkpoint=ckpt, phase_key=f"edges:{edge_label}",
        )

    graph_loader.close()

    # ── Phase 5: Embeddings ───────────────────────────────────────
    print()
    print("━" * 70)
    print("PHASE 5: Vector Embeddings (Azure OpenAI)")
    print("━" * 70)

    if ckpt.is_phase_done("embeddings"):
        print("  ⏭️  embeddings — already loaded (checkpoint), skipping")
    else:
        emb_gen = EmbeddingGenerator()
        batch_size = 100
        total_batches = -(-len(employees) // batch_size)

        # Stream: disk/API → parallel DB insert (no full-dataset memory load)
        batch_iter = emb_gen.iter_embedding_batches(
            employees, edge_data["has_skill"], batch_size=batch_size
        )

        vec_loader = VectorLoader()
        vec_loader.load_embeddings_streaming(
            batch_iter, total_batches,
            checkpoint=ckpt, phase_key="embeddings",
            workers=4,
        )
        vec_loader.close()
    # Clean up generation checkpoint once embeddings are in the DB
    if ckpt.is_phase_done("embeddings"):
        EmbeddingGenerator.clear_checkpoint()
    # ── Phase 6: Full-Text Search ─────────────────────────────────
    print()
    print("━" * 70)
    print("PHASE 6: Full-Text Search")
    print("━" * 70)

    fts_loader = FTSLoader()
    fts_loader.load_fts_data(
        employees, edge_data["has_skill"], edge_data["holds_cert"],
        checkpoint=ckpt, phase_key="fts",
    )
    fts_loader.close()

    # ── Phase 7: Index Creation ───────────────────────────────────
    print()
    print("━" * 70)
    print("PHASE 7: Index Creation")
    print("━" * 70)
    if ckpt.is_phase_done("indexes"):
        print("  ⏭️  indexes — already created (checkpoint), skipping")
    else:
        run_index_creation()
        ckpt.mark_phase_done("indexes")

    # ── Phase 8: Validation ───────────────────────────────────────
    print()
    print("━" * 70)
    print("PHASE 8: Post-Load Validation")
    print("━" * 70)
    run_validation()

    # Flush any remaining checkpoint data
    ckpt.flush()

    elapsed = time.time() - t0
    print()
    print("=" * 70)
    print(f"  ✅ All phases complete in {elapsed / 60:.1f} minutes")
    print("=" * 70)


def main() -> None:
    """Entry point for python -m talent_data_pipeline.load."""
    load_all()


if __name__ == "__main__":
    main()
