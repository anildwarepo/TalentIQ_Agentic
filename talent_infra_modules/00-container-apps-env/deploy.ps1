#requires -Version 5.1
<#
.SYNOPSIS
    Deploys an Azure Container Apps Environment (ACA Env) into an existing VNet.

.DESCRIPTION
    Deploys ONE Container Apps Environment plus its companion Log Analytics
    workspace. The infrastructure subnet is either:
      * Pre-existing (and delegated to Microsoft.App/environments)
      * Created on-the-fly inside the supplied VNet via a sidecar Bicep
        deployment

    deploy.ps1 does all the existing-or-create plumbing on the control plane
    BEFORE main.bicep runs, so the Bicep template only needs to receive a
    fully-qualified subnet ID.

.NOTES
    * Uses `az` CLI directly. NO azd dependency.
    * ACA enforces a 1:1 mapping between a Managed Environment and its
      infrastructure subnet (ManagedEnvironmentSubnetInUse). When an env
      is deleted, Azure holds a soft-lock on the subnet for ~30 minutes
      before another env can claim it.
    * Subnet delegation is REQUIRED: Microsoft.App/environments.
    * Re-running with the same inputs is idempotent (Azure ARM update).

.PARAMETER SubscriptionId
    Azure subscription ID. Defaults to AZURE_SUBSCRIPTION_ID env var or
    the currently signed-in account.

.PARAMETER ResourceGroup
    Resource group that will host the Container Apps Environment.
    Defaults to AZURE_RESOURCE_GROUP env var. Required.

.PARAMETER Location
    Azure region. Defaults to AZURE_LOCATION env var or 'westus'. (Canonical region for this project  -  VNet 'vnet-westus' lives in westus.)

.PARAMETER EnvName
    Container Apps Environment name (2-32 chars). Defaults to
    AZURE_ACA_ENV_NAME env var or 'cae-<5-char hash>' derived from
    (SubscriptionId|ResourceGroup|Location).

.PARAMETER VnetResourceGroup
    Resource group of the existing VNet. Defaults to AZURE_VNET_RESOURCE_GROUP
    env var or $ResourceGroup.

.PARAMETER VnetName
    Name of the existing VNet that hosts (or will host) the ACA subnet.
    Required. Defaults to AZURE_VNET_NAME env var.

.PARAMETER AcaSubnetName
    Name of the ACA subnet inside the VNet. Defaults to AZURE_ACA_SUBNET_NAME
    env var or 'talentiq-aca'.

.PARAMETER AcaSubnetAddressPrefix
    CIDR for the ACA subnet. REQUIRED when the subnet does not exist (will be
    created). Ignored when reusing an existing subnet. ACA recommends a /23.
    Defaults to AZURE_ACA_SUBNET_PREFIX env var.

.PARAMETER InternalOnly
    When true, the Container Apps Environment exposes ingress only on the VNet
    (no public endpoint). Defaults to AZURE_ACA_INTERNAL_ONLY env var or
    $false (matches the v2 baseline).

.PARAMETER LogAnalyticsWorkspaceName
    Optional Log Analytics workspace name. Defaults to AZURE_LOG_ANALYTICS_NAME
    env var or auto-derived as '<EnvName>-logs'.

.PARAMETER Force
    Skip the interactive confirmation prompt.

.EXAMPLE
    .\deploy.ps1 -ResourceGroup talentiq-rg -VnetName talentiq-vnet

.EXAMPLE
    .\deploy.ps1 -ResourceGroup talentiq-rg -VnetResourceGroup talentiq-network-rg `
                 -VnetName talentiq-vnet -AcaSubnetAddressPrefix 10.0.6.0/23 -Force
#>

[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$Location,
    [string]$EnvName,
    [string]$VnetResourceGroup,
    [string]$VnetName,
    [string]$AcaSubnetName,
    [string]$AcaSubnetAddressPrefix,
    [Nullable[bool]]$InternalOnly,
    [string]$LogAnalyticsWorkspaceName,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# -----------------------------------------------------------------------------
# 0. Shared helpers
# -----------------------------------------------------------------------------
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir '..\shared\common.ps1')

Show-AppConfigEnvPreflight -Import -Override -Force:$Force

Write-Step '00-container-apps-env: prerequisite checks'
Test-AzLoggedIn

# -----------------------------------------------------------------------------
# 1. Parameter resolution (script-arg > env-var > prompt)
# -----------------------------------------------------------------------------
Write-Step 'Resolving parameters'

$SubscriptionId = Resolve-AzSubscriptionId -Value $SubscriptionId -EnvVar 'AZURE_SUBSCRIPTION_ID'
$ResourceGroup = Resolve-AzResourceGroupName -SubscriptionId $SubscriptionId -Name 'Resource group' -EnvVar 'AZURE_RESOURCE_GROUP' -Value $ResourceGroup
if ([string]::IsNullOrWhiteSpace($Location)) {
    # Canonical region for this project is westus (VNet 'vnet-westus', talent_infra_v2 baseline).
    # Override via -Location <region> or $env:AZURE_LOCATION when targeting a different region.
    $Location = if ($env:AZURE_LOCATION) { $env:AZURE_LOCATION } else { 'westus' }
}
$VnetResourceGroup = Get-ParameterValue -Name 'VNet resource group' -EnvVar 'AZURE_VNET_RESOURCE_GROUP' -Value $VnetResourceGroup -Default $ResourceGroup
$VnetName          = Get-ParameterValue -Name 'VNet name' -EnvVar 'AZURE_VNET_NAME' -Value $VnetName
# -AlwaysPrompt: subnet names are environment-specific. Even though no
# param-block default exists today, force confirmation so a future
# maintainer adding a default does not re-introduce the silent-bind bug.
$AcaSubnetName     = Get-ParameterValue -Name 'ACA subnet name' -EnvVar 'AZURE_ACA_SUBNET_NAME' -Value $AcaSubnetName -Default 'talentiq-aca' -AlwaysPrompt
if ([string]::IsNullOrWhiteSpace($AcaSubnetAddressPrefix) -and $env:AZURE_ACA_SUBNET_PREFIX) {
    $AcaSubnetAddressPrefix = $env:AZURE_ACA_SUBNET_PREFIX
}
if ([string]::IsNullOrWhiteSpace($LogAnalyticsWorkspaceName) -and $env:AZURE_LOG_ANALYTICS_NAME) {
    $LogAnalyticsWorkspaceName = $env:AZURE_LOG_ANALYTICS_NAME
}

# InternalOnly: tri-state. Param > env var > $false.
if (-not $PSBoundParameters.ContainsKey('InternalOnly')) {
    if ($env:AZURE_ACA_INTERNAL_ONLY) {
        $InternalOnly = [System.Convert]::ToBoolean($env:AZURE_ACA_INTERNAL_ONLY)
    } else {
        $InternalOnly = $false
    }
}

# -----------------------------------------------------------------------------
# 2. Subscription context
# -----------------------------------------------------------------------------
Test-AzSubscription -SubscriptionId $SubscriptionId

# -----------------------------------------------------------------------------
# 3. EnvName default: cae-<5-char SHA256 hash of subId|rg|location>
# -----------------------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($EnvName)) {
    if ($env:AZURE_ACA_ENV_NAME) {
        $EnvName = $env:AZURE_ACA_ENV_NAME
    } else {
        $source = "$SubscriptionId|$ResourceGroup|$Location"
        $bytes  = [System.Text.Encoding]::UTF8.GetBytes($source)
        $sha    = [System.Security.Cryptography.SHA256]::Create()
        try { $hashBytes = $sha.ComputeHash($bytes) } finally { $sha.Dispose() }
        $hash5  = -join ([BitConverter]::ToString($hashBytes).Replace('-', '').ToLower().ToCharArray()[0..4])
        $EnvName = "cae-$hash5"
        Write-Info "Derived deterministic EnvName: $EnvName (from SHA256 of subId|rg|location)"
    }
}

# Length & charset validation (Azure: 2-32 chars, lowercase alphanum + hyphens)
if ($EnvName.Length -lt 2 -or $EnvName.Length -gt 32) {
    Write-Fail "EnvName '$EnvName' must be 2-32 chars (Azure limit). Override with -EnvName or AZURE_ACA_ENV_NAME."
}

# -----------------------------------------------------------------------------
# 4. Resource group + VNet prerequisites
# -----------------------------------------------------------------------------
Assert-PrerequisitesExist `
    -ResourceGroup $ResourceGroup `
    -VnetResourceGroup $VnetResourceGroup `
    -Checks @(
        @{ Type = 'rg';   Name = $ResourceGroup     },
        @{ Type = 'rg';   Name = $VnetResourceGroup },
        @{ Type = 'vnet'; Name = $VnetName          }
    )

# -----------------------------------------------------------------------------
# 5. Subnet detection + decision (existing vs create) + soft-lock check
# -----------------------------------------------------------------------------
Write-Step "Inspecting subnet '$AcaSubnetName' inside VNet '$VnetName' (RG '$VnetResourceGroup')"

function Convert-IpToUInt32 {
    param([Parameter(Mandatory)][string]$Ip)
    $addr  = [System.Net.IPAddress]::Parse($Ip)
    $bytes = $addr.GetAddressBytes()
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($bytes) }
    return [BitConverter]::ToUInt32($bytes, 0)
}

function Test-CidrInsideAny {
    param(
        [Parameter(Mandatory)][string]$Cidr,
        [Parameter(Mandatory)][string[]]$ParentCidrs
    )
    $cidrParts = $Cidr.Split('/')
    if ($cidrParts.Count -ne 2) { return $false }
    $childBits = [int]$cidrParts[1]
    if ($childBits -lt 0 -or $childBits -gt 32) { return $false }
    try { $childInt = Convert-IpToUInt32 -Ip $cidrParts[0] } catch { return $false }

    foreach ($parent in $ParentCidrs) {
        $pParts = $parent.Split('/')
        if ($pParts.Count -ne 2) { continue }
        $pBits = [int]$pParts[1]
        if ($pBits -lt 0 -or $pBits -gt 32) { continue }
        if ($childBits -lt $pBits) { continue }
        try { $pInt = Convert-IpToUInt32 -Ip $pParts[0] } catch { continue }
        $pMask = if ($pBits -eq 0) { [uint32]0 } else { [uint32](([uint64]0xFFFFFFFF -shl (32 - $pBits)) -band 0xFFFFFFFF) }
        $pNet  = $pInt -band $pMask
        if (($childInt -band $pMask) -eq $pNet) { return $true }
    }
    return $false
}

# Query subnet (suppress error if missing  -  we check $LASTEXITCODE)
$subnetJson = az network vnet subnet show `
    --subscription $SubscriptionId `
    -g $VnetResourceGroup `
    --vnet-name $VnetName `
    -n $AcaSubnetName `
    -o json 2>$null
$subnetExitCode = $LASTEXITCODE

$createSubnet  = $false
$existingSubnet = $null

if ($subnetExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($subnetJson)) {
    $existingSubnet = $subnetJson | ConvertFrom-Json
    Write-Info "Subnet '$AcaSubnetName' already exists (CIDR: $($existingSubnet.addressPrefix))"

    # Delegation check  -  must be Microsoft.App/environments
    $hasAcaDelegation = $false
    if ($existingSubnet.delegations) {
        foreach ($d in $existingSubnet.delegations) {
            if ($d.serviceName -eq 'Microsoft.App/environments') { $hasAcaDelegation = $true; break }
        }
    }
    if (-not $hasAcaDelegation) {
        Write-Fail @"
Subnet '$AcaSubnetName' exists but is NOT delegated to Microsoft.App/environments.
Container Apps Environments REQUIRE this delegation. We do NOT auto-modify
existing subnet delegations to avoid disrupting other workloads.

Either pick a different subnet name (-AcaSubnetName) so a new one is created,
or manually add the delegation:
  az network vnet subnet update -g $VnetResourceGroup --vnet-name $VnetName \
      -n $AcaSubnetName --delegations Microsoft.App/environments
"@
    }
    Write-Success 'Subnet delegation OK (Microsoft.App/environments).'

    # Soft-lock / 1:1 check  -  is another ACA env already pinned to this subnet?
    Write-Info 'Checking whether another Container Apps Environment already owns this subnet...'
    $envsJson = az containerapp env list --subscription $SubscriptionId -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($envsJson)) {
        $envs   = $envsJson | ConvertFrom-Json
        $owners = @($envs | Where-Object {
            $_.properties -and $_.properties.vnetConfiguration -and
            $_.properties.vnetConfiguration.infrastructureSubnetId -eq $existingSubnet.id
        })
        if ($owners.Count -gt 0) {
            $foreignOwners = @($owners | Where-Object { $_.name -ne $EnvName })
            if ($foreignOwners.Count -gt 0) {
                $names = ($foreignOwners | ForEach-Object { "$($_.name) (RG: $($_.resourceGroup))" }) -join '; '
                Write-Fail @"
Subnet '$AcaSubnetName' is already owned by a DIFFERENT Container Apps Environment:
  $names

ACA enforces a 1:1 mapping (ManagedEnvironmentSubnetInUse). To proceed you must
either:
  * Pick a different subnet (-AcaSubnetName) for this env, OR
  * Delete the existing env, wait ~30 minutes for Azure's soft-lock to clear,
    then re-run this script.
"@
            }
            Write-Success "Existing Container Apps Environment '$EnvName' already uses this subnet  -  idempotent reuse."
        }
    }
    $createSubnet = $false
} else {
    Write-Info "Subnet '$AcaSubnetName' does not exist yet  -  will be created."
    if ([string]::IsNullOrWhiteSpace($AcaSubnetAddressPrefix)) {
        Write-Fail "Subnet '$AcaSubnetName' does not exist and -AcaSubnetAddressPrefix was not supplied (also tried `$env:AZURE_ACA_SUBNET_PREFIX). Provide a CIDR (recommended /23 or larger) that fits inside the VNet's address space."
    }
    if ($AcaSubnetAddressPrefix -notmatch '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$') {
        Write-Fail "AcaSubnetAddressPrefix '$AcaSubnetAddressPrefix' is not a valid IPv4 CIDR."
    }

    # CIDR containment: must be inside one of the VNet's addressSpace.addressPrefixes
    $vnetJson = Invoke-Native {
        az network vnet show --subscription $SubscriptionId -g $VnetResourceGroup -n $VnetName -o json
    }
    $vnet           = $vnetJson | ConvertFrom-Json
    $parentPrefixes = @($vnet.addressSpace.addressPrefixes)
    if (-not (Test-CidrInsideAny -Cidr $AcaSubnetAddressPrefix -ParentCidrs $parentPrefixes)) {
        Write-Fail @"
AcaSubnetAddressPrefix '$AcaSubnetAddressPrefix' is NOT contained inside the
VNet's address space.

VNet '$VnetName' address prefixes: $($parentPrefixes -join ', ')

Pick a CIDR that fits inside one of the above ranges.
"@
    }
    Write-Success "CIDR '$AcaSubnetAddressPrefix' fits inside VNet address space ($($parentPrefixes -join ', '))."
    $createSubnet = $true
}

# -----------------------------------------------------------------------------
# 6. Confirmation
# -----------------------------------------------------------------------------
$summary = @"
About to deploy a Container Apps Environment with the following inputs:

  Subscription      : $SubscriptionId
  Resource group    : $ResourceGroup
  Location          : $Location
  Env name          : $EnvName
  Internal-only     : $InternalOnly
  Log Analytics name: $(if ([string]::IsNullOrWhiteSpace($LogAnalyticsWorkspaceName)) { "(auto: $EnvName-logs)" } else { $LogAnalyticsWorkspaceName })

  VNet RG           : $VnetResourceGroup
  VNet name         : $VnetName
  ACA subnet        : $AcaSubnetName
  Subnet action     : $(if ($createSubnet) { "CREATE (CIDR $AcaSubnetAddressPrefix)" } else { "REUSE existing (CIDR $($existingSubnet.addressPrefix))" })
"@
Write-Host ''
Write-Host $summary
Write-Host ''
if (-not (Confirm-Action -Message 'Proceed with deployment?' -Force:$Force)) {
    Write-Warn 'Deployment cancelled by user.'
    exit 0
}

# -----------------------------------------------------------------------------
# 7. (Optional) Create subnet via sidecar Bicep deployment in VNet's RG
# -----------------------------------------------------------------------------
if ($createSubnet) {
    Write-Step "Creating subnet '$AcaSubnetName' (CIDR $AcaSubnetAddressPrefix) inside VNet '$VnetName' (RG '$VnetResourceGroup')"
    $subnetTemplate = Join-Path $scriptDir 'infra\modules\aca-subnet.bicep'
    Invoke-Native {
        az deployment group create `
            --subscription $SubscriptionId `
            -g $VnetResourceGroup `
            --template-file $subnetTemplate `
            --parameters vnetName=$VnetName subnetName=$AcaSubnetName addressPrefix=$AcaSubnetAddressPrefix `
            -o json
    } | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Subnet sidecar deployment FAILED (exit $LASTEXITCODE). az error printed above. Common causes:"
        Write-Info "  * VNet '$VnetName' is in a different region than -Location '$Location' (ACA infra subnet must live inside a VNet in the same region as the env)."
        Write-Info "  * Requested CIDR $AcaSubnetAddressPrefix overlaps an existing subnet in '$VnetName'."
        Write-Info "  * Caller lacks Microsoft.Network/virtualNetworks/subnets/write on RG '$VnetResourceGroup'."
        exit 1
    }
    Write-Success "Subnet '$AcaSubnetName' created."
}

# Resolve subnet ID (single source of truth for main.bicep)
$subnetId = az network vnet subnet show `
    --subscription $SubscriptionId `
    -g $VnetResourceGroup `
    --vnet-name $VnetName `
    -n $AcaSubnetName `
    --query id -o tsv
if ([string]::IsNullOrWhiteSpace($subnetId)) {
    Write-Fail "Could not resolve subnet ID for '$AcaSubnetName' after creation/lookup."
    exit 1
}
Write-Info "Resolved subnet ID: $subnetId"

# -----------------------------------------------------------------------------
# 8. Deploy main.bicep (Container Apps Environment + Log Analytics)
# -----------------------------------------------------------------------------
Write-Step "Deploying Container Apps Environment '$EnvName' into '$ResourceGroup'"

$mainTemplate   = Join-Path $scriptDir 'infra\main.bicep'
$mainParameters = Join-Path $scriptDir 'infra\main.parameters.json'

$internalOnlyArg = ([bool]$InternalOnly).ToString().ToLower()
$deploymentJson = Invoke-Native {
    az deployment group create `
        --subscription $SubscriptionId `
        -g $ResourceGroup `
        --template-file $mainTemplate `
        --parameters "@$mainParameters" `
        --parameters `
            location=$Location `
            containerAppsEnvironmentName=$EnvName `
            subnetId=$subnetId `
            internalOnly=$internalOnlyArg `
            logAnalyticsWorkspaceName=$LogAnalyticsWorkspaceName `
        -o json
}

# ----------------------------------------------------------------------------
# 8a. Validate the deployment ACTUALLY succeeded before claiming so.
#     Invoke-Native deliberately runs with $ErrorActionPreference='Continue'
#     so az non-zero exits do not blow up the surrounding script  -  the caller
#     (this code) is responsible for inspecting $LASTEXITCODE. Skipping these
#     checks is how a failed `az deployment group create` (e.g. region
#     mismatch between the ACA env and its VNet subnet) silently fell through
#     to a green "deployment complete" banner with an all-null .outputs.json.
# ----------------------------------------------------------------------------
if ($LASTEXITCODE -ne 0) {
    Write-Fail "az deployment group create FAILED (exit $LASTEXITCODE). Azure error printed above."
    Write-Info "Inspect: az deployment group show -g $ResourceGroup -n <name> --query properties.error"
    Write-Info "Common cause: VNet '$VnetName' is in a different region than -Location '$Location'."
    Write-Info "             Either pass -Location <vnet-region> or set `$env:AZURE_LOCATION=<vnet-region> before re-running."
    exit 1
}
if ([string]::IsNullOrWhiteSpace($deploymentJson)) {
    Write-Fail "az deployment group create returned empty output despite exit code 0. Treating as failure."
    exit 1
}
try {
    $deployment = $deploymentJson | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-Fail "Could not parse az deployment output as JSON: $($_.Exception.Message)"
    exit 1
}
if ($null -eq $deployment -or $null -eq $deployment.properties) {
    Write-Fail "az deployment output missing 'properties' envelope. Treating as failure."
    exit 1
}
if ($deployment.properties.provisioningState -ne 'Succeeded') {
    $state = $deployment.properties.provisioningState
    Write-Fail "Deployment did not reach Succeeded (provisioningState: $state)."
    exit 1
}
$out = $deployment.properties.outputs
if ($null -eq $out -or $null -eq $out.containerAppsEnvName -or [string]::IsNullOrWhiteSpace($out.containerAppsEnvName.value)) {
    Write-Fail "Deployment reported Succeeded but main.bicep returned no outputs (or containerAppsEnvName is empty). Refusing to write a hand-off file with null values."
    exit 1
}
Write-Success "Container Apps Environment deployment succeeded ($($out.containerAppsEnvName.value))."

# -----------------------------------------------------------------------------
# 9. Emit .outputs.json hand-off for 02-backend & 03-frontend
# -----------------------------------------------------------------------------
Write-Step 'Writing .outputs.json hand-off file'

$outputsPath = Join-Path $scriptDir '.outputs.json'
$payload = [ordered]@{
    containerAppsEnvName            = $out.containerAppsEnvName.value
    containerAppsEnvId              = $out.containerAppsEnvId.value
    containerAppsEnvResourceGroup   = $ResourceGroup
    containerAppsEnvDefaultDomain   = $out.containerAppsEnvDefaultDomain.value
    containerAppsEnvStaticIp        = $out.containerAppsEnvStaticIp.value
    acaSubnetId                     = $out.acaSubnetId.value
    acaSubnetName                   = $AcaSubnetName
    vnetName                        = $VnetName
    vnetResourceGroup               = $VnetResourceGroup
    logAnalyticsWorkspaceId         = $out.logAnalyticsWorkspaceId.value
    internalOnly                    = [bool]$InternalOnly
    location                        = $Location
    subscriptionId                  = $SubscriptionId
}
($payload | ConvertTo-Json -Depth 6) | Set-Content -Path $outputsPath -Encoding UTF8
Write-Success "Wrote $outputsPath"

# -----------------------------------------------------------------------------
# 10. What-next footer
# -----------------------------------------------------------------------------
Write-Host ''
Write-Host '===================================================================='
Write-Host '  00-container-apps-env: deployment complete'
Write-Host '===================================================================='
Write-Host ''
Write-Host "  Container Apps Environment : $($payload.containerAppsEnvName)"
Write-Host "  Default domain             : $($payload.containerAppsEnvDefaultDomain)"
Write-Host "  Static IP                  : $($payload.containerAppsEnvStaticIp)"
Write-Host "  Subnet                     : $($payload.acaSubnetName) ($($payload.acaSubnetId))"
Write-Host "  Log Analytics workspace ID : $($payload.logAnalyticsWorkspaceId)"
Write-Host ''
Write-Host '  Next steps:'
Write-Host "    * 02-backend\deploy.ps1  will auto-pick up containerAppsEnvName / RG"
Write-Host "                              from $outputsPath if -ContainerAppsEnvName is not set."
Write-Host "    * 03-frontend\deploy.ps1 will do the same."
Write-Host ''
