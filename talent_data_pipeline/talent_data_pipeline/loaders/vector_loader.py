"""Load embeddings into the employee_embeddings table with pgvector."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable, TYPE_CHECKING

from psycopg2.extras import execute_values
from tqdm import tqdm

from talent_data_pipeline.loaders.base_loader import BaseLoader

if TYPE_CHECKING:
    from talent_data_pipeline.checkpoint import LoadCheckpoint


class VectorLoader(BaseLoader):
    """Load resume and skills embeddings into the relational vector table."""

    UPSERT_SQL = """
        INSERT INTO employee_embeddings
            (workday_id, employee_ageid, resume_embedding, skills_embedding, updated_at)
        VALUES %s
        ON CONFLICT (workday_id) DO UPDATE SET
            resume_embedding = EXCLUDED.resume_embedding,
            skills_embedding = EXCLUDED.skills_embedding,
            updated_at = NOW()
    """
    ROW_TEMPLATE = "(%s, 0, %s::vector, %s::vector, NOW())"

    @staticmethod
    def _vec_literal(vec: list[float]) -> str:
        """Convert a list of floats to a pgvector literal string."""
        return "[" + ",".join(str(x) for x in vec) + "]"

    def _insert_batch(self, records: list[dict[str, Any]]) -> int:
        """Insert a single batch using its own connection. Returns row count."""
        values = [
            (rec["workday_id"],
             self._vec_literal(rec["resume_embedding"]),
             self._vec_literal(rec["skills_embedding"]))
            for rec in records
        ]
        with self.get_conn() as conn:
            cur = conn.cursor()
            execute_values(
                cur, self.UPSERT_SQL, values,
                template=self.ROW_TEMPLATE,
                page_size=len(values),
            )
            conn.commit()
            cur.close()
        return len(values)

    def load_embeddings_streaming(
        self,
        batch_iter: Iterable[list[dict[str, Any]]],
        total_batches: int,
        checkpoint: LoadCheckpoint | None = None,
        phase_key: str = "embeddings",
        workers: int = 4,
    ) -> None:
        """Stream embedding batches from generator → parallel DB insert.

        Each batch is read from disk/API one at a time (no full-dataset
        memory load), then inserted into PostgreSQL via a thread pool
        with `workers` parallel connections.
        """
        if checkpoint and checkpoint.is_phase_done(phase_key):
            print(f"  ⏭️  {phase_key} — already loaded (checkpoint), skipping")
            return

        print(f"Loading embeddings (streaming, {workers} parallel workers)...")

        done_indices: set[int] = set()
        if checkpoint:
            done_indices = checkpoint.get_completed_batch_indices(phase_key)
            if done_indices:
                print(f"  (resuming — skipping {len(done_indices)} completed DB batches)")

        total_rows = 0
        pbar = tqdm(total=total_batches, desc="  DB upsert")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}

            for batch_idx, batch_records in enumerate(batch_iter):
                # Skip batches already in the DB
                if batch_idx in done_indices:
                    pbar.update(1)
                    continue

                # Throttle: if we have `workers` in-flight, wait for one
                while len(futures) >= workers:
                    done = next(as_completed(futures))
                    completed_idx = futures.pop(done)
                    rows = done.result()
                    total_rows += rows
                    pbar.update(1)
                    if checkpoint:
                        checkpoint.mark_batch_done(phase_key, completed_idx, total_batches)

                # Submit this batch
                fut = pool.submit(self._insert_batch, batch_records)
                futures[fut] = batch_idx

            # Drain remaining futures
            for fut in as_completed(futures):
                completed_idx = futures[fut]
                rows = fut.result()
                total_rows += rows
                pbar.update(1)
                if checkpoint:
                    checkpoint.mark_batch_done(phase_key, completed_idx, total_batches)

        pbar.close()

        if checkpoint:
            checkpoint.mark_phase_done(phase_key, total_rows)
        print(f"  ✓ {total_rows:,} embeddings loaded")

    # Keep the old interface for backward compat
    def load_embeddings(
        self,
        embeddings: list[dict[str, Any]],
        checkpoint: LoadCheckpoint | None = None,
        phase_key: str = "embeddings",
    ) -> None:
        """Upsert embeddings from a list (legacy interface). Uses streaming internally."""
        batches = list(self.batched(embeddings, size=500))
        self.load_embeddings_streaming(
            iter(batches), len(batches),
            checkpoint=checkpoint, phase_key=phase_key,
        )
