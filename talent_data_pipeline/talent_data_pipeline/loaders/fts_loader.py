"""Populate tsvector columns and build full-text search data."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from psycopg2.extras import execute_values
from tqdm import tqdm

from talent_data_pipeline.loaders.base_loader import BaseLoader

if TYPE_CHECKING:
    from talent_data_pipeline.checkpoint import LoadCheckpoint


class FTSLoader(BaseLoader):
    """Populate the employee_fts table with searchable text and tsvector."""

    UPSERT_SQL = """
        INSERT INTO employee_fts
            (workday_id, employee_ageid, name, job_title, resume_summary,
             skills_text, certs_text, fts_vector, updated_at)
        VALUES %s
        ON CONFLICT (workday_id) DO UPDATE SET
            name = EXCLUDED.name,
            job_title = EXCLUDED.job_title,
            resume_summary = EXCLUDED.resume_summary,
            skills_text = EXCLUDED.skills_text,
            certs_text = EXCLUDED.certs_text,
            fts_vector = EXCLUDED.fts_vector,
            updated_at = NOW()
    """
    ROW_TEMPLATE = "(%s, 0, %s, %s, %s, %s, %s, to_tsvector('english', %s), NOW())"

    def load_fts_data(
        self,
        employees: list[dict[str, Any]],
        skill_edges: list[dict[str, Any]],
        cert_edges: list[dict[str, Any]],
        checkpoint: LoadCheckpoint | None = None,
        phase_key: str = "fts",
    ) -> None:
        """Upsert FTS records for all employees via batch execute_values.

        One round-trip per batch instead of one per row.
        Supports checkpoint/resume: skips completed batches on restart.
        """
        if checkpoint and checkpoint.is_phase_done(phase_key):
            print(f"  ⏭️  {phase_key} — already loaded (checkpoint), skipping")
            return

        print(f"Loading {len(employees):,} FTS records (batch upsert)...")

        # Build per-employee skill and cert text
        emp_skills: dict[str, list[str]] = {}
        for edge in skill_edges:
            wid = edge["from_key"][1]
            emp_skills.setdefault(wid, []).append(edge["to_key"][1])

        emp_certs: dict[str, list[str]] = {}
        for edge in cert_edges:
            wid = edge["from_key"][1]
            emp_certs.setdefault(wid, []).append(edge["to_key"][1])

        batches = list(self.batched(employees))
        total_batches = len(batches)

        done_indices: set[int] = set()
        if checkpoint:
            done_indices = checkpoint.get_completed_batch_indices(phase_key)
            if done_indices:
                print(f"  (resuming — skipping {len(done_indices)} completed batches)")

        with self.get_conn() as conn:
            cur = conn.cursor()
            for idx, batch in enumerate(tqdm(batches, desc="  FTS")):
                if idx in done_indices:
                    continue

                values = []
                for emp in batch:
                    wid = emp["workday_id"]
                    skills_text = ", ".join(emp_skills.get(wid, []))
                    certs_text = ", ".join(emp_certs.get(wid, []))
                    full_text = " ".join(filter(None, [
                        emp["name"],
                        emp["job_title"],
                        emp.get("resume_summary", ""),
                        skills_text,
                        certs_text,
                    ]))
                    values.append((
                        wid, emp["name"], emp["job_title"],
                        emp.get("resume_summary", ""),
                        skills_text, certs_text, full_text,
                    ))

                execute_values(
                    cur, self.UPSERT_SQL, values,
                    template=self.ROW_TEMPLATE,
                    page_size=len(values),
                )
                conn.commit()
                if checkpoint:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)

            cur.close()

        if checkpoint:
            checkpoint.mark_phase_done(phase_key, len(employees))
        print(f"  ✓ {len(employees):,} FTS records loaded")
