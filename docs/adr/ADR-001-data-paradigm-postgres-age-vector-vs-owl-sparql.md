# ADR-001: Data Query Paradigm — PostgreSQL + Apache AGE (Cypher) + pgvector vs. OWL/SPARQL

> **Status:** Accepted
> **Date:** 2026-05-19
> **Deciders:** Architecture team
> **Consulted:** Data engineering (Parker), Backend (MCP/Agent), Product (Ash)
> **Scope:** TalentIQ v2 — data layer paradigm for the talent matching and search platform
> **Supersedes:** —
> **Superseded by:** —

---

## 1. Context

TalentIQ v2 is an agent-first internal talent matching and management platform for DXC Technology. The data layer must support 52 user stories spanning candidate search, CV generation, certifications, dashboards, RFI/tender intake, and pre-sales workflows (see [docs/specs/product-spec.md](../specs/product-spec.md)).

During design review, a question was raised: should the data layer be built on a **Semantic Web stack (OWL + SPARQL + RDF triple store)** instead of, or in addition to, the current **PostgreSQL + Apache AGE (Cypher) + pgvector + tsvector** stack documented in [docs/specs/database-architecture.md](../specs/database-architecture.md)?

This ADR captures the analysis and the decision.

### Current state

- Single Azure Database for PostgreSQL Flexible Server instance
- Apache AGE extension for property graph storage (Cypher)
- pgvector extension (DiskANN / HNSW) for semantic similarity search
- `tsvector` + GIN + `pg_trgm` for full-text and fuzzy keyword search
- 130,000 employee nodes, 14 node labels, 12 edge labels, ~1.87M edges
- MCP server (`FastMCP`, port 3002) exposes `query_using_sql_cypher`, `search_graph`, and `vector_search` tools to the AI agent
- Ontology documentation lives at [talentiq_requirements/talent_ontology/DXC_Talent_Ontology.md](../../talentiq_requirements/talent_ontology/DXC_Talent_Ontology.md) — a Markdown reference that mirrors the AGE schema

### Drivers

- Must support multi-criteria candidate search with skills, certs, languages, location, EQF/MECES, job level (US-009, US-010, US-011, US-013)
- Must support semantic / "developable" partial matches (US-009, US-014)
- Must support free-text CV search (US-015)
- Must support skill-gap analysis and RFI coverage heat maps (US-014, US-023)
- Must support org-hierarchy and team dashboards (US-023–028)
- Must support EQF/MECES mapping (US-006, US-007, US-008)
- Must remain operable by the current team (Python + PostgreSQL skills)

---

## 2. Decision

**Adopt** PostgreSQL + Apache AGE (Cypher) + pgvector + tsvector as the unified data layer for TalentIQ v2.

**Reject** an OWL / SPARQL / RDF triple-store layer (e.g., Apache Jena, Stardog, GraphDB, Blazegraph) — neither as the primary store nor as a parallel layer.

**Defer** any introduction of formal semantic-web tooling unless a future requirement explicitly demands W3C-standard federation, formal class-subsumption reasoning, or external vocabulary publication.

---

## 3. Options Considered

### Option A — PostgreSQL + AGE (Cypher) + pgvector + tsvector  *(Selected)*

A single Postgres instance hosting four query paradigms:

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Graph | PostgreSQL + Apache AGE | Relationship traversal (skills, teams, org hierarchy) |
| Vector | pgvector + DiskANN/HNSW | Semantic similarity (resume/skills) |
| Full-text | tsvector + GIN + pg_trgm | Keyword and fuzzy name search |
| Relational | Standard PostgreSQL tables | Embeddings storage, lookups, joins, audit |

### Option B — OWL / SPARQL on an RDF triple store

A semantic-web stack (Apache Jena Fuseki, Stardog, GraphDB, Blazegraph, or equivalent) hosting the talent ontology as OWL TBox axioms and the employee data as RDF ABox triples. Inference handled by a reasoner (RDFS, OWL-EL, OWL-RL, or OWL-DL).

### Option C — Hybrid (Postgres + AGE + pgvector + RDF/SPARQL side-car)

Keep Option A as the operational store and add an RDF/SPARQL layer for the ontology + inference, synchronized via ETL or CDC.

---

## 4. Comparison

### 4.1 Paradigm fit by query style

| Question / acceptance criterion type | Best paradigm |
|---|---|
| "Rows matching exact criteria, aggregations, joins on known keys" | SQL |
| "Find things semantically similar to this text/embedding" | Vector |
| "Traverse N-hop relationships, pathfinding, community detection" | Graph / Cypher |
| "Reason over a formal domain model with inferred facts and class hierarchies" | OWL / SPARQL |

### 4.2 Head-to-head matrix

| Dimension | SQL | Cypher (AGE) | Vector (pgvector) | SPARQL / OWL |
|---|---|---|---|---|
| Data model | Tables | Property graph | Embeddings | RDF triples + ontology |
| Query style | Set algebra | Pattern matching | Similarity | Pattern matching + inference |
| Schema | Rigid | Flexible | Schemaless | Formal ontology |
| Joins / multi-hop | Fixed depth, expensive | Native, cheap | N/A | Native via property paths |
| Aggregation | Excellent | Good | Poor | Decent |
| Semantic similarity | None | None (add-on) | Native | Via inference, not fuzzy |
| Inference / reasoning | None | None | None | Native (RDFS/OWL) |
| Standards | ISO SQL | GQL emerging | None | W3C |
| Tooling maturity | Highest | Medium | Growing fast | Niche |
| Write throughput | Very high | Medium | High | Lower |
| Explainability | High | High | Low | Highest (provenance) |
| Best query | "Sum sales by region" | "Shortest path A→B" | "Find similar resumes" | "All subclasses of X with property Y" |

---

## 5. User-Story Analysis

Mapping the 52 stories in [docs/user-stories/](../user-stories/) to query patterns:

| Story pattern | Example stories | Paradigm that fits |
|---|---|---|
| Multi-attribute filter (skills + certs + langs + location + level) | US-009, US-010, US-011, US-013 | Cypher (joins on graph) + SQL filter |
| Free-text resume search | US-015 | FTS (tsvector) + vector |
| Semantic skill match / "developable" candidates / partial match | US-009, US-014 | Vector (cosine on skill/role embeddings) |
| Skill-gap analysis ("required vs available"), RFI heat map | US-014, US-023 | Cypher set-difference / aggregation |
| Coverage dashboards by population (Iberia, service line) | US-023, US-024–028 | SQL aggregation over materialized views |
| Org/team traversal (REPORTS_TO) | US-026 + dashboards | Cypher multi-hop |
| EQF/MECES qualification lookup | US-006, US-007, US-008 | SQL lookup table |
| Skill inference from project/role | US-041 | Cypher rules + ML, not OWL inference |
| Tender / RFI text → structured roles | US-032 | LLM extraction, then store as graph nodes |
| Audit / RBAC / query history | US-037, US-038, US-045 | SQL rows |

**Zero stories require** formal class subsumption reasoning, cross-organization vocabulary federation, SHACL validation, or provenance-traceable inferred facts — the things OWL/SPARQL is uniquely good at.

---

## 6. Rationale — Why OWL/SPARQL Was Rejected

1. **The ontology is small, closed, and DXC-internal.** 14 node labels, 12 edge types, ~130k employees, 96 skills, 13 skill domains. This is a property graph, not a knowledge graph requiring W3C standards for federation with external parties.

2. **The "ontology" already exists as a Markdown + AGE schema artifact.** [DXC_Talent_Ontology.md](../../talentiq_requirements/talent_ontology/DXC_Talent_Ontology.md) is a documentation artifact that drives the AGE schema. Restating it as OWL TBox axioms buys nothing the stories ask for.

3. **EQF/MECES is a lookup, not an inference problem.** US-006 explicitly says *"pre-loaded mapping table"* with columns: qualification name, EQF level (1–8), MECES level (1–4), country/framework scope. That is a 4-column SQL table, not an OWL class hierarchy. A reasoner is not needed to derive `MSc ⊑ Postgraduate ⊑ EQF7`.

4. **Skill adjacency / "developable" candidates is fuzzy, not formal.** US-014's "partial match" and US-009's "potential to obtain missing certifications" are semantic-similarity problems (cosine distance between skill embeddings), not OWL `equivalentClass` axioms. A reasoner gives a deterministic yes/no — the platform needs a score.

5. **Heat maps and dashboards are aggregations.** US-023's RFI-vs-bench heat map is `COUNT(*) GROUP BY skill` over a join, not a SPARQL `CONSTRUCT`. Postgres + AGE wins on every dimension here (performance, BI tooling, talent pool).

6. **Operational cost.** Adding a triple store (Jena / Stardog / GraphDB) introduces a second data store, ETL or CDC synchronization, a separate query language for the team, and a reasoner to tune — with no acceptance criteria that justify it.

7. **Sunk investment in AGE.** The MCP server, agent prompts, `PGAgeHelper`, and tests are all built around Cypher and SQL. Switching paradigms is a re-architecture, not an enhancement.

---

## 7. How the Selected Stack Covers Each Story Type

| Need from stories | Already covered by |
|---|---|
| Multi-criteria search (US-009, 010, 013) | Cypher `MATCH ... WHERE` over `HAS_SKILL`, `HOLDS_CERT`, `SPEAKS`, `LOCATED_IN` |
| Semantic skill match (US-009 M05-02, US-015) | pgvector on `resume_summary` and skill embeddings |
| Full-text CV search (US-015) | tsvector + GIN |
| Skill gap / developable (US-014) | Cypher `WHERE NOT EXISTS` + vector similarity for near matches |
| Heat map / coverage (US-023) | Cypher aggregation OR materialized SQL view |
| EQF/MECES mapping (US-006–008) | SQL lookup table + `eqf_level` / `meces_level` properties on `Employee` and `STUDIED_AT` |
| Tender role extraction (US-032) | LLM + vector matching against `Skill` nodes |
| Org traversal (`REPORTS_TO`) | Cypher `MATCH (e)-[:REPORTS_TO*1..5]->(m)` |
| Audit, RBAC, history (US-037, 038, 045) | Plain SQL tables |

---

## 8. When OWL/SPARQL Would Become Attractive (Reconsideration Triggers)

This decision should be revisited if **any** of the following becomes a hard requirement:

1. DXC must **publish a public skills vocabulary** that external vendors, partners, or regulators consume via standard URIs.
2. A regulatory / compliance regime requires **provenance-traceable inferred facts** with formal entailment guarantees (e.g., every derived classification must cite the OWL axiom that produced it).
3. The platform must **federate live queries** across multiple independent triple stores or LOD endpoints (ESCO, schema.org, FIBO-style).
4. A taxonomy grows to the point where **automated class subsumption reasoning** over hundreds of thousands of axioms outperforms manually maintained edges.
5. **SHACL-style constraint validation** of cross-entity invariants becomes a core platform feature.

None of these are present in the current 52 stories or the 48 features in `features.csv`.

---

## 9. Forward-Looking Note — Skill Adjacency (EPIC-12)

EPIC-12 (Skills Enrichment, currently Backlog / Could) is the one area where a *lightweight semantic layer* could pay off: encoding "Django is-a Python framework", "Terraform is-related-to AWS/Azure", "PMP is-equivalent-to PRINCE2 for partial match".

**OWL is not required.** Pragmatic options, ranked:

1. **Add `Skill → Skill` edges in AGE** with types `IS_PART_OF`, `RELATED_TO`, `EQUIVALENT_TO`. Source the data from an existing taxonomy (ESCO, O*NET, Lightcast). Query in Cypher. **(Recommended.)**
2. **Skill embeddings + cosine threshold** for "adjacent" without explicit edges.
3. **Hybrid:** explicit edges for hard equivalences, embeddings for soft similarity.

ESCO is published as RDF/OWL but can be imported into the AGE schema as labels and edges without adopting the SPARQL stack.

---

## 10. Consequences

### Positive

- Single operational data store (Postgres) — one backup, one HA story, one network boundary, one set of credentials, one connection pool.
- Team operates in familiar languages (SQL, Cypher, Python) — no W3C / Description-Logic learning curve.
- Existing investments in `PGAgeHelper`, MCP tools, agent prompts, and tests are preserved.
- pgvector + AGE + tsvector compose cleanly inside a single SQL transaction.
- Standard Postgres tooling (Azure Monitor, pgAdmin, BI connectors, `pg_dump`) works end-to-end.

### Negative / Trade-offs

- No native formal reasoning. Class hierarchies and equivalences must be encoded as explicit edges or computed in application code.
- No W3C-standard interchange format out of the box. If a future partner requires RDF, an export adapter would be needed.
- AGE has known limitations (e.g., `ORDER BY` on aggregations must use `WITH`; see [docs/specs/database-architecture.md](../specs/database-architecture.md) §2.2) that the team must continue to work around.
- The `talent_graph` graph in AGE is not horizontally partitioned. Scale beyond a few million nodes will require sharding or migration to a dedicated graph DB — but this is far beyond current scope (130k employees).

### Neutral

- The ontology documentation in Markdown remains the source of truth for the schema; it does not become "executable" via a reasoner.

---

## 11. References

- [docs/specs/product-spec.md](../specs/product-spec.md) — Product vision, target users, sprint roadmap
- [docs/specs/database-architecture.md](../specs/database-architecture.md) — Current AGE + pgvector + tsvector design
- [docs/specs/mcp-server-tools.md](../specs/mcp-server-tools.md) — MCP tool surface for the AI agent
- [talentiq_requirements/talent_ontology/DXC_Talent_Ontology.md](../../talentiq_requirements/talent_ontology/DXC_Talent_Ontology.md) — Ontology reference
- [docs/user-stories/US-006.md](../user-stories/US-006.md) — EQF/MECES pre-load
- [docs/user-stories/US-009.md](../user-stories/US-009.md) — Multi-criteria search
- [docs/user-stories/US-014.md](../user-stories/US-014.md) — Skill gap / retraining
- [docs/user-stories/US-015.md](../user-stories/US-015.md) — Full-text CV search
- [docs/user-stories/US-023.md](../user-stories/US-023.md) — Dashboard / RFI heat map
- [docs/user-stories/US-032.md](../user-stories/US-032.md) — Tender role extraction
- [docs/user-stories/US-041.md](../user-stories/US-041.md) — Skill inference from role
