# DEPLOYMENT-ORDER.md — running the per-component scripts

> **Last updated:** 2026-05-21

The four scripts in `talent_infra_modules/` are independent, but they
**hand state off through files**. This document is the contract that
each script honors and the next script reads.

## The order

```
┌─────────────────────────────────────────────────────────────────┐
│  Pre-step: register the deployer as a PG Entra admin            │
│  (only needed if 01-postgresql is skipped because PG exists)    │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                ┌────────────────▼─────────────────┐
                │  01-postgresql/deploy.ps1        │
                │  (PG + extensions + Entra admin) │
                └─┬──────────────────────────┬─────┘
                  │                          │
                  │  .outputs.json           │  .outputs.json
                  │  (PG FQDN, tenant, UPN)  │
                  ▼                          ▼
   ┌──────────────────────────┐    ┌──────────────────────────┐
   │  02-backend/deploy.ps1   │    │  04-data-loading/        │
   │  (Backend + MCP sidecar) │    │  deploy.ps1              │
   └─────────┬────────────────┘    │  (Extensions + roles +   │
             │                     │   pipeline + indexes)    │
             │  .outputs.json      └──────────────────────────┘
             │  (Backend FQDN,                  ▲
             │   UAMI principalId)              │
             ▼                                  │ reads
   ┌──────────────────────────┐                 │ 02-backend
   │  03-frontend/deploy.ps1  │                 │ outputs to
   │  (Webapp w/ AUTH OFF)    │                 │ narrow UAMI
   └──────────────────────────┘                 │ grants
                                                │
                  ◄─────────────────────────────┘
```

## The contract: file hand-off

Each script writes a `.outputs.json` file in its own folder. The next
script reads that file by default (overridable via env var).

### Step 0 (OPTIONAL): `00-container-apps-env/deploy.ps1`

**When to run:** only when no Container Apps Environment exists yet (or
when you need a fresh, parallel env). Skip this step entirely if you
already have an ACA env you want `02-backend/` and `03-frontend/` to
target.

**Produces** `00-container-apps-env/.outputs.json`. The downstream-relevant
keys are:

- `containerAppsEnvName`
- `containerAppsEnvResourceGroup`
- `containerAppsEnvId`
- `acaSubnetId`, `acaSubnetName`

`02-backend/deploy.ps1` and `03-frontend/deploy.ps1` read
`containerAppsEnvName` and `containerAppsEnvResourceGroup` from this
file as a **soft fallback** when their own `-ContainerAppsEnvName`
/ `-ContainerAppsEnvResourceGroup` arguments and matching env vars are
empty. The fallback never fails if the file is missing.

**Reruns are safe.** ARM reconciles the env in place; if the subnet
already exists with the right delegation, the script skips subnet
creation entirely. The ~30-minute soft-lock after env deletion is the
only hard wait — the script detects it and tells you to wait.

### Pre-step (only when skipping `01-postgresql/`)

If PG already exists and was provisioned by `talent_infra_v2/` or any
other path, run:

```powershell
& ./../talent_infra_v2/scripts/Enable-PostgresEntraAuth.ps1 `
    -ResourceGroup <rg> `
    -ServerName    <pg-server> `
    -AdminUpn      $(az account show --query user.name -o tsv)
```

This makes sure the deployer can connect with an Entra token. If you
skip this and skip `01-postgresql/`, then `04-data-loading/` will fail
at Phase 4 with `Login failed for user '<upn>'`.

You will then need to **synthesize** `01-postgresql/.outputs.json` by
hand so `02-backend/` and `04-data-loading/` know how to reach PG:

```json
{
  "postgresqlServerName":  "tiqpgexisting",
  "postgresqlServerFqdn":  "tiqpgexisting.postgres.database.azure.com",
  "postgresqlPrivateFqdn": "tiqpgexisting.privatelink.postgres.database.azure.com",
  "postgresqlPrivateIp":   "10.0.4.5",
  "deployerEntraUpn":      "anildwa@example.onmicrosoft.com",
  "tenantId":              "150305b3-cc4b-46dd-9912-425678db1498"
}
```

### Step 1: `01-postgresql/deploy.ps1`

**Produces** `01-postgresql/.outputs.json`. See
[`01-postgresql/README.md`](01-postgresql/README.md) for the full
schema; the relevant keys for downstream are:

- `postgresqlServerFqdn` (or `postgresqlPrivateFqdn` for PE)
- `postgresqlServerName`
- `deployerEntraUpn`
- `tenantId`

**Reruns are safe.** The script no-ops the server create, re-applies
parameters only if pending restart, and re-emits the outputs file.

### Step 2: `02-backend/deploy.ps1`

**Reads** `01-postgresql/.outputs.json` for `postgresqlServerFqdn`
and `tenantId`. Override via `POSTGRESQL_OUTPUTS_FILE`.

**Produces** `02-backend/.outputs.json` with:

- `backendContainerAppName`
- `backendContainerAppFqdn`
- `backendUamiName`
- `backendUamiClientId`
- `backendUamiPrincipalId`
- `backendImage`, `mcpImage`

**Side effects on PG**: registers `<backendContainerAppName>-identity`
as a PG Entra ServicePrincipal admin via the control plane. This is
the broad-privilege fallback; narrow it later via Step 4.

### Step 3: `03-frontend/deploy.ps1`

**Reads** `02-backend/.outputs.json` for `backendContainerAppFqdn`.
Override via `BACKEND_OUTPUTS_FILE` or `BACKEND_FQDN`.

**Produces** `03-frontend/.outputs.json` with:

- `webappContainerAppName`
- `webappContainerAppFqdn`

**No PG / Foundry side effects** — the frontend has no UAMI role
assignments outside ACR pull.

### Step 4: `04-data-loading/deploy.ps1`

**Reads**:

- `01-postgresql/.outputs.json` (required) for PG FQDN, server name,
  graph name, deployer UPN.
- `02-backend/.outputs.json` (optional, when present) for the backend
  UAMI to narrow.

**Produces** `04-data-loading/.outputs.json` with load stats (rows
loaded, elapsed time). No downstream consumers — informational only.

**Side effects on PG**:

- `CREATE EXTENSION` for AGE, vector, pg_trgm, pg_diskann.
- If backend outputs were read, downgrades the backend UAMI from broad
  PG admin to schema-scoped grants via
  `pgaadauth_create_principal_with_oid` + `GRANT ... ON SCHEMA ag_catalog,
  public, <graph-schema>`.
- Loads ~130k employees, edges, and embeddings into the graph.

**Can be re-run** — the pipeline's own idempotency check (
`_data_already_loaded()` in `talent_data_pipeline/main.py` lines ~130+)
short-circuits Phases 3-4 when employees ≥ 90% of `EMPLOYEE_COUNT` and
the embeddings table is similarly populated. Pass `-Force` to bypass.

## Skipping steps

Each step can be skipped if its outputs already exist and you trust
them. The downstream script will simply read the existing
`.outputs.json` and continue.

Common skip patterns:

| You want to...                            | Run                                  | Skip                          |
|-------------------------------------------|--------------------------------------|-------------------------------|
| Iterate on backend code only              | 02 (with new tag)                    | 01, 03, 04                    |
| Iterate on frontend code only             | 03 (with new tag)                    | 01, 02, 04                    |
| Reload data on existing stack             | 04 (with `-Force`)                   | 01, 02, 03                    |
| Stand up everything from scratch          | 01, 02, 03, 04 (in order)            | nothing                       |
| Recover from a corrupted backend revision | 02 with `-RestartActive`             | usually 01, 03, 04            |

## When ordering breaks

| Symptom                                                       | Likely cause                                                  | Fix |
|---------------------------------------------------------------|---------------------------------------------------------------|-----|
| Backend pod 502s on first request, logs show `pg connect: password authentication failed for user "backend-xxx-identity"` | UAMI was not registered as PG Entra admin | Re-run `02-backend/deploy.ps1` — the registration step is idempotent |
| `unhandled cypher(cstring) function call` from backend logs   | AGE not preloaded + restarted                                 | Re-run `01-postgresql/deploy.ps1`; check `isConfigPendingRestart` |
| `04-data-loading` fails Phase 4 with `function pgaadauth_create_principal_with_oid does not exist` | PG version `<14` or `pgaadauth` not enabled | Use PG 16 in `01-postgresql/`; the extension is built in for 16 |
| Frontend loads but shows login screen                         | `VITE_DISABLE_AUTH` flag NOT honored by code                  | Code change in `talent_ui/` is required (Dallas) — see [AUTH-DISABLED.md](AUTH-DISABLED.md) |
| Frontend loads, backend returns 401 on /chat                  | Backend has `AZURE_TENANT_ID` set                             | Re-run `02-backend/deploy.ps1` — it should never set that var |
| Re-running `02-backend/` produces a new revision but PG calls still fail | psycopg2 pool cached stale tokens | Re-run with `-RestartActive` |
| `01-postgresql/` errors `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible` | Concurrent control-plane op on PG | Wait 60 s; PG flex serializes |
| `02-backend/` errors `IfMatchPreconditionFailed` on Foundry deployment | Concurrent ETag write on the same model deployment | Only happens if the script tries to *create* a deployment — should never happen in this folder. If it does, the script is misconfigured. |

## Disposal

There is **no `destroy.ps1`**. To clean up:

```powershell
# Container apps and their UAMIs
az containerapp delete --name <webapp>  --resource-group <rg> --yes
az containerapp delete --name <backend> --resource-group <rg> --yes
az identity delete --name <webapp>-identity  --resource-group <rg>
az identity delete --name <backend>-identity --resource-group <rg>

# PG (only if 01-postgresql created it — DOUBLE CHECK)
az postgres flexible-server delete --name <pg> --resource-group <rg> --yes

# Private endpoint + DNS link (only if 01-postgresql created them)
az network private-endpoint delete --name <pg>-pe --resource-group <rg>
```

Leave RG, VNet, ACA env, ACR, and Foundry intact — those pre-existed.

If in doubt, list resources first:

```powershell
az resource list --resource-group <rg> --output table
```

and delete only the rows whose name matches what these scripts emit.
