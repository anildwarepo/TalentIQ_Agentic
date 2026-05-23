<#
.SYNOPSIS
    Deploy a single Azure Database for PostgreSQL Flexible Server with AGE,
    pgvector, pg_trgm, pg_diskann, Entra ID authentication, and an optional
    Private Endpoint into an existing VNet.

.DESCRIPTION
    Idempotent orchestrator for talent_infra_modules/01-postgresql/. Reads
    parameters from script args -> env vars -> prompt -> bicep defaults
    (see talent_infra_modules/shared/common.ps1::Get-ParameterValue),
    deploys infra/main.bicep, applies the deployment lessons from
    /memories/repo/talentiq-azd-deploy.md, and writes .outputs.json next
    to the script so downstream components (02-backend, 04-data-loading)
    can consume the server FQDN, tenant, and deployer UPN.

    Hard rules baked in:
      * AGE preload + restart  -  polls isConfigPendingRestart and issues
        `az postgres flexible-server restart` when any param is pending.
        Without this, every cypher() call fails with
        `unhandled cypher(cstring) function call`.
      * Entra admin registration is CONTROL-PLANE ONLY (`az postgres
        flexible-server microsoft-entra-admin create`)  -  never via SQL.
        Avoids the ISP-blocks-5432 footgun on residential networks.
      * The deployer is always registered as Type=User; UAMIs are
        registered as Type=ServicePrincipal with display-name == UAMI
        name (that's the PG username the container presents).
      * Bicep is invoked with entraAdminObjectId='' to skip the
        administrators child resource  -  re-applying it during an idempotent
        redeploy triggers AadAuthOperationCannotBePerformedWhenServer-
        IsNotAccessible.

.PARAMETER UamiPrincipalIds
    JSON list of UAMIs to register as PG Entra ServicePrincipal admins, e.g.
        '[{"name":"backend-app-identity","objectId":"abc-..."}]'
    The `name` becomes the PG username the container will present and MUST
    match the UAMI's resource name exactly.

.EXAMPLE
    # Preferred: prompt securely  -  nothing lands in shell history, scripts, or
    # the GitGuardian feed. Get-ParameterValue in shared/common.ps1 also falls
    # back to Read-Host when -AdminPassword is omitted, so you can drop the
    # parameter entirely and just answer the prompt.
    pwsh ./deploy.ps1 `
        -SubscriptionId e4718866-... `
        -ResourceGroup rg-talent-modular `
        -Location westus `
        -AdminPassword (Read-Host -AsSecureString -Prompt 'Postgres admin password') `
        -VnetName vnet-talent-shared `
        -VnetResourceGroup rg-network `
        -Force

    # CI / automated runs: source the password from a secret manager (Key Vault,
    # GitHub Actions secret, AZ DevOps variable group) and convert to SecureString
    # just before invocation. NEVER hardcode a literal password in this file or
    # any committed script  -  use the placeholder pattern below only as a template:
    #   -AdminPassword (ConvertTo-SecureString '<your-strong-password>' -AsPlainText -Force)

.NOTES
    Requires Azure CLI 2.53+, Bicep CLI, Contributor on -ResourceGroup,
    and (when registering UAMIs)
    Microsoft.DBforPostgreSQL/flexibleServers/administrators/write.
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$Location = "westus",
    [string]$ServerName,
    [string]$AdminLogin = "pgadmin",
    [SecureString]$AdminPassword,
    [string]$PostgresqlVersion = "16",
    # SKU defaults mirror talent_infra_v2/infra/main.parameters.json  -  D-series
    # is the only D/E size that is actually GeneralPurpose; Standard_B* sizes
    # are Burstable tier and produce ServerEditionIncompatibleWithSkuSize when
    # paired with -SkuTier GeneralPurpose. See decision
    # 'postgres-sku-parity' (2026-05-21).
    [string]$SkuName = "Standard_D4ds_v5",
    [string]$SkuTier = "GeneralPurpose",
    [int]$StorageSizeGB = 32,
    [bool]$EnablePrivateEndpoint = $true,
    [string]$VnetResourceGroup,
    [string]$VnetName,
    [string]$PeSubnetName = "pe-subnet",
    [string]$ExistingDnsZoneId,
    [string]$ClientIpAddress,
    [string]$UamiPrincipalIds,
    [switch]$EntraOnly,
    # Self-heal flag for the
    #   UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed
    # redeploy failure that surfaces when the PE already has a
    # privateDnsZoneGroup wired to a zone that no longer matches the
    # resolved $ExistingDnsZoneId (typical after the discover-and-reuse
    # logic in Section 6b lands on top of artifacts from a pre-fix
    # deploy). When set (or -Force is set), Section 7b deletes the
    # stale zone group so Section 8's Bicep can recreate it cleanly.
    # When NOT set, Section 7b refuses the destructive cleanup and
    # exits with instructions. See Section 6c for detection logic.
    [switch]$FixStaleDnsZoneGroup,
    [switch]$Force
)

# Do NOT set $ErrorActionPreference='Stop' globally  -  Invoke-Native in
# common.ps1 manages it per-call so `az` non-zero exits don't blow up the
# script before we can inspect $LASTEXITCODE.

$scriptDir = $PSScriptRoot
. (Join-Path $scriptDir "..\shared\common.ps1")

Write-Host ""
Write-Host "================================================================" -ForegroundColor DarkCyan
Write-Host " talent_infra_modules / 01-postgresql / deploy.ps1" -ForegroundColor DarkCyan
Write-Host "================================================================" -ForegroundColor DarkCyan

# --------------------------------------------------------------------------
# 1. Az sign-in + subscription
# --------------------------------------------------------------------------
$account = Test-AzLoggedIn

# --------------------------------------------------------------------------
# 2. Parameter resolution  -  script arg -> env var -> prompt -> default
# --------------------------------------------------------------------------
$SubscriptionId = Get-ParameterValue -Name "Subscription ID" `
    -Value $SubscriptionId -EnvVar "AZURE_SUBSCRIPTION_ID" -Default $account.id
$ResourceGroup = Get-ParameterValue -Name "Resource group" `
    -Value $ResourceGroup -EnvVar "AZURE_RESOURCE_GROUP"
$Location = Get-ParameterValue -Name "Location" `
    -Value $Location -EnvVar "AZURE_LOCATION" -Default "westus"
$AdminLogin = Get-ParameterValue -Name "PG admin login" `
    -Value $AdminLogin -EnvVar "POSTGRESQL_ADMIN_LOGIN" -Default "pgadmin"
$PostgresqlVersion = Get-ParameterValue -Name "PostgreSQL version" `
    -Value $PostgresqlVersion -EnvVar "POSTGRESQL_VERSION" -Default "16"
# SKU defaults mirror talent_infra_v2/infra/main.parameters.json. Standard_D4ds_v5
# is GeneralPurpose; Standard_B* sizes are Burstable and would require
# -SkuTier Burstable. Env-var overrides still win.
$SkuName = Get-ParameterValue -Name "SKU name" `
    -Value $SkuName -EnvVar "POSTGRESQL_SKU_NAME" -Default "Standard_D4ds_v5"
$SkuTier = Get-ParameterValue -Name "SKU tier" `
    -Value $SkuTier -EnvVar "POSTGRESQL_SKU_TIER" -Default "GeneralPurpose"

# Numeric param: env var carries a string, force conversion.
$storageEnv = [Environment]::GetEnvironmentVariable("POSTGRESQL_STORAGE_GB")
if (-not [string]::IsNullOrEmpty($storageEnv)) { $StorageSizeGB = [int]$storageEnv }

# Bool param: env var with 'true' / 'false' literal.
$peEnv = [Environment]::GetEnvironmentVariable("POSTGRESQL_ENABLE_PE")
if (-not [string]::IsNullOrEmpty($peEnv)) {
    $EnablePrivateEndpoint = ($peEnv -match '^(true|1|yes)$')
}

# Secure password  -  never logged, never default.
if ($null -eq $AdminPassword -or $AdminPassword.Length -eq 0) {
    $AdminPassword = Get-ParameterValue -Name "PG admin password" `
        -EnvVar "POSTGRESQL_ADMIN_PASSWORD" -Secure
}

# VNet wiring  -  only required when PE is enabled.
if ($EnablePrivateEndpoint) {
    if ([string]::IsNullOrEmpty($VnetResourceGroup)) {
        $VnetResourceGroup = Get-ParameterValue -Name "VNet resource group" `
            -EnvVar "AZURE_VNET_RESOURCE_GROUP" -Default $ResourceGroup
    }
    if ([string]::IsNullOrEmpty($VnetName)) {
        $VnetName = Get-ParameterValue -Name "VNet name" `
            -Value $VnetName -EnvVar "AZURE_VNET_NAME"
    }
    # -AlwaysPrompt: subnet names are environment-specific (RG/VNet may not
    # contain "pe-subnet"). The param-block default would otherwise short-
    # circuit the prompt and bind us to a subnet that does not exist.
    $PeSubnetName = Get-ParameterValue -Name "PE subnet name" `
        -Value $PeSubnetName -EnvVar "AZURE_PE_SUBNET_NAME" -Default "pe-subnet" -AlwaysPrompt
} else {
    $VnetResourceGroup = ""
    $VnetName = ""
}

# Existing DNS zone is optional.
if ([string]::IsNullOrEmpty($ExistingDnsZoneId)) {
    $ExistingDnsZoneId = [Environment]::GetEnvironmentVariable("POSTGRESQL_DNS_ZONE_ID")
    if ($null -eq $ExistingDnsZoneId) { $ExistingDnsZoneId = "" }
}

# UAMI list (JSON)  -  env var override.
if ([string]::IsNullOrEmpty($UamiPrincipalIds)) {
    $UamiPrincipalIds = [Environment]::GetEnvironmentVariable("POSTGRESQL_UAMI_PRINCIPALS")
    if ($null -eq $UamiPrincipalIds) { $UamiPrincipalIds = "" }
}

# 3. Set subscription
Test-AzSubscription -SubscriptionId $SubscriptionId

# --------------------------------------------------------------------------
# 4. Auto-detect client IP if not supplied
# --------------------------------------------------------------------------
if ([string]::IsNullOrEmpty($ClientIpAddress)) {
    $ClientIpAddress = [Environment]::GetEnvironmentVariable("POSTGRESQL_CLIENT_IP")
}
if ([string]::IsNullOrEmpty($ClientIpAddress)) {
    Write-Step "Auto-detecting public IP from api.ipify.org"
    try {
        $detected = (Invoke-WebRequest -Uri 'https://api.ipify.org' `
            -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop).Content.Trim()
        if ($detected -match '^\d{1,3}(\.\d{1,3}){3}$') {
            $ClientIpAddress = $detected
            Write-Success "Detected client IP: $ClientIpAddress"
        } else {
            Write-Warn "api.ipify.org returned unexpected value: '$detected'  -  skipping client firewall rule"
            $ClientIpAddress = ""
        }
    } catch {
        Write-Warn "Could not auto-detect public IP ($($_.Exception.Message))  -  skipping client firewall rule"
        $ClientIpAddress = ""
    }
}

# --------------------------------------------------------------------------
# 5. Generate a deterministic server name if none supplied
# --------------------------------------------------------------------------
if ([string]::IsNullOrEmpty($ServerName)) {
    $ServerName = [Environment]::GetEnvironmentVariable("POSTGRESQL_SERVER_NAME")
}
if ([string]::IsNullOrEmpty($ServerName)) {
    $source = "$SubscriptionId|$ResourceGroup|$Location"
    $bytes  = [System.Text.Encoding]::UTF8.GetBytes($source)
    $sha    = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }
    $hash5 = -join (
        [BitConverter]::ToString($hashBytes).Replace('-','').ToLower().ToCharArray()[0..4]
    )
    $ServerName = "tiqpg$hash5"
    Write-Info "Auto-generated server name: $ServerName (deterministic for this RG + location)"
}

# --------------------------------------------------------------------------
# 6. Prerequisite checks
# --------------------------------------------------------------------------
$checks = @(@{ Type='rg'; Name=$ResourceGroup })
if ($EnablePrivateEndpoint) {
    $checks += @{ Type='vnet';   Name=$VnetName }
    $checks += @{ Type='subnet'; Vnet=$VnetName; Name=$PeSubnetName }
}
Assert-PrerequisitesExist `
    -ResourceGroup $ResourceGroup `
    -VnetResourceGroup $VnetResourceGroup `
    -Checks $checks

# --------------------------------------------------------------------------
# 6b. Auto-discover existing 'privatelink.postgres.database.azure.com' zone
#
# Azure rejects "a virtual network cannot be linked to multiple zones
# with overlapping namespaces". If a zone of that name is already linked
# to the target VNet (typical in shared-tenant subs where a network team
# owns the zone), we must REUSE it instead of creating a duplicate. We
# only discover when (a) PE is enabled, (b) the operator did NOT pass an
# explicit -ExistingDnsZoneId or POSTGRESQL_DNS_ZONE_ID override  -  those
# are trusted as-is.
# --------------------------------------------------------------------------
$ExistingDnsZoneLinked = $true   # default matches Bicep  -  skip link creation
if ($EnablePrivateEndpoint -and [string]::IsNullOrEmpty($ExistingDnsZoneId)) {
    Write-Step "Discovering existing 'privatelink.postgres.database.azure.com' Private DNS zone"

    $vnetId = "/subscriptions/$SubscriptionId/resourceGroups/$VnetResourceGroup/providers/Microsoft.Network/virtualNetworks/$VnetName"

    $linkedZoneId = Get-LinkedPrivateDnsZoneId `
        -SubscriptionId $SubscriptionId `
        -ZoneName 'privatelink.postgres.database.azure.com' `
        -VnetId $vnetId

    if (-not [string]::IsNullOrEmpty($linkedZoneId)) {
        $ExistingDnsZoneId = $linkedZoneId
        $ExistingDnsZoneLinked = $true
        Write-Success "Reusing existing linked Private DNS zone: $linkedZoneId"
    } else {
        $unlinkedZoneId = Get-PrivateDnsZoneIdByName `
            -SubscriptionId $SubscriptionId `
            -ZoneName 'privatelink.postgres.database.azure.com'
        if (-not [string]::IsNullOrEmpty($unlinkedZoneId)) {
            $ExistingDnsZoneId = $unlinkedZoneId
            $ExistingDnsZoneLinked = $false
            Write-Success "Reusing existing Private DNS zone (no current VNet link): $unlinkedZoneId"
            Write-Info "Bicep will create the VNet link in the zone's resource group."
        } else {
            Write-Info "No existing zone found  -  Bicep will create one and link it."
        }
    }
}

# --------------------------------------------------------------------------
# 6c. Detect stale Private DNS zone group on existing PE
#
# Azure rejects in-place mutation of
#   privateDnsZoneConfigs[*].properties.privateDnsZoneId
# with UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed.
# This surfaces when a previous (pre-discover-and-reuse) deploy wired
# the PE's 'default' zone group to a zone in $ResourceGroup, and the
# current run resolves a different canonical zone in 6b. The only fix
# is to delete the stale zone group so Section 8's Bicep recreates it.
# We DETECT here (read-only) and stash $script:StaleZoneGroup for
# Section 7's plan summary and Section 7b's repair step. Skipped if
# PE is disabled, no zone was resolved, or the PE doesn't exist yet
# (first run is a no-op).
# --------------------------------------------------------------------------
$StaleZoneGroup = $null            # name of stale zone group to delete (e.g. 'default')
$StaleZoneGroupOldZoneId = $null   # zone ID it currently (wrongly) points at
$peName = "${ServerName}-pe"

if ($EnablePrivateEndpoint -and -not [string]::IsNullOrEmpty($ExistingDnsZoneId)) {
    Write-Step "Checking for stale Private DNS zone group on PE '$peName'"

    $peJson = Invoke-Native {
        az network private-endpoint show -g $ResourceGroup -n $peName -o json 2>$null
    }
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($peJson)) {
        $zgJson = Invoke-Native {
            az network private-endpoint dns-zone-group list `
                -g $ResourceGroup --endpoint-name $peName -o json 2>$null
        }
        $zgList = @()
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($zgJson)) {
            try { $zgList = @($zgJson | ConvertFrom-Json) } catch { $zgList = @() }
        }
        foreach ($zg in $zgList) {
            foreach ($cfg in @($zg.privateDnsZoneConfigs)) {
                $currentZoneId = [string]$cfg.privateDnsZoneId
                if (-not ($currentZoneId -ieq $ExistingDnsZoneId)) {
                    $StaleZoneGroup = [string]$zg.name
                    $StaleZoneGroupOldZoneId = $currentZoneId
                    Write-Warn "Stale zone group '$($zg.name)' points at: $currentZoneId"
                    Write-Warn "Resolved canonical zone is        : $ExistingDnsZoneId"
                    Write-Warn "Azure forbids in-place repointing  -  zone group must be deleted and recreated."
                    break
                }
            }
            if ($null -ne $StaleZoneGroup) { break }
        }
        if ($null -eq $StaleZoneGroup) {
            Write-Success "No stale zone group detected on PE '$peName'."
        }
    } else {
        Write-Info "PE '$peName' not present yet (first run)  -  nothing to repair."
    }
}

# --------------------------------------------------------------------------
# 7. Confirm
# --------------------------------------------------------------------------
Write-Host ""
Write-Host "  Deployment plan" -ForegroundColor Cyan
Write-Host "  ---------------" -ForegroundColor Cyan
Write-Host ("    Subscription          : {0}" -f $SubscriptionId)
Write-Host ("    Resource group        : {0}" -f $ResourceGroup)
Write-Host ("    Location              : {0}" -f $Location)
Write-Host ("    PostgreSQL server     : {0}" -f $ServerName)
Write-Host ("    PostgreSQL version    : {0}" -f $PostgresqlVersion)
Write-Host ("    SKU                   : {0} ({1})" -f $SkuName, $SkuTier)
Write-Host ("    Storage               : {0} GB" -f $StorageSizeGB)
Write-Host ("    Admin login           : {0}" -f $AdminLogin)
Write-Host ("    Password auth         : {0}" -f $(if ($EntraOnly) { 'DISABLED (Entra-only)' } else { 'Enabled' }))
Write-Host ("    Private Endpoint      : {0}" -f $EnablePrivateEndpoint)
if ($EnablePrivateEndpoint) {
    Write-Host ("    VNet                  : {0}/{1}" -f $VnetResourceGroup, $VnetName)
    Write-Host ("    PE subnet             : {0}" -f $PeSubnetName)
    Write-Host ("    Existing DNS zone ID  : {0}" -f $(if ([string]::IsNullOrEmpty($ExistingDnsZoneId)) { '(create new)' } else { $ExistingDnsZoneId }))
    if (-not [string]::IsNullOrEmpty($ExistingDnsZoneId)) {
        Write-Host ("    DNS zone link status  : {0}" -f $(if ($ExistingDnsZoneLinked) { 'already linked (no link will be created)' } else { 'unlinked (Bicep will create the VNet link)' }))
    }
    if ($null -ne $StaleZoneGroup) {
        $gate = if ($FixStaleDnsZoneGroup -or $Force) { 'auto-approved (-FixStaleDnsZoneGroup or -Force)' } else { 'BLOCKED  -  rerun with -FixStaleDnsZoneGroup' }
        Write-Host ("    Stale PE zone group   : '{0}' WILL BE DELETED [{1}]" -f $StaleZoneGroup, $gate) -ForegroundColor Yellow
        Write-Host ("      currently points at : {0}" -f $StaleZoneGroupOldZoneId) -ForegroundColor DarkYellow
    }
}
Write-Host ("    Client IP firewall    : {0}" -f $(if ([string]::IsNullOrEmpty($ClientIpAddress)) { '(none)' } else { $ClientIpAddress }))
Write-Host ("    Deployer admin (Entra): {0}" -f $account.user.name)
$uamiList = @()
if (-not [string]::IsNullOrEmpty($UamiPrincipalIds)) {
    try { $uamiList = @($UamiPrincipalIds | ConvertFrom-Json) } catch {
        Write-Fail "Could not parse -UamiPrincipalIds as JSON. Expected: '[{`"name`":...,`"objectId`":...}]'"
        exit 1
    }
}
Write-Host ("    UAMIs to register     : {0}" -f $(if ($uamiList.Count -eq 0) { '(none)' } else { ($uamiList | ForEach-Object { $_.name }) -join ', ' }))
Write-Host ""

if (-not (Confirm-Action -Message "Proceed with deployment?" -Force:$Force)) {
    Write-Warn "Aborted by user."
    exit 1
}

# --------------------------------------------------------------------------
# 7b. Repair stale Private DNS zone group on existing PE
#
# If Section 6c detected a mismatched privateDnsZoneConfig and the
# operator opted in (via -FixStaleDnsZoneGroup or -Force), delete the
# offending zone group so Section 8's Bicep recreates it pointing at
# the canonical zone. Without this, az deployment group create fails
# with UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed.
# --------------------------------------------------------------------------
if ($null -ne $StaleZoneGroup) {
    if (-not ($FixStaleDnsZoneGroup -or $Force)) {
        Write-Fail "Stale Private DNS zone group '$StaleZoneGroup' on PE '$peName' would block this deploy."
        Write-Info  "Azure forbids in-place mutation of privateDnsZoneConfigs[*].privateDnsZoneId."
        Write-Info  "Rerun with -FixStaleDnsZoneGroup (or -Force) to delete and recreate it."
        exit 1
    }

    Write-Step "Deleting stale Private DNS zone group '$StaleZoneGroup' on PE '$peName'"
    $delOut = Invoke-Native {
        az network private-endpoint dns-zone-group delete `
            -g $ResourceGroup `
            --endpoint-name $peName `
            -n $StaleZoneGroup `
            --output none 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Could not delete stale zone group (exit $LASTEXITCODE):"
        $delOut | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkRed }
        exit 1
    }
    Write-Success "Stale zone group deleted. Bicep will recreate it pointing at the canonical zone."
}

# --------------------------------------------------------------------------
# 7c. Best-effort cleanup of the orphan Private DNS zone (when safe)
#
# When the stale zone group pointed at a zone that lives in
# $ResourceGroup (i.e. NOT the canonical zone in the shared network RG),
# that zone is almost certainly an orphan left over from the pre-fix
# deploy. We offer to delete it ONLY when it is provably safe:
#   * It lives in $ResourceGroup (separate from canonical).
#   * It has zero VNet links (canonical zone owns linking).
#   * It has at most one record set left (just the SOA after the
#     zone-group delete in 7b reclaimed the A record).
# Anything else -> log a manual-cleanup hint and move on. Failure here
# is non-fatal  -  Section 8's Bicep does not depend on this.
# --------------------------------------------------------------------------
if ($null -ne $StaleZoneGroup -and ($FixStaleDnsZoneGroup -or $Force) -and -not [string]::IsNullOrEmpty($StaleZoneGroupOldZoneId)) {
    $segments = $StaleZoneGroupOldZoneId.Split('/')
    if ($segments.Length -ge 9) {
        $orphanRg   = $segments[4]
        $orphanName = $segments[8]
        if ($orphanRg -ieq $ResourceGroup) {
            Write-Step "Checking orphan Private DNS zone '$orphanName' in '$orphanRg'"
            $zoneJson = Invoke-Native {
                az network private-dns zone show -g $orphanRg -n $orphanName -o json 2>$null
            }
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($zoneJson)) {
                # Authoritative record-set check via `record-set list`  - 
                # the `numberOfRecordSets` / `numberOfVirtualNetworkLinks`
                # counters on `zone show` (and the listing returned by
                # `link vnet list`) can lag the Azure RP's actual state
                # by several minutes after a link delete. Trusting them
                # for a delete decision led to a CannotDeleteResource
                # error in the prior run because a freshly orphaned link
                # was still held by the RP even though both list endpoints
                # reported 0. We therefore:
                #   1. Guard on real record-set contents (only SOA is OK).
                #   2. Loop any visible VNet links and delete each by
                #      name (delete is idempotent and authoritative).
                #   3. Attempt the zone delete unconditionally  -  if Azure
                #      still holds nested links we log a manual-cleanup
                #      hint and move on (non-fatal; Bicep does not depend
                #      on this cleanup).
                $rsListJson = Invoke-Native {
                    az network private-dns record-set list `
                        -g $orphanRg --zone-name $orphanName `
                        --query "[?type!='Microsoft.Network/privateDnsZones/SOA'].{n:name,t:type}" `
                        -o json 2>$null
                }
                $nonSoaRecords = @()
                if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($rsListJson)) {
                    try { $nonSoaRecords = @($rsListJson | ConvertFrom-Json) } catch { $nonSoaRecords = @() }
                }
                if ($nonSoaRecords.Count -gt 0) {
                    Write-Warn "Orphan zone has $($nonSoaRecords.Count) non-SOA record set(s)  -  leaving in place to avoid accidental data loss."
                    Write-Info  "Inspect: az network private-dns record-set list -g $orphanRg --zone-name $orphanName -o table"
                    Write-Info  "Delete manually only if safe: az network private-dns zone delete -g $orphanRg -n $orphanName --yes"
                } else {
                    Write-Step "Orphan zone has only SOA  -  clearing any visible VNet links"
                    $linkListJson = Invoke-Native {
                        az network private-dns link vnet list `
                            -g $orphanRg --zone-name $orphanName `
                            --query "[].name" -o json 2>$null
                    }
                    $linkNames = @()
                    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($linkListJson)) {
                        try { $linkNames = @($linkListJson | ConvertFrom-Json) } catch { $linkNames = @() }
                    }
                    Write-Info "Visible VNet links: $($linkNames.Count) ($(if ($linkNames.Count -gt 0) { $linkNames -join ', ' } else { 'none' }))"
                    foreach ($lname in $linkNames) {
                        Write-Info "  Deleting link '$lname' (idempotent)"
                        Invoke-Native {
                            az network private-dns link vnet delete `
                                -g $orphanRg --zone-name $orphanName `
                                -n $lname --yes --output none 2>$null
                        } | Out-Null
                    }
                    Write-Step "Attempting orphan zone delete"
                    $delZoneOut = Invoke-Native {
                        az network private-dns zone delete `
                            -g $orphanRg -n $orphanName `
                            --yes --output none 2>&1
                    }
                    if ($LASTEXITCODE -eq 0) {
                        Write-Success "Orphan zone '$orphanName' deleted from '$orphanRg'."
                    } else {
                        Write-Warn "Orphan zone delete failed (exit $LASTEXITCODE). Non-fatal  -  Bicep will still succeed."
                        $delZoneOut | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkYellow }
                        Write-Info "Manual cleanup (Azure RP cache can lag  -  retry after a few minutes):"
                        Write-Info "  az network private-dns link vnet list -g $orphanRg --zone-name $orphanName -o table"
                        Write-Info "  # for each link: az network private-dns link vnet delete -g $orphanRg --zone-name $orphanName -n <name> --yes"
                        Write-Info "  az network private-dns zone delete -g $orphanRg -n $orphanName --yes"
                    }
                }
            } else {
                Write-Info "Orphan zone not found (already deleted?)  -  nothing to clean up."
            }
        }
    }
}

# --------------------------------------------------------------------------
# 8. Bicep deploy
# --------------------------------------------------------------------------
$bicepFile  = Join-Path $scriptDir "infra\main.bicep"
$paramsFile = Join-Path $scriptDir "infra\main.parameters.json"

if (-not (Test-Path $bicepFile))  { Write-Fail "Missing $bicepFile";  exit 1 }
if (-not (Test-Path $paramsFile)) { Write-Fail "Missing $paramsFile"; exit 1 }

Write-Step "Deploying Bicep template (this can take 10-15 minutes for a fresh server)"

$plainPw = ConvertFrom-SecureStringPlain -Secure $AdminPassword
$deploymentName = "pg-{0}-{1}" -f $ServerName, (Get-Date -Format 'yyyyMMddHHmmss')

# Build override list. Bools/ints are passed as az CLI string literals.
$overrides = @(
    "serverName=$ServerName",
    "location=$Location",
    "administratorLogin=$AdminLogin",
    "administratorLoginPassword=$plainPw",
    "postgresqlVersion=$PostgresqlVersion",
    "skuName=$SkuName",
    "skuTier=$SkuTier",
    "storageSizeGB=$StorageSizeGB",
    "disablePasswordAuth=$($EntraOnly.IsPresent.ToString().ToLower())",
    "enablePrivateEndpoint=$($EnablePrivateEndpoint.ToString().ToLower())",
    "clientIpAddress=$ClientIpAddress"
)
if ($EnablePrivateEndpoint) {
    $overrides += "vnetResourceGroup=$VnetResourceGroup"
    $overrides += "vnetName=$VnetName"
    $overrides += "peSubnetName=$PeSubnetName"
    if (-not [string]::IsNullOrEmpty($ExistingDnsZoneId)) {
        $overrides += "existingPrivateDnsZoneId=$ExistingDnsZoneId"
        $overrides += "existingPrivateDnsZoneLinked=$($ExistingDnsZoneLinked.ToString().ToLower())"
    }
}

# Capture stdout (JSON) and stderr SEPARATELY. Merging them with 2>&1
# breaks ConvertFrom-Json on success because `az` writes incidental
# notices (e.g. "A new Bicep release is available") and ARM diagnostic
# warnings to stderr, which then interleave with the JSON body on stdout.
# Force `-o json` defensively in case AZURE_DEFAULTS_OUTPUT is set to
# table/yaml in the operator's environment.
$logDir = Join-Path $scriptDir ".deploy-logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logStamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$stderrLog = Join-Path $logDir "$logStamp-bicep-stderr.txt"

$deployOut = Invoke-Native {
    az deployment group create `
        --resource-group $ResourceGroup `
        --name $deploymentName `
        --template-file $bicepFile `
        --parameters "@$paramsFile" `
        --parameters $overrides `
        --output json 2>$stderrLog
}
# Scrub the password from anything we might log on failure.
$plainPw = $null

if ($LASTEXITCODE -ne 0) {
    Write-Fail "Bicep deployment FAILED (exit $LASTEXITCODE)."
    if (Test-Path $stderrLog) {
        Write-Info "stderr captured to: $stderrLog"
        Get-Content $stderrLog | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkRed }
    }
    if ($deployOut) {
        $stdoutLog = Join-Path $logDir "$logStamp-bicep-stdout.txt"
        ($deployOut -join "`n") | Out-File -FilePath $stdoutLog -Encoding utf8
        Write-Info "stdout captured to: $stdoutLog"
    }
    exit 1
}
Write-Success "Bicep deployment succeeded ($deploymentName)"

# Validate non-empty BEFORE parsing  -  an empty stdout on a success exit
# is itself a bug worth surfacing rather than silently NPE'ing below.
$deployRaw = ($deployOut -join "`n").Trim()
if ([string]::IsNullOrWhiteSpace($deployRaw)) {
    Write-Fail "Bicep deploy succeeded (exit 0) but produced empty stdout  -  cannot read outputs."
    if (Test-Path $stderrLog) {
        Write-Info "stderr captured to: $stderrLog"
    }
    exit 1
}
try {
    $deployJson = $deployRaw | ConvertFrom-Json
} catch {
    # Dump raw stdout to disk for post-mortem; DO NOT echo inline (could
    # be hundreds of KB and may contain whatever polluted the stream).
    $stdoutLog = Join-Path $logDir "$logStamp-bicep-stdout-unparseable.txt"
    $deployRaw | Out-File -FilePath $stdoutLog -Encoding utf8
    Write-Fail "Could not parse az deployment output as JSON."
    Write-Info "Raw stdout dumped to: $stdoutLog"
    if (Test-Path $stderrLog) {
        Write-Info "stderr captured to:    $stderrLog"
    }
    exit 1
}
# Success path: stderr log only holds the incidental Bicep notice (if any).
# Remove it to keep .deploy-logs/ from accumulating noise.
if (Test-Path $stderrLog) { Remove-Item $stderrLog -Force -ErrorAction SilentlyContinue }
$bicepOutputs   = $deployJson.properties.outputs
$serverFqdn     = $bicepOutputs.serverFqdn.value
$serverId       = $bicepOutputs.serverId.value
$tenantId       = $bicepOutputs.tenantId.value
$privateFqdn    = $bicepOutputs.privateFqdn.value
Write-Info "Server FQDN  : $serverFqdn"
Write-Info "Server ID    : $serverId"
Write-Info "Tenant ID    : $tenantId"

# --------------------------------------------------------------------------
# 9. Restart if any params still pending  -  AGE is unusable until then
# --------------------------------------------------------------------------
Write-Step "Checking for PostgreSQL parameters pending restart"
$pendingJson = Invoke-Native {
    az postgres flexible-server parameter list `
        --resource-group $ResourceGroup `
        --server-name $ServerName `
        --query "[?isConfigPendingRestart].{name:name,value:value}" `
        --output json 2>$null
}
$pending = @()
if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($pendingJson)) {
    try { $pending = @($pendingJson | ConvertFrom-Json) } catch { $pending = @() }
}
if ($pending.Count -gt 0) {
    Write-Warn ("Parameters pending restart: " + (($pending | ForEach-Object { "$($_.name)=$($_.value)" }) -join '; '))
    Write-Info "Restarting PG (offline ~30-60s) so AGE preload takes effect..."
    Invoke-Native {
        az postgres flexible-server restart `
            --resource-group $ResourceGroup `
            --name $ServerName --output none 2>&1 | Out-Null
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "PG restart failed. AGE will be unusable until the server is restarted manually."
        exit 1
    }
    Write-Success "Restart issued."
} else {
    Write-Success "No parameters pending restart."
}

# --------------------------------------------------------------------------
# 10. Register the deployer as a User Entra admin (control plane, idempotent)
# --------------------------------------------------------------------------
Write-Step "Registering deployer as PG Entra User administrator"

$meJson = Invoke-Native { az ad signed-in-user show --output json 2>$null }
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($meJson)) {
    Write-Fail "Could not resolve signed-in user via 'az ad signed-in-user show'. Cannot continue."
    exit 1
}
$me = $meJson | ConvertFrom-Json
$deployerUpn = $me.userPrincipalName
$deployerOid = $me.id
Write-Info "Deployer: $deployerUpn ($deployerOid)"

$existingAdminsJson = Invoke-Native {
    az postgres flexible-server microsoft-entra-admin list `
        --resource-group $ResourceGroup `
        --server-name $ServerName `
        --output json 2>$null
}
$existingAdmins = @()
if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($existingAdminsJson)) {
    try { $existingAdmins = @($existingAdminsJson | ConvertFrom-Json) } catch { $existingAdmins = @() }
}

if ($existingAdmins | Where-Object { $_.objectId -eq $deployerOid }) {
    Write-Success "Deployer already registered as Entra admin (objectId match)."
} else {
    $adminOut = Invoke-Native {
        az postgres flexible-server microsoft-entra-admin create `
            --resource-group $ResourceGroup `
            --server-name $ServerName `
            --display-name $deployerUpn `
            --object-id $deployerOid `
            --type User `
            --only-show-errors `
            --output none 2>&1
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Registered $deployerUpn as PG Entra User admin."
    } elseif ("$adminOut" -match 'already exists|conflict') {
        Write-Success "Deployer admin already exists (control-plane idempotent)."
    } else {
        Write-Fail "Failed to register deployer as Entra admin (exit $LASTEXITCODE):"
        $adminOut | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkRed }
        exit 1
    }
}

# --------------------------------------------------------------------------
# 11. Register UAMIs as ServicePrincipal Entra admins (control-plane fallback)
# --------------------------------------------------------------------------
if ($uamiList.Count -gt 0) {
    Write-Step "Registering UAMIs as PG Entra ServicePrincipal admins"

    # Refresh admin list once after the deployer add  -  used to skip already-present UAMIs.
    $refreshJson = Invoke-Native {
        az postgres flexible-server microsoft-entra-admin list `
            --resource-group $ResourceGroup `
            --server-name $ServerName `
            --output json 2>$null
    }
    $existingAdmins = @()
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($refreshJson)) {
        try { $existingAdmins = @($refreshJson | ConvertFrom-Json) } catch { $existingAdmins = @() }
    }
    $existingOids = @($existingAdmins | ForEach-Object { $_.objectId })

    foreach ($entry in $uamiList) {
        $uamiName = [string]$entry.name
        $uamiOid  = [string]$entry.objectId
        if ([string]::IsNullOrEmpty($uamiName) -or [string]::IsNullOrEmpty($uamiOid)) {
            Write-Warn "Skipping malformed entry (missing name or objectId)."
            continue
        }
        Write-Info "UAMI: $uamiName ($uamiOid)"

        if ($existingOids -contains $uamiOid) {
            Write-Success "  Already registered (objectId match)."
            continue
        }

        $regOut = Invoke-Native {
            az postgres flexible-server microsoft-entra-admin create `
                --resource-group $ResourceGroup `
                --server-name $ServerName `
                --display-name $uamiName `
                --object-id $uamiOid `
                --type ServicePrincipal `
                --only-show-errors `
                --output none 2>&1
        }
        if ($LASTEXITCODE -eq 0) {
            Write-Success "  Registered $uamiName as PG Entra ServicePrincipal admin."
        } elseif ("$regOut" -match 'already exists|conflict') {
            Write-Success "  Already exists (control-plane idempotent)."
        } else {
            Write-Fail "  Failed to register $uamiName (exit $LASTEXITCODE):"
            $regOut | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkRed }
            # Non-fatal: continue with the rest of the UAMIs.
        }
    }
}

# --------------------------------------------------------------------------
# 12. Resolve PE private IP (when PE is enabled) and emit .outputs.json
# --------------------------------------------------------------------------
$privateIp = $null
if ($EnablePrivateEndpoint) {
    Write-Step "Resolving Private Endpoint NIC private IP"
    $peName = "${ServerName}-pe"
    $nicId = Invoke-Native {
        az network private-endpoint show `
            --name $peName --resource-group $ResourceGroup `
            --query "networkInterfaces[0].id" -o tsv 2>$null `
        | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
    }
    $nicId = ($nicId -join "").Trim()
    if (-not [string]::IsNullOrEmpty($nicId)) {
        $ipRaw = Invoke-Native {
            az network nic show --ids $nicId `
                --query "ipConfigurations[0].privateIPAddress" -o tsv 2>$null `
            | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
        }
        $privateIp = ($ipRaw -join "").Trim()
        if (-not [string]::IsNullOrEmpty($privateIp)) {
            Write-Success "PE private IP: $privateIp"
        } else {
            Write-Warn "Could not read private IP from NIC $nicId  -  leaving null."
            $privateIp = $null
        }
    } else {
        Write-Warn "Private endpoint $peName has no NIC reference  -  leaving private IP null."
    }
}

$outputs = [ordered]@{
    postgresqlServerName  = $ServerName
    postgresqlServerFqdn  = $serverFqdn
    postgresqlPrivateFqdn = $privateFqdn
    postgresqlPrivateIp   = $privateIp
    deployerEntraUpn      = $deployerUpn
    tenantId              = $tenantId
}
$outputsPath = Join-Path $scriptDir ".outputs.json"
$outputs | ConvertTo-Json -Depth 4 | Set-Content -Path $outputsPath -Encoding UTF8
Write-Step "Wrote outputs to $outputsPath"
Get-Content $outputsPath | ForEach-Object { Write-Host "      $_" -ForegroundColor Gray }

# --------------------------------------------------------------------------
# 13. What next
# --------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host " 01-postgresql DEPLOYMENT COMPLETE" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next step: deploy the backend + MCP sidecar Container App." -ForegroundColor Cyan
Write-Host "    cd $($scriptDir | Split-Path -Parent)\02-backend"            -ForegroundColor Gray
Write-Host "    pwsh ./deploy.ps1"                                            -ForegroundColor Gray
Write-Host ""
Write-Host "  02-backend/deploy.ps1 will read 01-postgresql/.outputs.json"     -ForegroundColor Gray
Write-Host "  for postgresqlServerFqdn and tenantId."                          -ForegroundColor Gray
Write-Host ""
exit 0
