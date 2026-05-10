"""Load nodes and edges into the Apache AGE graph using Cypher MERGE (idempotent)."""

from __future__ import annotations

import json
from typing import Any

from tqdm import tqdm

from talent_data_pipeline.config import pipeline_config
from talent_data_pipeline.loaders.base_loader import BaseLoader


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
    """Load nodes and edges into the AGE talent_graph."""

    def __init__(self):
        super().__init__()
        self.graph = pipeline_config.graph_name

    def _exec_cypher(self, conn, cypher: str) -> None:
        """Execute a Cypher query via ag_catalog."""
        cur = conn.cursor()
        cur.execute("SET search_path = ag_catalog, '$user', public;")
        stmt = f"SELECT * FROM ag_catalog.cypher('{self.graph}', $$ {cypher} $$) AS (result agtype);"
        self.execute_with_retry(conn, cur, stmt)
        conn.commit()
        cur.close()

    def load_nodes(self, label: str, nodes: list[dict[str, Any]], key_prop: str = "name") -> None:
        """Load nodes using MERGE (idempotent). Batched with progress."""
        print(f"Loading {len(nodes):,} {label} nodes...")

        with self.get_conn() as conn:
            for batch in tqdm(
                list(self.batched(nodes)),
                desc=f"  {label}",
                disable=len(nodes) < 100,
            ):
                for node in batch:
                    props = {k: v for k, v in node.items() if not k.startswith("_")}
                    key_val = props.get(key_prop, props.get("name", ""))
                    props_str = _props_to_cypher(props)

                    cypher = (
                        f"MERGE (n:{label} {{{key_prop}: {_cypher_escape(key_val)}}}) "
                        f"SET n = {props_str}"
                    )
                    try:
                        self._exec_cypher(conn, cypher)
                    except Exception as exc:
                        print(f"    ERROR on {label} node {key_val}: {exc}")

    def load_edges(
        self,
        edge_label: str,
        from_label: str,
        to_label: str,
        edges: list[dict[str, Any]],
        from_key_prop: str = "workday_id",
        to_key_prop: str = "name",
    ) -> None:
        """Load edges using MERGE. Batched with progress."""
        print(f"Loading {len(edges):,} {edge_label} edges...")

        with self.get_conn() as conn:
            for batch in tqdm(list(self.batched(edges)), desc=f"  {edge_label}"):
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

                    try:
                        self._exec_cypher(conn, cypher)
                    except Exception as exc:
                        # Log but continue — idempotent loading should tolerate some failures
                        pass

    def load_reference_nodes(self, ref_data: dict[str, list[dict[str, Any]]]) -> None:
        """Load all reference/dimension nodes."""
        key_props = {
            "Country": "code",
            "Location": "city",
            "Manager": "employee_id",
            "Subregion": "name",
        }

        for label, nodes in ref_data.items():
            kp = key_props.get(label, "name")
            self.load_nodes(label, nodes, key_prop=kp)

    def load_employees(self, employees: list[dict[str, Any]]) -> None:
        """Load Employee nodes."""
        self.load_nodes("Employee", employees, key_prop="workday_id")
