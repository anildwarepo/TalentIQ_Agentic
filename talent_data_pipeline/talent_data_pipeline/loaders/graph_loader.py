"""Load nodes and edges into the Apache AGE graph using Cypher MERGE (idempotent).

Uses parallel workers with connection pooling for throughput.
Supports checkpoint/resume so interrupted loads skip completed batches.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TYPE_CHECKING

from psycopg2.extras import execute_values

from talent_data_pipeline.config import db_config, pipeline_config
from talent_data_pipeline.loaders.base_loader import BaseLoader


class _ProgressReporter:
    """Plain-text periodic progress reporter (TTY-independent).

    Designed for environments where stdout is captured (azd hooks, CI logs)
    and tqdm's carriage-return updates either disappear or get buffered into
    one-per-completion lines. Prints a short line every ~min_interval seconds
    OR every step_pct% items, whichever comes first.
    """

    def __init__(
        self,
        label: str,
        total: int,
        step_pct: float = 5.0,
        min_interval_sec: float = 15.0,
    ) -> None:
        self.label = label
        self.total = max(1, total)
        self.done = 0
        self.step = max(1, int(self.total * step_pct / 100))
        self.next_threshold = self.step
        self.min_interval = min_interval_sec
        self.start = time.time()
        self.last_print = self.start
        self._lock = threading.Lock()
        print(f"  [{label}] 0 / {self.total:,} (0%) — starting", flush=True)

    def update(self, n: int) -> None:
        with self._lock:
            self.done += n
            now = time.time()
            hit_step = self.done >= self.next_threshold
            hit_time = (now - self.last_print) >= self.min_interval
            if not (hit_step or hit_time or self.done >= self.total):
                return
            elapsed = now - self.start
            pct = self.done * 100.0 / self.total
            rate = self.done / max(0.001, elapsed)
            remaining = max(0, self.total - self.done)
            eta_sec = remaining / max(0.001, rate)
            print(
                f"  [{self.label}] {self.done:,} / {self.total:,} "
                f"({pct:5.1f}%) — elapsed {elapsed/60:5.1f}m, "
                f"rate {rate:.0f}/s, ETA {eta_sec/60:5.1f}m",
                flush=True,
            )
            self.last_print = now
            while self.next_threshold <= self.done:
                self.next_threshold += self.step

    def finish(self) -> None:
        with self._lock:
            elapsed = time.time() - self.start
            rate = self.done / max(0.001, elapsed)
            print(
                f"  [{self.label}] done: {self.done:,} / {self.total:,} "
                f"in {elapsed/60:.1f}m ({rate:.0f}/s)",
                flush=True,
            )

if TYPE_CHECKING:
    from talent_data_pipeline.checkpoint import LoadCheckpoint

# Number of parallel workers — defaults to pool_max or LOAD_WORKERS env var
LOAD_WORKERS = int(os.getenv("LOAD_WORKERS", str(db_config.pool_max)))

# Key property for each node label — used to build {key → AGE id} lookups
NODE_KEY_PROPS: dict[str, str] = {
    "Employee": "workday_id",
    "Location": "city",
    "Country": "code",
    "Subregion": "name",
    "Skill": "name",
    "SkillDomain": "name",
    "Certification": "name",
    "Language": "name",
    "ServiceLine": "name",
    "Offering": "name",
    "Manager": "employee_id",
    "University": "name",
    "Client": "name",
    "Project": "name",
    "Role": "name",
}


def _cypher_escape(value: Any) -> str:
    """Format a value for embedding in a Cypher property map literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_cypher_escape(v) for v in value) + "]"
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _props_to_cypher(props: dict[str, Any]) -> str:
    """Convert a dict to a Cypher property map literal {key: val, ...}."""
    parts = []
    for k, v in props.items():
        if k.startswith("_"):
            continue  # skip internal metadata
        parts.append(f"{k}: {_cypher_escape(v)}")
    return "{" + ", ".join(parts) + "}"


class GraphLoader(BaseLoader):
    """Load nodes and edges into the AGE talent_graph using parallel workers."""

    def __init__(self):
        super().__init__()
        self.graph = pipeline_config.graph_name

    def _exec_cypher(self, conn, cypher: str) -> None:
        """Execute a single Cypher query via ag_catalog."""
        cur = conn.cursor()
        cur.execute("SET search_path = ag_catalog, '$user', public;")
        stmt = f"SELECT * FROM ag_catalog.cypher('{self.graph}', $$ {cypher} $$) AS (result agtype);"
        self.execute_with_retry(conn, cur, stmt)
        conn.commit()
        cur.close()

    def _load_node_batch(self, batch: list[dict[str, Any]], label: str, key_prop: str) -> int:
        """Load a batch of nodes using one connection. Returns count loaded."""
        loaded = 0
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SET search_path = ag_catalog, '$user', public;")
            for node in batch:
                props = {k: v for k, v in node.items() if not k.startswith("_")}
                key_val = props.get(key_prop, props.get("name", ""))
                props_str = _props_to_cypher(props)
                cypher = (
                    f"MERGE (n:{label} {{{key_prop}: {_cypher_escape(key_val)}}}) "
                    f"SET n = {props_str}"
                )
                stmt = f"SELECT * FROM ag_catalog.cypher('{self.graph}', $$ {cypher} $$) AS (result agtype);"
                try:
                    self.execute_with_retry(conn, cur, stmt)
                    loaded += 1
                except Exception as exc:
                    conn.rollback()
            conn.commit()
            cur.close()
        return loaded

    def _load_edge_batch(
        self,
        batch: list[dict[str, Any]],
        edge_label: str,
        from_label: str,
        to_label: str,
        from_key_prop: str,
        to_key_prop: str,
    ) -> int:
        """Load a batch of edges using one connection. Returns count loaded."""
        loaded = 0
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SET search_path = ag_catalog, '$user', public;")
            for edge in batch:
                fk = edge.get("from_key", (from_key_prop, ""))
                tk = edge.get("to_key", (to_key_prop, ""))
                from_kp, from_kv = fk if isinstance(fk, tuple) else (from_key_prop, fk)
                to_kp, to_kv = tk if isinstance(tk, tuple) else (to_key_prop, tk)

                props = edge.get("props", {})
                if props:
                    props_str = " " + _props_to_cypher(props)
                    cypher = (
                        f"MATCH (a:{from_label} {{{from_kp}: {_cypher_escape(from_kv)}}}), "
                        f"(b:{to_label} {{{to_kp}: {_cypher_escape(to_kv)}}}) "
                        f"MERGE (a)-[r:{edge_label}]->(b) "
                        f"SET r = {props_str.strip()}"
                    )
                else:
                    cypher = (
                        f"MATCH (a:{from_label} {{{from_kp}: {_cypher_escape(from_kv)}}}), "
                        f"(b:{to_label} {{{to_kp}: {_cypher_escape(to_kv)}}}) "
                        f"MERGE (a)-[r:{edge_label}]->(b)"
                    )

                stmt = f"SELECT * FROM ag_catalog.cypher('{self.graph}', $$ {cypher} $$) AS (result agtype);"
                try:
                    self.execute_with_retry(conn, cur, stmt)
                    loaded += 1
                except Exception:
                    conn.rollback()
            conn.commit()
            cur.close()
        return loaded

    def load_nodes(
        self,
        label: str,
        nodes: list[dict[str, Any]],
        key_prop: str = "name",
        checkpoint: LoadCheckpoint | None = None,
        phase_key: str = "",
    ) -> None:
        """Load nodes using parallel workers. Each worker processes a batch with its own connection.

        If *checkpoint* is provided and the phase is already complete, skips entirely.
        If partially complete, skips finished batches and resumes.
        """
        if checkpoint and phase_key and checkpoint.is_phase_done(phase_key):
            print(f"  ⏭️  {phase_key} — already loaded (checkpoint), skipping")
            return

        print(f"Loading {len(nodes):,} {label} nodes ({LOAD_WORKERS} workers)...")

        batches = list(self.batched(nodes))
        if not batches:
            return

        # Determine which batches to skip
        done_indices: set[int] = set()
        if checkpoint and phase_key:
            done_indices = checkpoint.get_completed_batch_indices(phase_key)

        total_batches = len(batches)

        # Small sets — load sequentially
        if len(nodes) < 200:
            reporter = _ProgressReporter(label, len(nodes), step_pct=25.0, min_interval_sec=5.0)
            for idx, batch in enumerate(batches):
                if idx in done_indices:
                    reporter.update(len(batch))
                    continue
                count = self._load_node_batch(batch, label, key_prop)
                reporter.update(len(batch))
                if checkpoint and phase_key:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)
            reporter.finish()
            if checkpoint and phase_key:
                checkpoint.mark_phase_done(phase_key, len(nodes))
            return

        # Parallel load
        total_loaded = 0
        items_to_process = sum(
            len(b) for i, b in enumerate(batches) if i not in done_indices
        )
        skipped = len(done_indices)
        if skipped:
            print(f"  (resuming — skipping {skipped} completed batches)")

        reporter = _ProgressReporter(label, items_to_process)
        with ThreadPoolExecutor(max_workers=LOAD_WORKERS) as executor:
            futures = {}
            for idx, batch in enumerate(batches):
                if idx in done_indices:
                    continue
                fut = executor.submit(self._load_node_batch, batch, label, key_prop)
                futures[fut] = (idx, len(batch))

            for future in as_completed(futures):
                idx, batch_size = futures[future]
                count = future.result()
                total_loaded += count
                reporter.update(batch_size)
                if checkpoint and phase_key:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)
        reporter.finish()

        if checkpoint and phase_key:
            checkpoint.mark_phase_done(phase_key, len(nodes))
        print(f"  Loaded {total_loaded:,} / {len(nodes):,} {label} nodes")

    def load_edges(
        self,
        edge_label: str,
        from_label: str,
        to_label: str,
        edges: list[dict[str, Any]],
        from_key_prop: str = "workday_id",
        to_key_prop: str = "name",
        checkpoint: LoadCheckpoint | None = None,
        phase_key: str = "",
    ) -> None:
        """Load edges using parallel workers with optional checkpoint/resume."""
        if checkpoint and phase_key and checkpoint.is_phase_done(phase_key):
            print(f"  ⏭️  {phase_key} — already loaded (checkpoint), skipping")
            return

        print(f"Loading {len(edges):,} {edge_label} edges ({LOAD_WORKERS} workers)...")

        batches = list(self.batched(edges))
        if not batches:
            return

        done_indices: set[int] = set()
        if checkpoint and phase_key:
            done_indices = checkpoint.get_completed_batch_indices(phase_key)

        total_batches = len(batches)

        # Small sets — load sequentially
        if len(edges) < 200:
            reporter = _ProgressReporter(edge_label, len(edges), step_pct=25.0, min_interval_sec=5.0)
            for idx, batch in enumerate(batches):
                if idx in done_indices:
                    reporter.update(len(batch))
                    continue
                self._load_edge_batch(batch, edge_label, from_label, to_label, from_key_prop, to_key_prop)
                reporter.update(len(batch))
                if checkpoint and phase_key:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)
            reporter.finish()
            if checkpoint and phase_key:
                checkpoint.mark_phase_done(phase_key, len(edges))
            return

        # Parallel load
        total_loaded = 0
        items_to_process = sum(
            len(b) for i, b in enumerate(batches) if i not in done_indices
        )
        skipped = len(done_indices)
        if skipped:
            print(f"  (resuming — skipping {skipped} completed batches)")

        reporter = _ProgressReporter(edge_label, items_to_process)
        with ThreadPoolExecutor(max_workers=LOAD_WORKERS) as executor:
            futures = {}
            for idx, batch in enumerate(batches):
                if idx in done_indices:
                    continue
                fut = executor.submit(
                    self._load_edge_batch, batch, edge_label,
                    from_label, to_label, from_key_prop, to_key_prop,
                )
                futures[fut] = (idx, len(batch))

            for future in as_completed(futures):
                idx, batch_size = futures[future]
                count = future.result()
                total_loaded += count
                reporter.update(batch_size)
                if checkpoint and phase_key:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)
        reporter.finish()

        if checkpoint and phase_key:
            checkpoint.mark_phase_done(phase_key, len(edges))
        print(f"  Loaded {total_loaded:,} / {len(edges):,} {edge_label} edges")

    def load_reference_nodes(
        self,
        ref_data: dict[str, list[dict[str, Any]]],
        checkpoint: LoadCheckpoint | None = None,
    ) -> None:
        """Load all reference/dimension nodes."""
        key_props = {
            "Country": "code",
            "Location": "city",
            "Manager": "employee_id",
            "Subregion": "name",
        }

        for label, nodes in ref_data.items():
            kp = key_props.get(label, "name")
            phase_key = f"nodes:{label}"
            self.load_nodes(label, nodes, key_prop=kp, checkpoint=checkpoint, phase_key=phase_key)

    def load_employees(
        self,
        employees: list[dict[str, Any]],
        checkpoint: LoadCheckpoint | None = None,
    ) -> None:
        """Load Employee nodes."""
        self.load_nodes(
            "Employee", employees, key_prop="workday_id",
            checkpoint=checkpoint, phase_key="nodes:Employee",
        )

    # ── Direct SQL Batch INSERT Methods ───────────────────────────
    #
    # Bypass Cypher MERGE entirely: INSERT straight into the AGE label tables
    # created by Phase 2 (create_vlabel / create_elabel). ~50–100× faster than
    # per-row MERGE because there is no parse/plan/match round-trip per row.
    # The trade-off is non-idempotency: we DELETE the label table first
    # (controlled by --no-truncate). AGE generates `id` via DEFAULT.

    def truncate_label(self, label: str) -> int:
        """DELETE all rows from an AGE label table. Returns count deleted."""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f'DELETE FROM {self.graph}."{label}"')
            deleted = cur.rowcount
            conn.commit()
            cur.close()
        return deleted

    def _load_nodes_direct_batch(
        self, batch: list[dict[str, Any]], label: str
    ) -> int:
        """Direct SQL INSERT batch — AGE generates `id` via DEFAULT.

        Internal keys (prefix `_`) are dropped before serialization.
        """
        if not batch:
            return 0
        values: list[tuple[str]] = []
        for node in batch:
            props = {k: v for k, v in node.items() if not k.startswith("_")}
            values.append((json.dumps(props),))
        with self.get_conn() as conn:
            cur = conn.cursor()
            execute_values(
                cur,
                f'INSERT INTO {self.graph}."{label}" (properties) VALUES %s',
                values,
                template="(%s::ag_catalog.agtype)",
                page_size=5000,
            )
            conn.commit()
            cur.close()
        return len(batch)

    def load_nodes_direct(
        self,
        label: str,
        nodes: list[dict[str, Any]],
        key_prop: str = "name",
        checkpoint: LoadCheckpoint | None = None,
        phase_key: str = "",
    ) -> None:
        """Load nodes via direct SQL INSERT (no Cypher MERGE).

        Truncates the label table first unless --no-truncate. Parallel for
        large sets, sequential for small. Uses _ProgressReporter for visible
        progress under captured stdout (azd hook).
        """
        if checkpoint and phase_key and checkpoint.is_phase_done(phase_key):
            print(f"  ⏭️  {phase_key} — already loaded (checkpoint), skipping")
            return

        if not nodes:
            return

        no_truncate = "--no-truncate" in sys.argv
        if no_truncate:
            print(f"  ⚠️  --no-truncate: keeping existing {label} nodes")
        else:
            deleted = self.truncate_label(label)
            if deleted:
                print(f"  Cleared {deleted:,} existing {label} nodes")

        print(
            f"Loading {len(nodes):,} {label} nodes via direct SQL "
            f"({LOAD_WORKERS} workers)..."
        )

        batches = list(self.batched(nodes))
        if not batches:
            return
        total_batches = len(batches)

        # Small → sequential
        if len(nodes) < 1000:
            reporter = _ProgressReporter(
                label, len(nodes), step_pct=25.0, min_interval_sec=5.0
            )
            for idx, batch in enumerate(batches):
                self._load_nodes_direct_batch(batch, label)
                reporter.update(len(batch))
                if checkpoint and phase_key:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)
            reporter.finish()
            if checkpoint and phase_key:
                checkpoint.mark_phase_done(phase_key, len(nodes))
            return

        # Parallel
        reporter = _ProgressReporter(label, len(nodes))
        with ThreadPoolExecutor(max_workers=LOAD_WORKERS) as executor:
            futures: dict[Any, tuple[int, int]] = {}
            for idx, batch in enumerate(batches):
                fut = executor.submit(self._load_nodes_direct_batch, batch, label)
                futures[fut] = (idx, len(batch))
            for fut in as_completed(futures):
                idx, sz = futures[fut]
                try:
                    fut.result()
                except Exception as exc:
                    print(f"  batch {idx} FAILED: {exc}")
                    continue
                reporter.update(sz)
                if checkpoint and phase_key:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)
        reporter.finish()

        if checkpoint and phase_key:
            checkpoint.mark_phase_done(phase_key, len(nodes))

    def load_employees_direct(
        self,
        employees: list[dict[str, Any]],
        checkpoint: LoadCheckpoint | None = None,
    ) -> None:
        """Load Employee nodes via direct SQL INSERT (fast path)."""
        self.load_nodes_direct(
            "Employee", employees, key_prop="workday_id",
            checkpoint=checkpoint, phase_key="nodes:Employee",
        )

    def load_reference_nodes_direct(
        self,
        ref_data: dict[str, list[dict[str, Any]]],
        checkpoint: LoadCheckpoint | None = None,
    ) -> None:
        """Load reference/dimension nodes via direct SQL INSERT."""
        key_props = {
            "Country": "code",
            "Location": "city",
            "Manager": "employee_id",
            "Subregion": "name",
        }
        for label, nodes in ref_data.items():
            kp = key_props.get(label, "name")
            phase_key = f"nodes:{label}"
            self.load_nodes_direct(
                label, nodes, key_prop=kp,
                checkpoint=checkpoint, phase_key=phase_key,
            )

    def _build_node_lookup(self, label: str, key_prop: str) -> dict[str, str]:
        """Return {key_property_value → graphid-as-text} for a label.

        Uses SQL-side extraction with the agtype→text→jsonb double cast that
        AGE 1.6.0 requires (the bare `->>` operator does not exist on agtype).
        graphid is returned as text so it can be cast back via ::graphid in
        edge INSERT statements.
        """
        graph = self.graph
        lookup: dict[str, str] = {}
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f'SELECT id::text, ((properties::text)::jsonb)->>%s '
                f'FROM {graph}."{label}"',
                (key_prop,),
            )
            for raw_id, key_val in cur:
                if key_val is not None:
                    lookup[str(key_val)] = str(raw_id)
            cur.close()
        return lookup

    def build_all_lookups(self) -> dict[str, dict[str, str]]:
        """Build {label → {key_value → graphid-as-text}} for all labels."""
        lookups: dict[str, dict[str, str]] = {}
        for label, key_prop in NODE_KEY_PROPS.items():
            t0 = time.time()
            lookups[label] = self._build_node_lookup(label, key_prop)
            print(
                f"  Lookup {label:15s} → {len(lookups[label]):>8,} entries "
                f"in {time.time()-t0:.1f}s",
                flush=True,
            )
        return lookups

    def _get_edge_label_id(self, edge_label: str) -> int:
        """Get the AGE internal label_id for an edge label from ag_catalog."""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT l.id FROM ag_catalog.ag_label l "
                "JOIN ag_catalog.ag_graph g ON l.graph = g.graphid "
                "WHERE g.name = %s AND l.name = %s",
                (self.graph, edge_label),
            )
            row = cur.fetchone()
            cur.close()
            if not row:
                raise ValueError(
                    f"Edge label '{edge_label}' not found in graph '{self.graph}'"
                )
            return int(row[0])

    def load_edges_direct(
        self,
        edge_label: str,
        from_label: str,
        to_label: str,
        edges: list[dict[str, Any]],
        from_lookup: dict[str, str],
        to_lookup: dict[str, str],
        checkpoint: LoadCheckpoint | None = None,
        phase_key: str = "",
    ) -> None:
        """Load edges via direct SQL INSERT into AGE's internal edge table.

        Uses execute_values() in chunks of 50k for 10–100× speedup over
        Cypher MERGE. AGE generates `id` via DEFAULT — we only provide
        (start_id, end_id, properties). Truncates the label first unless
        --no-truncate is passed.

        Lookups map key-value → graphid-as-text (built via
        :meth:`build_all_lookups`); we cast back via ::ag_catalog.graphid
        on the SQL side.
        """
        if checkpoint and phase_key and checkpoint.is_phase_done(phase_key):
            print(f"  ⏭️  {phase_key} — already loaded (checkpoint), skipping")
            return

        if not edges:
            print(f"  No {edge_label} edges to load")
            return

        no_truncate = "--no-truncate" in sys.argv
        graph = self.graph

        print(f"Loading {len(edges):,} {edge_label} edges (direct SQL)...")

        # Resolve start/end IDs from lookups
        values: list[tuple[str, str, str]] = []
        skipped = 0
        for edge in edges:
            fk = edge.get("from_key", ("", ""))
            tk = edge.get("to_key", ("", ""))
            from_val = fk[1] if isinstance(fk, (tuple, list)) else fk
            to_val = tk[1] if isinstance(tk, (tuple, list)) else tk

            start_id = from_lookup.get(str(from_val))
            end_id = to_lookup.get(str(to_val))

            if start_id is None or end_id is None:
                skipped += 1
                continue

            props = edge.get("props", {})
            props_json = json.dumps(props) if props else "{}"
            values.append((start_id, end_id, props_json))

        if skipped:
            print(f"  ⚠️  Skipped {skipped:,} edges (unresolved node IDs)")

        if not values:
            print(f"  No resolvable {edge_label} edges — nothing to insert")
            if checkpoint and phase_key:
                checkpoint.mark_phase_done(phase_key, 0)
            return

        # Truncate first (unless --no-truncate)
        if no_truncate:
            print(f"  ⚠️  --no-truncate: keeping existing {edge_label} edges")
        else:
            deleted = self.truncate_label(edge_label)
            if deleted:
                print(f"  Cleared {deleted:,} existing {edge_label} edges")

        # Batch INSERT — let AGE generate id via DEFAULT
        insert_sql = (
            f'INSERT INTO {graph}."{edge_label}" '
            f"(start_id, end_id, properties) VALUES %s"
        )
        template = (
            "(%s::ag_catalog.graphid, %s::ag_catalog.graphid, "
            "%s::ag_catalog.agtype)"
        )

        chunk_size = 50_000
        total_inserted = 0
        reporter = _ProgressReporter(edge_label, len(values))
        with self.get_conn() as conn:
            cur = conn.cursor()
            for i in range(0, len(values), chunk_size):
                chunk = values[i : i + chunk_size]
                execute_values(
                    cur, insert_sql, chunk, template=template, page_size=5000
                )
                conn.commit()
                total_inserted += len(chunk)
                reporter.update(len(chunk))
            cur.close()
        reporter.finish()

        if checkpoint and phase_key:
            checkpoint.mark_phase_done(phase_key, total_inserted)
