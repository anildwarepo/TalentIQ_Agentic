# 02-backend — Backend (FastAPI) + MCP sidecar Container App

## What this script will do

Build, push, and deploy the **TalentIQ backend** as a single Azure
Container App with the **MCP server** running as a **sidecar container**
in the same pod.

Phases:

1. **Verify** pre-existing resources: RG, VNet+subnets, ACA env, ACR,
   PG server (FQDN from `01-postgresql/.outputs.json`), Foundry account
   + project + deployments.
2. **Build & push** two images to ACR (Docker Desktop locally, or
   `az acr build` when `-UseAcrTasks` is set):
   - `<acr>/backend:<tag>` from `talent_backend/Dockerfile`
   - `<acr>/mcp-server:<tag>` from `talent_backend/Dockerfile.mcp`
3. **Provision a user-assigned managed identity** named
   `<backendContainerAppName>-identity` (or reuse if present).
4. **Register the UAMI as a PG Entra ServicePrincipal admin** via
   `az postgres flexible-server microsoft-entra-admin create`. This is
   the same control-plane registration as `01-postgresql/` but invoked
   here for the brand-new UAMI created in step 3.

   `Display-name` MUST equal the UAMI name. Skip with a warning when
   the UAMI is already an admin.
5. **Grant the UAMI** `AcrPull`, `Cognitive Services OpenAI User`, and
   `Cosmos DB Built-in Data Contributor` (if Cosmos is present).
6. **Deploy the Container App** with:
   - 2 containers: `backend` (port 8000, external ingress) + `mcp-server`
     (port 3002, intra-pod only).
   - Both containers receive `AZURE_CLIENT_ID=<UAMI.clientId>` so
     `DefaultAzureCredential` picks up the right identity.
   - The MCP sidecar's `PGUSER` is **the backend UAMI name**, not a
     separate identity — they share the same PG role.
   - `MCP_ENDPOINT=http://localhost:3002/mcp` injected into the backend
     container.
   - **`AZURE_TENANT_ID` is NOT set** — this is the auth-disable
     contract (see [../AUTH-DISABLED.md](../AUTH-DISABLED.md)). Without
     `AZURE_TENANT_ID`, `talent_backend/auth.py` short-circuits to dev
     mode and returns a synthetic user for every request.

7. **Optional revision restart**: when `-RestartActive` is supplied,
   run `az containerapp revision restart` on the active revision after
   confirming PG is Ready (see "Lessons encoded" below).
8. Write `02-backend/.outputs.json` with the backend FQDN, UAMI
   `clientId`, UAMI `principalId`, and the image tags.

## What this script will NOT do

- Create the ACA Environment, ACR, or VNet/subnets — those must
  pre-exist (verified in step 1).
- Run any `CREATE EXTENSION` SQL — the backend starts up assuming
  AGE, vector, pg_trgm, and pg_diskann are already installed in the
  `postgres` database. `04-data-loading/` installs them before the
  first load; if you skip that script you must install extensions some
  other way.
- Modify backend source code. The `VITE_DISABLE_AUTH` analogue for the
  frontend is a build-time flag (see `03-frontend/`); for the backend
  it is purely the *absence* of `AZURE_TENANT_ID` at runtime.
- Validate the Foundry model deployments by issuing a real
  inference call — only existence is checked.

## Inputs (parameters)

| Name                          | Env var                              | Default                         | Notes |
|-------------------------------|--------------------------------------|---------------------------------|-------|
| SubscriptionId                | `AZURE_SUBSCRIPTION_ID`              | —                               | |
| ResourceGroup                 | `AZURE_RESOURCE_GROUP`               | —                               | |
| Location                     | `AZURE_LOCATION`                     | `eastus`                        | |
| AcrName                       | `AZURE_ACR_NAME`                     | —                               | Must exist. |
| AcaEnvironmentName            | `AZURE_ACA_ENV_NAME`                 | —                               | Must exist. |
| BackendContainerAppName       | `BACKEND_CONTAINER_APP_NAME`         | `backend-<uniq>`                | Drives UAMI name `<this>-identity`. |
| BackendImageTag               | `BACKEND_IMAGE_TAG`                  | git short SHA, fallback `latest`| |
| McpImageTag                   | `MCP_IMAGE_TAG`                      | git short SHA, fallback `latest`| |
| BackendSourcePath             | `BACKEND_SOURCE_PATH`                | `../../talent_backend`          | |
| PostgresqlOutputsFile         | `POSTGRESQL_OUTPUTS_FILE`            | `../01-postgresql/.outputs.json`| Read for PG FQDN. |
| FoundryAccountName            | `FOUNDRY_ACCOUNT_NAME`               | —                               | |
| FoundryProjectName            | `FOUNDRY_PROJECT_NAME`               | `talentiq`                      | |
| FoundryChatDeploymentName     | `FOUNDRY_CHAT_DEPLOYMENT_NAME`       | `gpt-4.1`                       | |
| CosmosAccountName             | `COSMOS_ACCOUNT_NAME`                | empty                           | When empty, chat history is disabled. |
| CosmosDatabaseName            | `COSMOS_CHAT_DATABASE`               | `talent_db`                     | |
| CosmosContainerName           | `COSMOS_CHAT_CONTAINER`              | `chat_history_db`               | |
| BackendCpu                    | `BACKEND_CPU`                        | `0.5`                           | |
| BackendMemory                 | `BACKEND_MEMORY`                     | `1Gi`                           | |
| McpCpu                        | `MCP_CPU`                            | `0.5`                           | |
| McpMemory                     | `MCP_MEMORY`                         | `1Gi`                           | |
| UseAcrTasks                   | `USE_ACR_TASKS`                      | `false`                         | When true, `az acr build` instead of local Docker. |
| RestartActive                 | (switch only)                        | off                             | When set, restarts the active revision after deploy. |
| AppInsightsConnectionString   | `APPLICATIONINSIGHTS_CONNECTION_STRING` | empty                        | Optional. |

## Env vars injected into containers

| Var                                | Value                                                  | Notes |
|------------------------------------|--------------------------------------------------------|-------|
| `AZURE_CLIENT_ID`                  | UAMI clientId                                          | `DefaultAzureCredential` hint. |
| `PGHOST`                           | from `01-postgresql/.outputs.json`                     | privatelink FQDN when PE is on. |
| `PGPORT`                           | `5432`                                                 | |
| `PGDATABASE`                       | `postgres`                                             | |
| `PGUSER`                           | `<backendContainerAppName>-identity`                   | Same for backend AND MCP sidecar. |
| `GRAPH_NAME`                       | from `01-postgresql/.outputs.json` (default `talent_graph`) | |
| `AZURE_OPENAI_ENDPOINT`            | Foundry account `properties.endpoint`                  | |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`| `gpt-4.1` (default)                                    | |
| `MCP_ENDPOINT`                     | `http://localhost:3002/mcp`                            | Sidecar over the pod loopback. |
| `COSMOS_CHAT_ENDPOINT`             | Cosmos endpoint when account is supplied               | |
| `COSMOS_CHAT_DATABASE`             | `talent_db`                                            | |
| `COSMOS_CHAT_CONTAINER`            | `chat_history_db`                                      | |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | optional                                          | |
| **`AZURE_TENANT_ID`**              | **NOT SET**                                            | **DELIBERATELY omitted to disable JWT validation in `talent_backend/auth.py`.** |

## Outputs

```json
{
  "backendContainerAppName": "backend-66lb",
  "backendContainerAppFqdn": "backend-66lb.delightfulwave-1234.eastus.azurecontainerapps.io",
  "backendUamiName":         "backend-66lb-identity",
  "backendUamiClientId":     "<guid>",
  "backendUamiPrincipalId":  "<guid>",
  "backendImage":            "acrxyz.azurecr.io/backend:<sha>",
  "mcpImage":                "acrxyz.azurecr.io/mcp-server:<sha>"
}
```

`03-frontend/deploy.ps1` reads `backendContainerAppFqdn`.

## Deployment lessons encoded

- **MCP-as-sidecar**: One Container App, two containers in the same
  pod. The MCP container's `PGUSER` is the **backend's** UAMI name —
  there is **no separate MCP UAMI** and **no separate PG role for MCP**.
  Backend reaches MCP via `http://localhost:3002/mcp` (intra-pod
  loopback). This eliminates the `Mcp-Session-Id` restart cascade that
  the legacy two-app topology required.
- **Auth-disable is env-var-driven**: `talent_backend/auth.py` lines
  86-90 short-circuit to dev mode when `AZURE_TENANT_ID` is unset. This
  script enforces the contract by **never** setting that env var on
  either container. Re-enabling auth = set `AZURE_TENANT_ID`,
  `AZURE_CLIENT_ID` (currently aliased to the UAMI; flip to your SPA
  app registration's clientId), and `AZURE_TOKEN_AUDIENCE`; then
  restart the revision.
- **PG-role staleness**: When `01-postgresql/` registers a new UAMI as
  Entra admin after backend has already started, the backend's
  psycopg2 pool caches stale tokens. The `-RestartActive` switch runs
  `az containerapp revision restart` on the active revision to force a
  cold start with a fresh token. Always pair it with a check that PG
  is Ready first.
- **PowerShell quoting**: do not call `az containerapp exec ... -- python -c "..."`
  to verify deployment; the nested quote layers break on Windows. Use
  control-plane operations (`az containerapp show --query ...`) or a
  small base64-encoded script piped into `python -`.

## To be implemented in this folder

```
02-backend/
├── README.md
├── deploy.ps1        TODO
├── infra/
│   ├── main.bicep    TODO — references talent_infra_v2 container-app.bicep
│   └── main.parameters.json  TODO
└── .outputs.json     produced at runtime
```
