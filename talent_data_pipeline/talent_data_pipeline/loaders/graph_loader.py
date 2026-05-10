"""Load nodes and edges into the Apache AGE graph using Cypher MERGE (idempotent).

Uses parallel workers with connection pooling for throughput.
Supports checkpoint/resume so interrupted loads skip completed batches.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TYPE_CHECKING

from psycopg2.extras import execute_values
from tqdm import tqdm

from talent_data_pipeline.config import db_config, pipeline_config
from talent_data_pipeline.loaders.base_loader import BaseLoader

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
}


def _cypher_escape(value: Any) -> str:
    """Format a value for embedding in a Cypher property map literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
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
            for idx, batch in enumerate(batches):
                if idx in done_indices:
                    continue
                self._load_node_batch(batch, label, key_prop)
                if checkpoint and phase_key:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)
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

        with tqdm(total=items_to_process, desc=f"  {label}", miniters=500) as pbar:
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
                    pbar.update(batch_size)
                    if checkpoint and phase_key:
                        checkpoint.mark_batch_done(phase_key, idx, total_batches)

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
            for idx, batch in enumerate(batches):
                if idx in done_indices:
                    continue
                self._load_edge_batch(batch, edge_label, from_label, to_label, from_key_prop, to_key_prop)
                if checkpoint and phase_key:
                    checkpoint.mark_batch_done(phase_key, idx, total_batches)
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

        with tqdm(total=items_to_process, desc=f"  {edge_label}", miniters=1000) as pbar:
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
                    pbar.update(batch_size)
                    if checkpoint and phase_key:
                        checkpoint.mark_batch_done(phase_key, idx, total_batches)

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

    def _build_node_lookup(self, label: str, key_prop: str) -> dict[str, int]:
        """Query all nodes of a label and return {key_property_value → AGE id}."""
        graph = self.graph
        lookup: dict[str, int] = {}
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f'SELECT id, properties FROM {graph}."{label}"')
            for raw_id, raw_props in cur:
                node_id = (
                    int(raw_id)
                    if isinstance(raw_id, (int, float))
                    else int(str(raw_id).strip())
                )
                try:
                    props = (
                        json.loads(raw_props)
                        if isinstance(raw_props, str)
                        else raw_props
                    )
                except (json.JSONDecodeError, TypeError):
                    continue
                key_val = props.get(key_prop) if isinstance(props, dict) else None
                if key_val is not None:
                    lookup[str(key_val)] = node_id
            cur.close()
        return lookup

    def build_all_lookups(self) -> dict[str, dict[str, int]]:
        """Build {label → {key_value → AGE id}} lookups for all node labels."""
        lookups: dict[str, dict[str, int]] = {}
        for label, key_prop in NODE_KEY_PROPS.items():
            lookups[label] = self._build_node_lookup(label, key_prop)
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
        from_lookup: dict[str, int],
        to_lookup: dict[str, int],
        checkpoint: LoadCheckpoint | None = None,
        phase_key: str = "",
    ) -> None:
        """Load edges via direct SQL INSERT into AGE's internal edge table.

        Uses batch execute_values() for 10-100x speedup over Cypher MERGE.
        Deletes existing edges first for idempotent fresh load unless
        --no-truncate is passed.
        """
        if checkpoint and phase_key and checkpoint.is_phase_done(phase_key):
            print(f"  ⏭️  {phase_key} — already loaded (checkpoint), skipping")
            return

        if not edges:
            print(f"  No {edge_label} edges to load")
            return

        no_truncate = "--no-truncate" in sys.argv
        graph = self.graph
        label_id = self._get_edge_label_id(edge_label)

        print(f"Loading {len(edges):,} {edge_label} edges (direct SQL)...")

        # 1. Build values list — resolve start/end IDs from lookups
        values: list[tuple[int, int, str]] = []
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

        # 2. Execute direct SQL INSERT
        seq_name = f'{graph}."{edge_label}_id_seq"'
        template = (
            f"(({label_id}::bigint << 48 | nextval('{seq_name}'))::agtype, "
            f"%s::agtype, %s::agtype, %s::agtype)"
        )
        insert_sql = (
            f'INSERT INTO {graph}."{edge_label}" '
            f"(id, start_id, end_id, properties) VALUES %s"
        )

        with self.get_conn() as conn:
            cur = conn.cursor()

            # Delete existing edges (unless --no-truncate)
            if no_truncate:
                print(f"  ⚠️  --no-truncate: keeping existing {edge_label} edges")
            else:
                cur.execute(f'DELETE FROM {graph}."{edge_label}"')
                deleted = cur.rowcount
                conn.commit()
                if deleted:
                    print(f"  Cleared {deleted:,} existing {edge_label} edges")

            # Batch INSERT in chunks for progress reporting
            chunk_size = 50_000
            total_inserted = 0
            for i in range(0, len(values), chunk_size):
                chunk = values[i : i + chunk_size]
                execute_values(
                    cur, insert_sql, chunk, template=template, page_size=5000
                )
                conn.commit()
                total_inserted += len(chunk)
                if len(values) > chunk_size:
                    print(
                        f"    {edge_label}: {total_inserted:,} / {len(values):,}",
                        end="\r",
                    )

            cur.close()

        print(f"  ✓ {edge_label}: {total_inserted:,} edges inserted" + " " * 30)

        if checkpoint and phase_key:
            checkpoint.mark_phase_done(phase_key, total_inserted)
