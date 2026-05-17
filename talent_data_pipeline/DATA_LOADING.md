# TalentIQ Data Pipeline

## Full Pipeline

Runs all phases end-to-end: connectivity test → schema → data generation → loading → indexing → validation.

```bash
uv run --package talent_data_pipeline python -m talent_data_pipeline.main
```

**Duration:** ~60-90 minutes (130K employees, 1M+ edges, embeddings via Azure OpenAI)

**Phases:**
1. Connectivity test (PostgreSQL + AGE + pgvector)
2. Schema creation (15 node labels, 13 edge labels, relational tables)
3. Data generation (employees, edges, resumes, embeddings)
4. Data loading (graph nodes, edges, vectors, FTS, entity search)
5. Index creation (DiskANN, GIN, B-tree, AGE property indexes)
6. Validation (counts, index verification)

## Incremental Updates

When you only need to add new entities or refresh specific components, run targeted scripts instead of the full pipeline.

### Entity Search Only (FTS + embeddings for resolve_entities tool)

**When:** After adding/modifying reference data (certs, skills, countries, etc.) but graph data already exists.

```bash
uv run --package talent_data_pipeline python -c "
from talent_data_pipeline.schema.create_relational_tables import create_relational_tables
from talent_data_pipeline.schema.create_indexes import run_index_creation
from talent_data_pipeline.loaders.entity_search_loader import EntitySearchLoader

create_relational_tables()
loader = EntitySearchLoader()
loader.load_entity_search()
loader.embed_entities()
loader.close()
run_index_creation()
"
```

**Duration:** ~30 seconds (335 entities)

### Add New Entity Type (e.g., Role)

**When:** A new node label + edge type was added to the data model.

1. Create a script that loads only the new nodes + edges:

```python
from talent_data_pipeline.schema.create_relational_tables import run_schema_creation
from talent_data_pipeline.generators.reference_data import NEW_ENTITIES
from talent_data_pipeline.generators.employee_generator import EmployeeGenerator
from talent_data_pipeline.generators.edge_generator import EdgeGenerator
from talent_data_pipeline.loaders.graph_loader import GraphLoader
from talent_data_pipeline.loaders.entity_search_loader import EntitySearchLoader
from talent_data_pipeline.schema.create_indexes import run_index_creation

# 1. Schema (adds new labels)
run_schema_creation()

# 2. Load new entity nodes
loader = GraphLoader()
loader.load_nodes("NewEntity", NEW_ENTITIES, key_prop="name")

# 3. Generate employees in-memory (not reloading to graph)
emp_gen = EmployeeGenerator()
employees = emp_gen.generate_all()

# 4. Generate + load new edges
edge_gen = EdgeGenerator(employees)
new_edges = edge_gen.generate_new_edges()
loader.load_edges("NEW_EDGE", "Employee", "NewEntity", new_edges, "workday_id", "name")
loader.close()

# 5. Refresh entity search + indexes
entity_loader = EntitySearchLoader()
entity_loader.load_entity_search()
entity_loader.embed_entities()
entity_loader.close()
run_index_creation()
```

**Duration:** ~15-20 minutes (mostly edge loading at ~160 edges/sec for 130K edges)

### Refresh Embeddings Only

**When:** Entity search records exist but embeddings are missing (e.g., Azure OpenAI was down during initial load).

```bash
uv run --package talent_data_pipeline python -c "
from talent_data_pipeline.loaders.entity_search_loader import EntitySearchLoader
loader = EntitySearchLoader()
loader.embed_entities()  # skips entities that already have embeddings
loader.close()
"
```

**Duration:** ~30 seconds (335 entities, batched 16 at a time)

## Architecture

### Data Model (Graph)

```
15 Node Labels: Employee (130K), Location (46), Country (19), Subregion (15),
  Skill (98), SkillDomain (13), Certification (39), Language (18),
  ServiceLine (8), Offering (8), Manager (80), University (74),
  Client (36), Project (22), Role (17)

13 Edge Labels: LOCATED_IN, IN_COUNTRY, SPECIALIZES_IN, HAS_SKILL,
  HOLDS_CERT, SPEAKS, BELONGS_TO_SL, WORKS_IN_OFFERING, HAS_ROLE,
  REPORTS_TO, STUDIED_AT, WORKED_FOR, WORKED_ON
```

### Relational Tables (public schema)

| Table | Purpose | Records |
|-------|---------|---------|
| `employee_embeddings` | Resume + skills vector embeddings (1536-dim) | 130K |
| `employee_fts` | Full-text search on employee name/title/resume/skills/certs | 130K |
| `entity_search` | Unified FTS + vector search for all reference entities | ~350 |

### Reference Entities

All reference entities (Certification, Skill, Country, Role, etc.) have:
- `name` — canonical full name
- `code` — short code for exact matching in Cypher
- `aliases` — common abbreviations/shorthands

These are stored in:
1. **AGE graph nodes** — for Cypher queries (`entity.code = 'PMP'`)
2. **`entity_search` table** — for the `resolve_entities` MCP tool (FTS + vector)

### Loading Performance

| Operation | Speed | 130K records |
|-----------|-------|-------------|
| Employee MERGE | ~160/sec | ~13 min |
| Edge MERGE | ~20-160/sec | ~13-90 min per edge type |
| FTS upsert | ~5000/sec | ~26 sec |
| Vector embedding | ~16/batch | ~7 min (Azure OpenAI) |
| Entity search | ~25/sec | ~15 sec |

Edge loading is the bottleneck — AGE doesn't support batch MERGE, so each edge is a separate SQL round-trip.

## Indexing

Run index creation after any data load:

```bash
uv run --package talent_data_pipeline python -c "
from talent_data_pipeline.schema.create_indexes import run_index_creation
run_index_creation()
"
```

### Index Types

| Type | Engine | Purpose | Tables/Entities |
|------|--------|---------|-----------------|
| **DiskANN** (or HNSW fallback) | pgvector | Vector similarity search | `employee_embeddings.resume_embedding`, `employee_embeddings.skills_embedding` |
| **GIN (tsvector)** | PostgreSQL | Full-text search | `employee_fts.fts_vector`, `entity_search.fts_vector` |
| **GIN (pg_trgm)** | pg_trgm | Fuzzy/trigram search | `employee_fts.name`, `employee_fts.job_title`, `employee_fts.skills_text` |
| **B-tree** | PostgreSQL | Exact lookups | `employee_embeddings.workday_id`, `employee_fts.workday_id`, `entity_search(entity_type, code)`, `entity_search(entity_type, name)` |
| **AGE property** | Apache AGE | Cypher WHERE clause acceleration | All node labels (see below) |

### AGE Graph Property Indexes

Every reference entity has both `name` and `code` indexed for fast Cypher lookups:

| Node Label | Indexed Properties |
|------------|-------------------|
| Employee | `workday_id`, `email`, `is_bench`, `employment_status`, `skill_level`, `job_level`, `delivery_model` |
| Location | `city` |
| Country | `code` |
| Skill | `name`, `code` |
| SkillDomain | `name`, `code` |
| Certification | `name`, `code` |
| Language | `name`, `code` |
| ServiceLine | `name`, `code` |
| Offering | `name`, `code` |
| University | `name`, `code` |
| Client | `name`, `code` |
| Project | `name`, `code` |
| Role | `name`, `code` |
| Manager | `employee_id` |

The `code` indexes are critical for the resolve-first query architecture — `cert.code = 'PMP'` uses the index directly instead of scanning all nodes.

## Configuration

All config from `app_config/.env`:

```
PGHOST=...          # PostgreSQL host
PGPORT=5432         # PostgreSQL port
PGDATABASE=postgres # Database name
PGUSER=...          # Database user
PGPASSWORD=...      # Database password (or use managed identity)
PGSSLMODE=require   # SSL mode
GRAPH_NAME=talent_graph_dev  # AGE graph name
```

## Troubleshooting

### Azure OpenAI token expired during embedding generation
The embedding generator has checkpoint support. Re-run — it skips already-generated embeddings.

### "Entity search table does not exist"
Run the entity search setup:
```bash
uv run --package talent_data_pipeline python -c "
from talent_data_pipeline.schema.create_relational_tables import create_relational_tables
create_relational_tables()
"
```

### Full pipeline crashed mid-load
The graph loader uses MERGE (idempotent) — re-running won't duplicate data. But it will re-process everything from the beginning. Use incremental scripts for just the missing parts.
