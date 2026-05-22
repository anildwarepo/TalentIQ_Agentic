---
name: "azure-private-dns-discover-reuse"
description: "Before a per-component Bicep module creates a privatelink.<service>.* Private DNS zone for a new Private Endpoint, discover whether a zone of that name is already linked to the target VNet — or exists unlinked anywhere in the subscription — and reuse it. Prevents the BadRequest 'overlapping namespaces' failure that hits every fresh deploy in shared-tenant subs where a central network team owns the canonical zone."
domain: "deployment"
confidence: "low"
source: "earned"
---

## Context

Use this skill whenever a Bicep module (or `azd` infra layer) provisions a Private Endpoint for an Azure PaaS service AND the deploy target is a shared subscription where Private DNS zones may already exist (typical: a central network team owns `privatelink.postgres.database.azure.com`, `privatelink.documents.azure.com`, etc. in an RG like `vnet` and links them to a single hub VNet).

Azure enforces **at most one Private DNS zone per namespace per VNet** via `Microsoft.Network/privateDnsZones/virtualNetworkLinks`. Attempting to link a *second* zone with the same DNS name to the *same* VNet — even from a different resource group, even with the original link untouched — is rejected at create time with:

```
BadRequest — A virtual network cannot be linked to multiple zones with overlapping
namespaces. You tried to link virtual network with
'privatelink.<service>.database.azure.com' and 'privatelink.<service>.database.azure.com' zones.
```

The error is the same whether the conflict comes from creating a new zone in the deployment RG or from creating a duplicate link against an existing zone elsewhere. The only resilient fix is to *discover* whichever zone is already linked and reuse it.

**Trigger conditions:**
- You are adding a new Private Endpoint to a per-component module.
- The deploy target shares its VNet with other components or other teams.
- The error message above appeared on a previous deploy attempt.
- The user/operator says "reuse existing private DNS" or "this should first check of existing private links".

**Out of scope:**
- Modules that don't create a Private Endpoint.
- Single-tenant subs where the deploying RG owns the only zone and only VNet.
- Test environments where deleting the zone is cheap.

## Patterns

### Pattern 1 — Two PowerShell helpers (canonical, copy-paste reusable)

Live in `talent_infra_modules/shared/common.ps1`. Both use RP-specific `az network private-dns` calls (same RBAC posture as `Test-VnetExists` / `Test-VnetSubnetExists` — works in shared subs where the operator only has `Microsoft.Network/privateDnsZones/read` scoped to the network team's RG). Both return `$null` on miss or RBAC fail — never `throw`.

```powershell
function Get-LinkedPrivateDnsZoneId {
    # Return zone ID of any zone named -ZoneName that is already linked
    # to -VnetId (case-insensitive). $null if no such linked zone exists.
    param(
        [Parameter(Mandatory)][string]$SubscriptionId,
        [Parameter(Mandatory)][string]$ZoneName,
        [Parameter(Mandatory)][string]$VnetId
    )
    # List sub zones → filter by exact name → per-zone list vnet links
    # → return first whose virtualNetwork.id -ieq $VnetId.
}

function Get-PrivateDnsZoneIdByName {
    # Return resource ID of the first zone named -ZoneName anywhere
    # in the subscription. $null if none exists.
    param(
        [Parameter(Mandatory)][string]$SubscriptionId,
        [Parameter(Mandatory)][string]$ZoneName
    )
}
```

### Pattern 2 — Deploy-script wiring (canonical placement: between prereq check and confirm)

```powershell
# 6b. Auto-discover existing Private DNS zone (when PE enabled and no override)
$ExistingDnsZoneLinked = $true   # default matches Bicep — skip link creation
if ($EnablePrivateEndpoint -and [string]::IsNullOrEmpty($ExistingDnsZoneId)) {
    Write-Step "Discovering existing 'privatelink.<service>.*' Private DNS zone"
    $vnetId = "/subscriptions/$SubscriptionId/resourceGroups/$VnetResourceGroup/providers/Microsoft.Network/virtualNetworks/$VnetName"

    $linkedZoneId = Get-LinkedPrivateDnsZoneId `
        -SubscriptionId $SubscriptionId `
        -ZoneName 'privatelink.<service>.*' `
        -VnetId $vnetId
    if (-not [string]::IsNullOrEmpty($linkedZoneId)) {
        $ExistingDnsZoneId = $linkedZoneId
        $ExistingDnsZoneLinked = $true            # skip link creation
        Write-Success "Reusing existing linked Private DNS zone: $linkedZoneId"
    } else {
        $unlinkedZoneId = Get-PrivateDnsZoneIdByName `
            -SubscriptionId $SubscriptionId `
            -ZoneName 'privatelink.<service>.*'
        if (-not [string]::IsNullOrEmpty($unlinkedZoneId)) {
            $ExistingDnsZoneId = $unlinkedZoneId
            $ExistingDnsZoneLinked = $false       # Bicep will create the link
            Write-Success "Reusing existing Private DNS zone (no current VNet link): $unlinkedZoneId"
        } else {
            Write-Info "No existing zone found — Bicep will create one and link it."
        }
    }
}

# … later in $overrides …
if (-not [string]::IsNullOrEmpty($ExistingDnsZoneId)) {
    $overrides += "existingPrivateDnsZoneId=$ExistingDnsZoneId"
    $overrides += "existingPrivateDnsZoneLinked=$($ExistingDnsZoneLinked.ToString().ToLower())"
}
```

Preserve any explicit `XXX_DNS_ZONE_ID` env-var override as the highest-priority signal — discovery only runs when `$ExistingDnsZoneId` is still empty after the env-var read.

### Pattern 3 — Bicep contract (PE module params)

```bicep
@description('Optional resource ID of an existing privatelink.<service>.* DNS zone. Empty = create new + link.')
param existingPrivateDnsZoneId string = ''

@description('Whether the existing zone is already linked to the target VNet. true=skip link creation; false=create link in the existing zone\'s RG. Ignored when existingPrivateDnsZoneId is empty. Default true (backward compatible).')
param existingPrivateDnsZoneLinked bool = true

var useExistingDnsZone = !empty(existingPrivateDnsZoneId)

// /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/privateDnsZones/{name}
var existingZoneRg = useExistingDnsZone ? split(existingPrivateDnsZoneId, '/')[4] : ''
var existingZoneName = useExistingDnsZone ? last(split(existingPrivateDnsZoneId, '/')) : ''

resource privateDnsZone '...' = if (!useExistingDnsZone) { ... }
resource privateDnsZoneVnetLink '...' = if (!useExistingDnsZone) { ... }

// Cross-RG link when reusing an unlinked existing zone:
module existingZoneVnetLink './private-dns-zone-vnet-link.bicep' = if (useExistingDnsZone && !existingPrivateDnsZoneLinked) {
  name: 'link-${vnetName}-to-${existingZoneName}'
  scope: resourceGroup(existingZoneRg)
  params: { privateDnsZoneName: existingZoneName; vnetId: vnetId; vnetName: vnetName; tags: tags }
}

// PE DNS zone group always uses the resolved ID:
var resolvedDnsZoneId = useExistingDnsZone ? existingPrivateDnsZoneId : privateDnsZone.id
```

### Pattern 4 — Nested module file (one file, reusable by every PE module)

Reference: `talent_infra_modules/01-postgresql/infra/modules/private-dns-zone-vnet-link.bicep`. Single-purpose: takes a zone name + VNet ID + VNet name + tags, references the zone via `existing`, creates one `virtualNetworkLinks` child. Caller controls scope by deploying the module at `scope: resourceGroup(<zone-rg>)`. Idempotent (re-running with the same VNet is a no-op).

## Examples

**Done — reference implementation:** `talent_infra_modules/01-postgresql/`
- Helpers: `talent_infra_modules/shared/common.ps1` (`Get-LinkedPrivateDnsZoneId`, `Get-PrivateDnsZoneIdByName`)
- Deploy wiring: `talent_infra_modules/01-postgresql/deploy.ps1` Section 6b
- Bicep params + variables: `talent_infra_modules/01-postgresql/infra/main.bicep`, `infra/modules/private-endpoint.bicep`
- Nested cross-RG link module: `talent_infra_modules/01-postgresql/infra/modules/private-dns-zone-vnet-link.bicep`
- Validated: `mcp_bicep_build_bicep` → zero diagnostics. Live discovery confirmed against Anil's sub (linked zone found in RG `vnet` for `vnet-westus`).

**Apply this skill when adding PEs for:**
| Service                       | Zone name |
|-------------------------------|-----------|
| Cosmos DB SQL API             | `privatelink.documents.azure.com` |
| Azure AI Foundry / CogServices| `privatelink.cognitiveservices.azure.com` |
| Azure OpenAI sub-resource     | `privatelink.openai.azure.com` |
| Key Vault                     | `privatelink.vaultcore.azure.net` |
| ACR Premium                   | `privatelink.azurecr.io` |
| Container Apps Env (internal) | `privatelink.<region>.azurecontainerapps.io` |
| Storage Blob                  | `privatelink.blob.core.windows.net` |
| Storage File                  | `privatelink.file.core.windows.net` |
| Service Bus                   | `privatelink.servicebus.windows.net` |
| Event Hubs                    | `privatelink.servicebus.windows.net` (shares with Service Bus — extra care: ONE zone covers both) |

## Anti-Patterns

**Do NOT use `az resource show` to check for the zone.** It goes through the generic `Microsoft.Resources/resources` endpoint and requires broader RBAC than the operator typically has on a network team's RG. Use `az network private-dns zone list` + `az network private-dns link vnet list` (which are scoped to `Microsoft.Network/privateDnsZones/read`). Same rule of thumb as `Test-VnetExists` vs `Test-ResourceExists` (see `bishop/history.md` 2026-05-22 entry on asymmetric RBAC).

**Do NOT `throw` from the discovery helpers.** Return `$null` on miss or RBAC failure. The deploy script decides whether to fall through to Bicep's "create new" path or surface a hard error. Throwing forces the operator into env-var override mode just to bypass discovery — which defeats the point.

**Do NOT prompt the user interactively for a zone ID.** Discovery is automatic; the env-var override (`POSTGRESQL_DNS_ZONE_ID`, `COSMOS_DNS_ZONE_ID`, …) is the manual escape hatch. Interactive prompts break CI/CD and azd hooks.

**Do NOT set `existingPrivateDnsZoneLinked: true` when the zone is NOT actually linked.** The PE's DNS zone group will be created against a zone whose A-records aren't resolvable from the VNet — the connection string will resolve to the public IP and silently bypass the PE. If discovery cannot verify the link, set `false` and let Bicep create the link.

**Do NOT pick "the first zone of that name anywhere" as a hard rule.** When multiple zones share the name in different RGs (e.g., one in `vnet` and a leftover in `rg-kg4-westus`), the linked check ALWAYS wins — `Get-LinkedPrivateDnsZoneId` is the authoritative selector; `Get-PrivateDnsZoneIdByName` is only the fallback when nothing is linked.

**Do NOT modify `talent_infra_v2/`** when applying this skill to a per-component module under `talent_infra_modules/`. The v2 folder is the working reference; per-component re-implementations carry the discovery pattern in their own self-contained copies.

**Do NOT add the discovery code if you also remove the env-var override.** The `XXX_DNS_ZONE_ID` env var is the highest-priority signal — operators rely on it to force-pin a zone for special cases (e.g., cross-tenant scenarios where the linked-zone API call returns nothing).
