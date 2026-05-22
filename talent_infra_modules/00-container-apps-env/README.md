# 00-container-apps-env — Azure Container Apps Environment (VNet-integrated)

## What this script will do

Deploy a single **Azure Container Apps Environment (ACA Env)** wired into
a pre-existing VNet, with:

- **Consumption workload profile** (the only profile this stack uses).
- **VNet integration** via an infrastructure subnet delegated to
  `Microsoft.App/environments`. The subnet is either:
  - **Pre-existing** — verified to be delegated to `Microsoft.App/environments`
    and not already claimed by a *different* Container Apps Environment, OR
  - **Created on the fly** inside the supplied VNet (sidecar deployment of
    `infra/modules/aca-subnet.bicep` into the VNet's resource group). A CIDR
    must be supplied via `-AcaSubnetAddressPrefix` and is validated to fit
    inside one of the VNet's `addressSpace.addressPrefixes` before any change.
- **Log Analytics workspace** (`PerGB2018`, 30-day retention) auto-named
  `<EnvName>-logs` (or `-LogAnalyticsWorkspaceName` if provided). The env is
  wired to ship app logs to this workspace.
- **Optional internal-only ingress** (`vnetConfiguration.internal=true`) via
  `-InternalOnly`. Defaults to `$false` to mirror the v2 baseline (public FQDN
  with VNet-resolved private IP).

deploy.ps1 does all the "existing-or-create" plumbing on the control plane
**before** Bicep runs, so the template only receives a fully-qualified
`subnetId`. This keeps the Bicep declarative and side-effect-free, and avoids
a known Bicep limitation around ternary references that cross conditional
modules and conditional `existing` resources (BCP032).

## What this script will NOT do

- **Create the VNet or resource groups.** Both must exist.
- **Modify an existing subnet's delegation.** If the subnet exists without
  delegation to `Microsoft.App/environments`, the script fails clearly with
  remediation instructions — it never auto-adds delegation to a subnet that
  may carry other workloads.
- **Deploy any Container Apps.** That is the job of `02-backend/` and
  `03-frontend/`. This module only creates the *environment* they target.
- **Provision the Application Insights resource.** The companion module
  `container-apps-environment.bicep` exposes
  `appInsightsConnectionString` as an empty string output (placeholder) so
  downstream consumers can wire AI separately if they want it.
- **Register any role assignments.** Container App identities + their RBAC
  on PG / ACR / Foundry are owned by `02-backend/` and `03-frontend/`.

## When to run

This module is **OPTIONAL**. The other 4 modules (01-postgresql,
02-backend, 03-frontend, 04-data-loading) treat the ACA env as a
pre-existing resource — and in most environments it is. Run **00** only
when:

- You are bootstrapping a brand-new environment that does **not** already
  have a Container Apps Environment, OR
- You need to provision a *second* env (e.g. internal-only) alongside an
  existing public one.

Because **00** has no dependency on **01**, it can be deployed in
**parallel** with `01-postgresql`. Both are prerequisites for `02-backend`
and `03-frontend`.

## Inputs (parameters)

| Name                       | Env var                          | Default                                | Notes |
|----------------------------|----------------------------------|----------------------------------------|-------|
| SubscriptionId             | `AZURE_SUBSCRIPTION_ID`          | active `az` account                    | Required. |
| ResourceGroup              | `AZURE_RESOURCE_GROUP`           | —                                      | Must exist. Hosts the ACA env. |
| Location                   | `AZURE_LOCATION`                 | `eastus`                               | Region for the env + LA workspace. |
| EnvName                    | `AZURE_ACA_ENV_NAME`             | `cae-<5-char SHA256(subId\|rg\|loc)>`  | 2-32 chars, region-unique. Deterministic default ⇒ idempotent re-runs. |
| VnetResourceGroup          | `AZURE_VNET_RESOURCE_GROUP`      | = ResourceGroup                        | RG of the VNet. |
| VnetName                   | `AZURE_VNET_NAME`                | —                                      | Required. Must exist. |
| AcaSubnetName              | `AZURE_ACA_SUBNET_NAME`          | `talentiq-aca`                         | If present, delegation is verified. If absent, the subnet is created. |
| AcaSubnetAddressPrefix     | `AZURE_ACA_SUBNET_PREFIX`        | —                                      | **REQUIRED when subnet does not exist.** Recommended /23. CIDR must fit inside `VNet.addressSpace.addressPrefixes`. |
| InternalOnly               | `AZURE_ACA_INTERNAL_ONLY`        | `$false`                               | When `$true`, sets `vnetConfiguration.internal=true`. |
| LogAnalyticsWorkspaceName  | `AZURE_LOG_ANALYTICS_NAME`       | `<EnvName>-logs`                       | Workspace is created in `ResourceGroup`. |
| Force                      | —                                | (off)                                  | Skip the interactive confirmation prompt. |

## Outputs

Written to `<script-dir>/.outputs.json` so `02-backend/` and `03-frontend/`
can auto-discover the env without further configuration:

```json
{
  "containerAppsEnvName":          "cae-3ab12",
  "containerAppsEnvId":            "/subscriptions/.../Microsoft.App/managedEnvironments/cae-3ab12",
  "containerAppsEnvResourceGroup": "talentiq-rg",
  "containerAppsEnvDefaultDomain": "kindforest-3ab12.eastus.azurecontainerapps.io",
  "containerAppsEnvStaticIp":      "10.0.6.4",
  "acaSubnetId":                   "/subscriptions/.../virtualNetworks/talentiq-vnet/subnets/talentiq-aca",
  "acaSubnetName":                 "talentiq-aca",
  "vnetName":                      "talentiq-vnet",
  "vnetResourceGroup":             "talentiq-network-rg",
  "logAnalyticsWorkspaceId":       "/subscriptions/.../workspaces/cae-3ab12-logs",
  "internalOnly":                  false,
  "location":                      "eastus",
  "subscriptionId":                "00000000-0000-0000-0000-000000000000"
}
```

The `02-backend/deploy.ps1` and `03-frontend/deploy.ps1` scripts read
`containerAppsEnvName` and `containerAppsEnvResourceGroup` from this file
when their own `-ContainerAppsEnvName` / `-ContainerAppsEnvResourceGroup`
arguments and `AZURE_ACA_ENV_NAME` / `AZURE_ACA_ENV_RESOURCE_GROUP` env
vars are both empty (soft fallback — never fails if the file is missing).

## Deployment lessons encoded

- **1:1 mapping between ACA Env and infrastructure subnet** (Azure error
  `ManagedEnvironmentSubnetInUse`). deploy.ps1 lists every Container Apps
  env in the target subscription and refuses to create a new env that
  would step on a subnet already owned by a *different* env (it still
  allows idempotent re-runs against the *same* env name).
- **~30-minute subnet soft-lock after env deletion.** When the
  ownership-collision check fires, the script's failure message includes
  the explicit "delete the existing env, wait ~30 minutes, re-run"
  guidance so operators don't get stuck retrying immediately.
- **Subnet must be delegated to `Microsoft.App/environments`.** Pre-existing
  subnets without this delegation are rejected with a remediation
  command — never silently mutated.
- **CIDR containment check before subnet create.** If we are about to
  create the subnet, the requested CIDR is validated to fit inside one of
  the VNet's `addressSpace.addressPrefixes` (PowerShell-side IPv4 math,
  no internet calls). This catches "wrong /16" mistakes before Bicep
  starts a 5-minute deployment that would fail late.
- **Bicep BCP032 around mixed conditional resources.** Earlier iterations
  tried to express `createSubnet ? createdSubnet.outputs.id : existingSubnet.id`
  inside the same Bicep template. Bicep's compile-time-constant check
  rejects ternaries that mix a conditional `module` with a conditional
  `existing` resource. Moving the subnet decision out of Bicep and into
  PowerShell removed the limitation entirely — the bicep template
  now takes a single resolved `subnetId` parameter, matching the simpler
  pattern of the other four modules.
- **Single dot-quote source for `subnetId`.** After the optional sidecar
  subnet deployment, we re-query the subnet via
  `az network vnet subnet show --query id -o tsv` so the value passed to
  `main.bicep` is always the canonical ARM ID, whether the subnet was
  just created or already existed.

## Re-running

This script is **idempotent**. Re-running against an existing env:

1. **Skips subnet creation** when the subnet already exists with the right
   delegation (verifies delegation and soft-lock status only).
2. **Re-runs the main Bicep deployment** — ARM updates the env in place
   without disruption. Tags, internal-only flag, and Log Analytics linkage
   are reconciled.
3. **Re-emits `.outputs.json`** with the latest values.

If you want to *recreate* the env on the same subnet you must first delete
the env and wait ~30 minutes for the soft-lock to clear (the script will
detect the conflict and tell you exactly this).

## Folder layout

```
00-container-apps-env/
├── README.md                              (this file)
├── deploy.ps1                             entry point — dot-sources ../shared/common.ps1
├── infra/
│   ├── main.bicep                         ACA env + Log Analytics
│   ├── main.parameters.json               defaults for internalOnly / logAnalyticsWorkspaceName / tags
│   └── modules/
│       ├── container-apps-environment.bicep  Env + LA workspace (lifted from v2)
│       └── aca-subnet.bicep                  Sidecar subnet creator (lifted from v2)
└── .outputs.json                          produced at runtime
```

The two `modules/` files are byte-for-byte copies of their counterparts in
`talent_infra_v2/infra/modules/` (no behavioural drift). They are vendored
locally so each module folder under `talent_infra_modules/` remains
self-contained — no relative climbing into `talent_infra_v2/`.
