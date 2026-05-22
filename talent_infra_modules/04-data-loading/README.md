# 04-data-loading — TalentIQ data pipeline (`talent_data_pipeline`)

## What this script will do

Run the **`talent_data_pipeline` Python pipeline** against the freshly
provisioned PostgreSQL server to load:

- Reference data (countries, locations, skills, certifications)
- ~130,000 synthetic employee nodes + resume summaries
- Skill, certification, location, project, client edges
- Vector embeddings (text-embedding-ada-002)
- FTS + entity-search auxiliary tables
- AGE label indexes and post-load validation indexes

Phases (executed in `talent_data_pipeline/main.py` order):

1. **Prereq verification**: PG exists, Foundry exists with
   `text-embedding-ada-002` deployment, deployer's UPN is a registered
   PG Entra admin (otherwise the pipeline cannot connect with a token).
2. **(Optional) Open hosts-file gap**: when PG is private-endpoint-only,
   look up the PE NIC's private IP and either (a) auto-emit hosts-file
   instructions and wait for the operator to add them, or (b) accept a
   `-HostAddr` argument that the pipeline forwards to `psycopg2.connect`
   as `hostaddr=...` so DNS is bypassed entirely. (See
   `talent_data_pipeline/main.py`'s `pg_connect` and
   `talent_infra_v2/scripts/provision_pg_entra_roles.py --hostaddr`.)
3. **Set extension / preload params** (idempotent — typically already
   applied by `01-postgresql/`). Restart server if anything is
   `isConfigPendingRestart`.
4. **`CREATE EXTENSION ... CASCADE`** for AGE, vector, pg_trgm,
   pg_diskann inside the `postgres` database (deployer connects with
   their Entra token).
5. **Run `provision_pg_entra_roles.py`** to grant the backend UAMI
   (and any other UAMIs in `02-backend/.outputs.json`) narrow
   per-schema privileges via `pgaadauth_create_principal_with_oid`.
   This **supersedes** the broad PG-admin privilege the UAMI received
   from the control-plane registration in `01-postgresql/` — once SQL
   role provisioning succeeds, the UAMI is downgraded to least-privilege.
6. **Run `python -m talent_data_pipeline.main`** with `--force` or
   without (the pipeline skips Phase 3/4 if data is already loaded:
   employees >= 90% of `EMPLOYEE_COUNT` and `employee_embeddings` >= 90%).
7. **Final validation** (the pipeline's Phase 6).
8. **(Optional) Restart backend revision** so the backend's psycopg2
   pool picks up the now-narrowed UAMI grants.

## What this script will NOT do

- Spin up any Azure resources — PG, Foundry, and (if used) ACA backend
  must all exist.
- Generate or push container images.
- Drop and recreate the database. The pipeline mutates the existing
  `postgres` database in place; use a fresh server to start over.
- Use ACR Tasks. This is a **local** Python invocation, not a
  containerized job. To run it as an ACA Job, build a small wrapper
  image and follow the `talent_infra_v2/hooks/postprovision.ps1`
  pattern.

## Inputs (parameters)

| Name                          | Env var                              | Default                              | Notes |
|-------------------------------|--------------------------------------|--------------------------------------|-------|
| SubscriptionId                | `AZURE_SUBSCRIPTION_ID`              | —                                    | |
| ResourceGroup                 | `AZURE_RESOURCE_GROUP`               | —                                    | |
| PostgresqlOutputsFile         | `POSTGRESQL_OUTPUTS_FILE`            | `../01-postgresql/.outputs.json`     | |
| BackendOutputsFile            | `BACKEND_OUTPUTS_FILE`               | `../02-backend/.outputs.json` (opt.) | When supplied, narrow grants are applied to that UAMI. |
| DataPipelinePath              | `DATA_PIPELINE_PATH`                 | `../../talent_data_pipeline`         | |
| GraphName                     | `GRAPH_NAME`                         | from PG outputs (default `talent_graph`) | |
| EmployeeCount                 | `EMPLOYEE_COUNT`                     | `130000`                             | |
| BatchSize                     | `BATCH_SIZE`                         | `1000`                               | |
| RandomSeed                    | `RANDOM_SEED`                        | `42`                                 | |
| FoundryAccountName            | `FOUNDRY_ACCOUNT_NAME`               | —                                    | For embedding endpoint. |
| FoundryEmbeddingDeployment    | `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`  | `text-embedding-ada-002`             | |
| EmbeddingDim                  | `AZURE_OPENAI_EMBEDDING_DIMENSIONS`  | `1536`                               | |
| HostAddr                      | `PGHOSTADDR`                         | empty                                | Forward to psycopg2 `hostaddr` to bypass DNS. |
| Force                         | (switch only)                        | off                                  | Pass `--force` to the pipeline (regenerate from scratch). |
| RestartBackend                | (switch only)                        | off                                  | Restart backend revision after narrowing UAMI grants. |

## Outputs

```json
{
  "graphName":         "talent_graph_66lb",
  "employeesLoaded":   130000,
  "embeddingsLoaded":  130000,
  "elapsedMinutes":    42.3
}
```

These are diagnostic only — no later step consumes them.

## Deployment lessons encoded

- **Deployer must be an Entra admin first**: `provision_pg_entra_roles.py`
  refuses to start without a working Entra token connection. The
  `01-postgresql/` script registers the deployer's UPN as a User Entra
  admin precisely so this step works.
- **Private endpoint connectivity gap**: When PG is PE-only and the
  deployer is on a network that cannot route to the PE subnet, the
  pipeline must either (a) be invoked from inside the ACA env (as an
  ACA Job sharing the backend UAMI), or (b) use `--hostaddr` + a hosts
  file override. `talent_infra_v2/hooks/postprovision.ps1` documents
  the hosts-file walk-through; we re-use that prompt.
- **Embedding endpoint must exist** before Phase 4 starts — otherwise
  the pipeline burns ~5 minutes on graph load before discovering the
  embedding deployment is missing. The prereq verification in step 1
  catches this.
- **Narrow grants supersede broad ones — but only if SQL works**:
  Steps 4-5 above are the path that takes a UAMI from "PG admin"
  (broad, from 01-postgresql's control-plane registration) down to
  "schema-scoped CRUD" (narrow, from `pgaadauth_create_principal_with_oid`).
  If SQL connectivity fails here, the UAMI **stays** as PG admin —
  that is the deliberate trade-off for unblocking the container app.
- **`shared_preload_libraries=age` precondition**: the pipeline's
  `cypher()` calls fail with `unhandled cypher(cstring) function call`
  if AGE was not preloaded + restarted. The prereq verification calls
  `Ensure-PostgresqlConfigApplied`-equivalent logic before Phase 4.

## To be implemented in this folder

```
04-data-loading/
├── README.md
├── deploy.ps1        TODO — orchestrates prereq checks + python invocation
└── .outputs.json     produced at runtime
```

`deploy.ps1` will dot-source `../shared/common.ps1` and shell out to
`python -m talent_data_pipeline.main` after the prereq + role
provisioning phases complete. It re-uses
`talent_infra_v2/scripts/provision_pg_entra_roles.py` (read-only —
do not modify).
