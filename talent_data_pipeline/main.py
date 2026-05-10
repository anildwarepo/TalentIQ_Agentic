"""Main orchestrator — runs the complete TalentIQ data pipeline end-to-end."""

from __future__ import annotations

import sys
import time

from talent_data_pipeline.connectivity_test import run_connectivity_test
from talent_data_pipeline.schema.create_relational_tables import run_schema_creation
from talent_data_pipeline.schema.create_indexes import run_index_creation
from talent_data_pipeline.generators.reference_data import ReferenceDataGenerator
from talent_data_pipeline.generators.employee_generator import EmployeeGenerator
from talent_data_pipeline.generators.edge_generator import EdgeGenerator
from talent_data_pipeline.generators.resume_generator import ResumeGenerator
from talent_data_pipeline.generators.embedding_generator import EmbeddingGenerator
from talent_data_pipeline.loaders.graph_loader import GraphLoader
from talent_data_pipeline.loaders.vector_loader import VectorLoader
from talent_data_pipeline.loaders.fts_loader import FTSLoader
from talent_data_pipeline.validate import run_validation


def main() -> None:
    """Run the full data pipeline."""
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
    print()

    # ── Phase 3: Data Generation ──────────────────────────────────
    print("━" * 70)
    print("PHASE 3: Data Generation")
    print("━" * 70)

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
    graph_loader.load_reference_nodes(ref_data)

    # 4b. Location → Country edges
    print("\n[4b] Location → Country edges...")
    graph_loader.load_edges(
        "IN_COUNTRY", "Location", "Country",
        location_country_edges,
        from_key_prop="city", to_key_prop="code",
    )

    # 4c. Employee nodes (batched)
    print("\n[4c] Employee nodes...")
    graph_loader.load_employees(employees)

    # 4d. All employee edges
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
    ]

    for edge_label, from_l, to_l, edges, fk, tk in edge_configs:
        graph_loader.load_edges(edge_label, from_l, to_l, edges, fk, tk)

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

    print()

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


if __name__ == "__main__":
    main()
