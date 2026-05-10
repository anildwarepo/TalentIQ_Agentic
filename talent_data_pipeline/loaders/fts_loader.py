"""Populate tsvector columns and build full-text search data."""

from __future__ import annotations

from typing import Any

from tqdm import tqdm

from talent_data_pipeline.loaders.base_loader import BaseLoader


class FTSLoader(BaseLoader):
    """Populate the employee_fts table with searchable text and tsvector."""

    def load_fts_data(
        self,
        employees: list[dict[str, Any]],
        skill_edges: list[dict[str, Any]],
        cert_edges: list[dict[str, Any]],
    ) -> None:
        """Upsert FTS records for all employees. Idempotent."""
        print(f"Loading {len(employees):,} FTS records...")

        # Build per-employee skill and cert text
        emp_skills: dict[str, list[str]] = {}
        for edge in skill_edges:
            wid = edge["from_key"][1]
            emp_skills.setdefault(wid, []).append(edge["to_key"][1])

        emp_certs: dict[str, list[str]] = {}
        for edge in cert_edges:
            wid = edge["from_key"][1]
            emp_certs.setdefault(wid, []).append(edge["to_key"][1])

        with self.get_conn() as conn:
            cur = conn.cursor()
            for batch in tqdm(list(self.batched(employees)), desc="  FTS"):
                for emp in batch:
                    wid = emp["workday_id"]
                    skills_text = ", ".join(emp_skills.get(wid, []))
                    certs_text = ", ".join(emp_certs.get(wid, []))

                    # Combine all text for tsvector
                    full_text = " ".join(filter(None, [
                        emp["name"],
                        emp["job_title"],
                        emp.get("resume_summary", ""),
                        skills_text,
                        certs_text,
                    ]))

                    self.execute_with_retry(
                        conn,
                        cur,
                        """
                        INSERT INTO employee_fts
                            (workday_id, employee_ageid, name, job_title, resume_summary,
                             skills_text, certs_text, fts_vector, updated_at)
                        VALUES
                            (%s, 0, %s, %s, %s, %s, %s,
                             to_tsvector('english', %s), NOW())
                        ON CONFLICT (workday_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            job_title = EXCLUDED.job_title,
                            resume_summary = EXCLUDED.resume_summary,
                            skills_text = EXCLUDED.skills_text,
                            certs_text = EXCLUDED.certs_text,
                            fts_vector = EXCLUDED.fts_vector,
                            updated_at = NOW();
                        """,
                        (
                            wid, emp["name"], emp["job_title"],
                            emp.get("resume_summary", ""),
                            skills_text, certs_text, full_text,
                        ),
                    )
                conn.commit()

        print("FTS load complete.")
