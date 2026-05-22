# AUTH-DISABLED.md — Entra ID auth bypass contract

> **TL;DR**: The `talent_infra_modules/` scripts deploy a demo stack
> where the **React UI does not require sign-in** and the **FastAPI
> backend does not validate JWTs**. PostgreSQL and Foundry still use
> Entra ID — the bypass is only between the user and the application
> tier. **Do not use this configuration in production.**

## Why we have a bypass mode

The motivating scenario is a partial-environment deployment where:

- Most Azure infra already exists (RG, VNet, ACR, ACA env, Foundry).
- A new app-registration (SPA + API) is **not** available or would take
  too long to provision (admin consent, redirect URI churn, audience
  alignment).
- We just need to validate the end-to-end stack — UI → backend → MCP →
  PG → Foundry — without the MSAL ceremony.

In production (`talent_infra_v2/`) the full Entra ID auth path is
mandatory. In `talent_infra_modules/` it is **off by default**.

## The two-piece contract

### Backend: omit `AZURE_TENANT_ID`

[`talent_backend/talent_backend/auth.py`](../talent_backend/talent_backend/auth.py)
lines 86-90 short-circuit when `AZURE_TENANT_ID` is unset:

```python
if not AZURE_TENANT_ID:
    logger.warning("AZURE_TENANT_ID not set — auth is DISABLED (dev mode)")
    return {"oid": "dev-user", "name": "Dev User", "email": "dev@localhost"}
```

Every request returns the same synthetic user; no JWT validation, no
JWKS fetch, no audience check.

The `02-backend/deploy.ps1` script **deliberately does not set**
`AZURE_TENANT_ID` on either container (backend or MCP sidecar). The
auth-disable state is therefore the **default**.

#### Backend env-var matrix

| Variable                                | Normal (Entra ID auth ON) | Auth-disabled (this folder) |
|-----------------------------------------|---------------------------|-----------------------------|
| `AZURE_TENANT_ID`                       | tenant GUID               | **unset**                   |
| `AZURE_CLIENT_ID`                       | UAMI clientId (for `DefaultAzureCredential`) | UAMI clientId (still needed for PG / Foundry) |
| `AZURE_API_AUDIENCE` / `AZURE_TOKEN_AUDIENCE` | `api://<app-id>` (or the SPA's clientId) | unset |
| `PGHOST`/`PGUSER`/etc.                  | as documented              | identical                   |
| `AZURE_OPENAI_ENDPOINT`                 | Foundry endpoint           | identical                   |
| `MCP_ENDPOINT`                          | `http://localhost:3002/mcp`| identical                   |

`AZURE_CLIENT_ID` is still required — it tells `DefaultAzureCredential`
which UAMI to use when fetching PG and Foundry tokens. The bypass is
purely on the inbound HTTP path, not on outbound service calls.

### Frontend: `VITE_DISABLE_AUTH=true` build arg

[`talent_ui/src/main.jsx`](../talent_ui/src/main.jsx) currently
**unconditionally** wraps the app in `<MsalProvider>`. [`App.jsx`](../talent_ui/src/App.jsx)
gates the entire UI behind `useIsAuthenticated()` (around line 1033).

To enable the bypass, the frontend developer must add a build-time
flag check:

```jsx
// main.jsx
if (import.meta.env.VITE_DISABLE_AUTH === "true") {
  root.render(<App />);
} else {
  root.render(
    <MsalProvider instance={msalInstance}>
      <App />
    </MsalProvider>
  );
}
```

```jsx
// App.jsx — pseudo-diff
const authDisabled = import.meta.env.VITE_DISABLE_AUTH === "true";
const account = authDisabled
  ? { name: "Dev User", username: "dev@localhost" }
  : (useMsal().accounts[0] ?? null);
const isAuthenticated = authDisabled ? true : useIsAuthenticated();
const getToken = authDisabled
  ? async () => null
  : async () => instance.acquireTokenSilent({ ...foundryLoginRequest, account, forceRefresh: false }).then(r => r.accessToken);

// later:
fetch(`${VITE_API_BASE}/chat`, {
  headers: authDisabled ? {} : { Authorization: `Bearer ${await getToken()}` },
  ...
});
```

`03-frontend/deploy.ps1` passes `--build-arg VITE_DISABLE_AUTH=true`
into the Docker build. `VITE_*` values are inlined into the JS bundle
at build time; they **cannot** be overridden at runtime via Container
App env vars.

#### Frontend build-arg matrix

| Build arg                  | Normal (Entra ID auth ON)             | Auth-disabled (this folder) |
|----------------------------|----------------------------------------|-----------------------------|
| `VITE_DISABLE_AUTH`        | `false` (or unset)                     | `true`                      |
| `VITE_API_BASE`            | `https://<backend>`                    | identical                   |
| `VITE_AF_BACKEND_URL`      | `https://<backend>/af`                 | identical                   |
| `VITE_AGENT_NAME`          | `talentiq-agent`                       | identical                   |
| `VITE_MSAL_CLIENT_ID`      | SPA app registration clientId          | unused                      |
| `VITE_MSAL_TENANT_ID`      | tenant GUID                            | unused                      |
| `VITE_MSAL_REDIRECT_URI`   | `https://<webapp>/`                    | unused                      |

## What is NOT bypassed

Even with auth disabled:

- **Backend → PostgreSQL**: still uses Entra ID. The backend UAMI is
  registered as a PG Entra ServicePrincipal admin (or a narrow role
  once `04-data-loading/` runs).
- **Backend → Foundry**: still uses Entra ID. `DefaultAzureCredential`
  → UAMI → `Cognitive Services OpenAI User` role assignment.
- **Backend → Cosmos**: still uses Entra ID via the `Cosmos DB
  Built-in Data Contributor` role on the UAMI (when Cosmos is
  configured).
- **ACR pulls**: still UAMI + `AcrPull`.

Only the **inbound** path (user → frontend → backend) is unauthenticated.

## Security implications

This configuration MUST NOT be used in production. Specifically:

1. **Anyone with the UI URL can use the app.** There is no
   authentication, no rate limiting beyond ACA's defaults, no audit
   trail of who called what.
2. **Every request is logged as `dev-user`.** Telemetry, chat history
   in Cosmos, and any per-user state will all coalesce on a single
   identity. Forensics is impossible.
3. **The backend trusts every header.** A malicious caller can send
   any `X-Forwarded-*`, any cookie, any body — `auth.py` does not
   inspect them when `AZURE_TENANT_ID` is unset.
4. **Foundry costs are unattributable.** The UAMI bills all model
   calls regardless of who triggered them. Cap quotas in Foundry
   itself; do not rely on per-user limits.
5. **CORS is permissive.** The backend's auth-disabled mode is paired
   with a development CORS policy (`*`); production needs an explicit
   origin allow-list anyway.

Mitigations when this mode is exposed to a wider audience:

- Put a Front Door or App Gateway in front with IP allow-list + WAF.
- Cap Foundry deployment SKU and tokens-per-minute aggressively.
- Set a hard ACA replica limit (`maxReplicas: 1`) to bound load.
- Disable chat history persistence (omit `COSMOS_*` env vars) so
  there is no per-user data to leak.

## Re-enabling Entra ID auth

1. **Decide on the identities** — a SPA app registration for the UI
   and an API app registration (or the same one with
   `accessTokenAcceptedVersion: 2`) for the backend audience.
2. **Backend**: set `AZURE_TENANT_ID`, `AZURE_API_AUDIENCE` (and any
   other env vars `auth.py` reads), then `az containerapp revision
   restart`.
3. **Frontend**: rebuild with `VITE_DISABLE_AUTH=false` (or unset) and
   the appropriate `VITE_MSAL_*` values. Push and create a new
   revision.
4. **Add the UI's URL** as a redirect URI on the SPA app registration.
5. **Grant the SPA** delegated permission `User.Read` (and any custom
   scope on the API registration). Admin consent if required.
6. **Verify**: the UI now redirects to `login.microsoftonline.com` on
   first load; backend rejects requests without a valid bearer token.

At that point you have rebuilt what `talent_infra_v2/` deploys by
default — consider whether you should be using that template instead.
