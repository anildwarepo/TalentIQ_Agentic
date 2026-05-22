# 03-frontend — React/Vite UI Container App (MSAL bypass)

## What this script will do

Build, push, and deploy the **TalentIQ frontend** (React/Vite served by
nginx) as a single Azure Container App.

Phases:

1. **Verify** pre-existing resources: RG, ACA env, ACR. Read
   `02-backend/.outputs.json` for the backend's externally-routable
   FQDN.
2. **Build & push** `<acr>/webapp:<tag>` from `talent_ui/Dockerfile`
   with the following **build-time** args:
   - `VITE_DISABLE_AUTH=true` — the auth-bypass flag the frontend code
     reads at build time (see "Frontend code change required" below).
   - `VITE_API_BASE=https://<backend FQDN>` — backend chat endpoints.
   - `VITE_AF_BACKEND_URL=https://<backend FQDN>/af` — Agent Framework
     route prefix (matches the dev-mode default `/af`).
   - `VITE_AGENT_NAME=talentiq-agent`
3. **Provision a user-assigned managed identity** named
   `<webappContainerAppName>-identity` for ACR pulls (no PG / Foundry
   roles needed for the UI).
4. **Grant the UAMI** `AcrPull` on the ACR.
5. **Deploy the Container App** on port 80 with **external ingress**
   enabled and `allowInsecure=false`. No secrets, no Redis, no PG.
6. Write `03-frontend/.outputs.json` with the UI FQDN.

## What this script will NOT do

- Create the ACA env or ACR.
- Talk to PG, Foundry, or Cosmos.
- Provision Entra ID app registrations (in normal-auth mode the UI
  needs an Entra SPA registration with redirect URI = the UI FQDN; in
  auth-disabled mode this is not needed and the script does NOT create
  one).
- Modify the frontend source. The `VITE_DISABLE_AUTH` bypass requires
  a **one-time code change** in `talent_ui/src/main.jsx` and
  `talent_ui/src/App.jsx` (see below). That is a frontend-team
  deliverable, not this script's responsibility.

## Frontend code change required (one-time)

This script alone will **not** disable Microsoft sign-in. The React
code currently hard-wires `MsalProvider` in
[`talent_ui/src/main.jsx`](../../talent_ui/src/main.jsx) and gates the
entire UI behind `useIsAuthenticated()` in
[`talent_ui/src/App.jsx`](../../talent_ui/src/App.jsx) (line ~1033:
`if (!isAuthenticated) { return <login-card> }`).

The frontend developer must add a `VITE_DISABLE_AUTH` branch:

- **`main.jsx`**: when `import.meta.env.VITE_DISABLE_AUTH === "true"`,
  render `<App />` directly (no `MsalProvider`, no `PublicClientApplication`).
- **`App.jsx`**: when the flag is on:
  - Skip `useIsAuthenticated()` / `useMsal()` / `getToken()` entirely
    (use a static `{ name: "Dev User", username: "dev@localhost" }` for
    `account`, and `null` for `accessToken`).
  - Send all backend requests **without** the `Authorization: Bearer ...`
    header. The backend in auth-disabled mode short-circuits in
    `talent_backend/auth.py` and returns a synthetic dev user.

The exact diff is the frontend dev's call (Dallas's deliverable in
follow-up work); see [../AUTH-DISABLED.md](../AUTH-DISABLED.md) for
the full env-var matrix and security implications.

## Inputs (parameters)

| Name                       | Env var                          | Default                                | Notes |
|----------------------------|----------------------------------|----------------------------------------|-------|
| SubscriptionId             | `AZURE_SUBSCRIPTION_ID`          | —                                      | |
| ResourceGroup              | `AZURE_RESOURCE_GROUP`           | —                                      | |
| Location                   | `AZURE_LOCATION`                 | `eastus`                               | |
| AcrName                    | `AZURE_ACR_NAME`                 | —                                      | |
| AcaEnvironmentName         | `AZURE_ACA_ENV_NAME`             | —                                      | |
| WebappContainerAppName     | `WEBAPP_CONTAINER_APP_NAME`      | `webapp-<uniq>`                        | |
| WebappImageTag             | `WEBAPP_IMAGE_TAG`               | git short SHA, fallback `latest`       | |
| WebappSourcePath           | `WEBAPP_SOURCE_PATH`             | `../../talent_ui`                      | |
| BackendOutputsFile         | `BACKEND_OUTPUTS_FILE`           | `../02-backend/.outputs.json`          | Read for backend FQDN. |
| BackendFqdnOverride        | `BACKEND_FQDN`                   | (from outputs)                         | Useful when backend was deployed elsewhere. |
| DisableAuth                | `VITE_DISABLE_AUTH`              | `true`                                 | Build-time flag passed through. |
| WebappCpu                  | `WEBAPP_CPU`                     | `0.25`                                 | |
| WebappMemory               | `WEBAPP_MEMORY`                  | `0.5Gi`                                | |
| UseAcrTasks                | `USE_ACR_TASKS`                  | `false`                                | |

## Outputs

```json
{
  "webappContainerAppName": "webapp-66lb",
  "webappContainerAppFqdn": "webapp-66lb.delightfulwave-1234.eastus.azurecontainerapps.io",
  "webappUamiName":         "webapp-66lb-identity",
  "webappUamiClientId":     "<guid>",
  "webappImage":            "acrxyz.azurecr.io/webapp:<sha>",
  "viteDisableAuth":        true
}
```

## Deployment lessons encoded

- **`VITE_*` is build-time, not runtime**: Vite inlines `import.meta.env.VITE_*`
  values at `npm run build` time. The script must pass them as `--build-arg`
  to Docker (or `--build-arg` to `az acr build`); setting them as
  Container App environment variables has **no effect** on the
  already-compiled bundle.
- **External ingress is required**: This is the user-facing endpoint;
  no internal-only mode. `allowInsecure=false` so nginx serves only
  HTTPS (ACA terminates TLS at the edge).
- **No backend reverse-proxy**: The frontend talks to the backend's
  **public** FQDN directly. The backend is deployed with
  `externalIngress=true` in `02-backend/`. The legacy
  `BACKEND_URL=https://<backend>.internal.<acaEnvDomain>` pattern from
  `talent_infra_v2/` does NOT apply here because the UI runs in the
  user's browser, not inside the ACA env.
- **MSAL must be guarded behind the flag**: leaving `MsalProvider`
  mounted while `VITE_DISABLE_AUTH=true` causes `PublicClientApplication`
  to attempt token acquisition against an invalid tenant and throws a
  CORS error on first load. The code change above must remove the
  provider mount, not just the gating component.

## To be implemented in this folder

```
03-frontend/
├── README.md
├── deploy.ps1        TODO
├── infra/
│   ├── main.bicep    TODO
│   └── main.parameters.json  TODO
└── .outputs.json     produced at runtime
```
