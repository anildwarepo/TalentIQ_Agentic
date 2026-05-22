# 01-postgresql — PostgreSQL Flexible Server (AGE + vector + diskann + Entra)

## What this script will do

Deploy a single **Azure Database for PostgreSQL Flexible Server** with:

- **Extensions allow-listed and preloaded**:
  - `azure.extensions = AGE,VECTOR,PG_TRGM,PG_DISKANN`
  - `shared_preload_libraries = age` (requires server restart — handled
    automatically)
- **Entra ID auth enabled** (`activeDirectoryAuth = Enabled`) with
  password auth retained by default (flip via `-EntraOnly` once all
  identities are registered).
- The **deployer** (current `az` signed-in user) registered as a User
  Entra administrator so subsequent SQL-based role provisioning (data
  load, backend) can connect with an Entra token.
- **(Optional)** A list of pre-existing **UAMI principalIds**
  (e.g. `<backendContainerAppName>-identity`) registered as
  ServicePrincipal Entra administrators via the **control plane**
  (`az postgres flexible-server microsoft-entra-admin create
  --type ServicePrincipal --display-name <UAMI-name> --object-id <UAMI-principalId>`).

  This is the deliberate **control-plane fallback** path — it bypasses
  the `pgaadauth_create_principal_with_oid` SQL approach for
  environments where the deployer cannot reach 5432 (ISP block, PE-only
  server). The display name **must** equal the UAMI's `name`, because
  that becomes the PG username the container will present.
- **(Optional)** Private endpoint into the pre-existing `pe-subnet`,
  with a Private DNS Zone link to the target VNet.
- **Firewall rules** for AllowAllAzureServices and the deployer's
  public IP (so the data pipeline can connect from a workstation).

## What this script will NOT do

- Create the VNet, subnets, or private DNS zones for the VNet itself
  — those must pre-exist.
- Create the resource group.
- Provision per-application PG roles via SQL (that is the
  04-data-loading script's job for the deployer, and the backend's
  startup pool for the UAMI). This script only *registers* the UAMI
  as an Entra ServicePrincipal admin so the UAMI can connect.
- Apply `CREATE EXTENSION` statements — those run during 04-data-loading
  inside the `postgres` database.

## Inputs (parameters)

| Name                       | Env var                          | Default              | Notes |
|----------------------------|----------------------------------|----------------------|-------|
| SubscriptionId             | `AZURE_SUBSCRIPTION_ID`          | —                    | Required. |
| ResourceGroup              | `AZURE_RESOURCE_GROUP`           | —                    | Must exist. |
| Location                   | `AZURE_LOCATION`                 | `eastus`             | Region for the PG server. |
| ServerName                 | `POSTGRESQL_SERVER_NAME`         | `tiqpg<uniq>`        | 3-63 chars, globally unique. |
| AdminLogin                 | `POSTGRESQL_ADMIN_LOGIN`         | `pgadmin`            | Password auth admin (still useful for break-glass). |
| AdminPassword              | `POSTGRESQL_ADMIN_PASSWORD`      | — (prompted, secure) | 8+ chars, complexity per Azure rules. |
| PostgresqlVersion          | `POSTGRESQL_VERSION`             | `16`                 | |
| SkuName                    | `POSTGRESQL_SKU_NAME`            | `Standard_B2s`       | |
| SkuTier                    | `POSTGRESQL_SKU_TIER`            | `GeneralPurpose`     | |
| StorageSizeGB              | `POSTGRESQL_STORAGE_GB`          | `32`                 | |
| EnablePrivateEndpoint      | `POSTGRESQL_ENABLE_PE`           | `true`               | When true, requires VNet+pe-subnet to exist. |
| VnetResourceGroup          | `AZURE_VNET_RESOURCE_GROUP`      | = ResourceGroup      | |
| VnetName                   | `AZURE_VNET_NAME`                | —                    | Required when EnablePrivateEndpoint=true. |
| PeSubnetName               | `AZURE_PE_SUBNET_NAME`           | `pe-subnet`          | |
| ExistingDnsZoneId          | `POSTGRESQL_DNS_ZONE_ID`         | empty                | If empty, a new zone is created and linked. |
| ClientIpAddress            | `POSTGRESQL_CLIENT_IP`           | auto-detected        | Used for AllowClientIp firewall rule. |
| UamiPrincipalIds           | `POSTGRESQL_UAMI_PRINCIPALS`     | empty                | JSON list `[{ "name": "...", "objectId": "..." }, ...]`. Registered as ServicePrincipal Entra admins. |
| EntraOnly                  | `POSTGRESQL_ENTRA_ONLY`          | `false`              | When `true`, disables password auth. Do not flip until all clients (UAMIs + deployer) are registered. |
| FixStaleDnsZoneGroup       | —                                | `false`              | Self-heal switch. When set (or with `-Force`), Section 7b deletes any `privateDnsZoneGroup` on the existing PE whose `privateDnsZoneId` no longer matches the resolved canonical zone, so Bicep can recreate it. Without it, the script fails fast with instructions. See "Deployment lessons encoded". |

## Outputs

Written to `<script-dir>/.outputs.json` so subsequent scripts can read:

```json
{
  "postgresqlServerName":  "tiqpg66lb",
  "postgresqlServerFqdn":  "tiqpg66lb.postgres.database.azure.com",
  "postgresqlPrivateFqdn": "tiqpg66lb.privatelink.postgres.database.azure.com",
  "postgresqlPrivateIp":   "10.0.4.5",
  "deployerEntraUpn":      "anildwa@example.onmicrosoft.com",
  "tenantId":              "150305b3-cc4b-46dd-9912-425678db1498"
}
```

`02-backend/deploy.ps1` reads `postgresqlServerFqdn` (or
`postgresqlPrivateFqdn` for PE deployments). `04-data-loading/deploy.ps1`
reads all four FQDN-related values plus `deployerEntraUpn`.

## Deployment lessons encoded

- **AGE preload + restart**: After applying the
  `shared_preload_libraries=age` server parameter, this script polls
  `az postgres flexible-server parameter list --query "[?isConfigPendingRestart]"`
  and issues `az postgres flexible-server restart` if anything is
  pending. AGE is unusable until that restart completes (every
  `cypher()` call fails with `unhandled cypher(cstring) function call`).
- **Serialization on the PG control plane**: PG flex allows only one
  data-plane op at a time. The Bicep template wires `server →
  azureExtensions → sharedPreloadLibraries → entraAdministrator →
  firewallRules` via `dependsOn` to avoid
  `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible`.
- **UAMI as PG role — control plane only**: We deliberately use
  `az postgres flexible-server microsoft-entra-admin create
  --type ServicePrincipal` rather than connecting via SQL. The trade-off
  is broader privileges (PG admin instead of narrow schema grants); the
  per-schema narrowing happens in 04-data-loading once an Entra token
  works. The display-name-equals-UAMI-name rule is **mandatory**.
- **Private DNS zone group is immutable — self-heal on redeploy**
  *(added 2026-05-22)*. Azure rejects in-place mutation of
  `privateDnsZoneConfigs[*].properties.privateDnsZoneId` with
  `UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed`. This
  surfaces when the discover-and-reuse logic in Section 6b lands on a
  canonical zone in the shared network RG, but the PE's existing
  `default` zone group was wired (by a pre-fix deploy) to a duplicate
  zone in the local RG. Section 6c detects the mismatch read-only;
  Section 7b deletes the stale zone group when `-FixStaleDnsZoneGroup`
  (or `-Force`) is set, then Bicep recreates it pointing at the
  canonical zone. Section 7c best-effort deletes the orphan duplicate
  zone only when it has zero VNet links AND at most one record set (the
  SOA); anything else is left for a manual cleanup hint. Without the
  switch, the script fails fast with rerun instructions instead of
  letting Bicep error out half-way.

## Re-running

This script must be **idempotent**. Re-running against an existing
server should:

1. No-op the server create (Bicep handles).
2. Re-apply server parameters and restart only if `isConfigPendingRestart` is true.
3. Re-add the deployer as Entra admin only when not already present.
4. Re-add UAMIs only when their `objectId` is not in the admin list.
5. Refresh firewall rules.
6. Re-emit `.outputs.json` with the latest values.

## To be implemented in this folder

```
01-postgresql/
├── README.md         (this file)
├── deploy.ps1        TODO — invokes az + dot-sources ../shared/common.ps1
├── infra/
│   ├── main.bicep    TODO — server + extensions + Entra admin + PE
│   └── main.parameters.json  TODO — defaults for the above
└── .outputs.json     produced at runtime
```

Reuse `talent_infra_v2/infra/modules/postgresql-flexible-server.bicep`
and `talent_infra_v2/infra/modules/private-endpoint.bicep` as-is where
possible; do not modify them.
