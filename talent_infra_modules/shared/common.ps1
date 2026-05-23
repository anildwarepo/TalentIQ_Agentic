<#
.SYNOPSIS
    Shared helpers for talent_infra_modules per-component deployment scripts.

.DESCRIPTION
    Dot-source this file from any per-component deploy.ps1:

        . (Join-Path $PSScriptRoot "..\shared\common.ps1")

    Then call the functions documented below. All helpers are idempotent,
    write coloured output via Write-Step / Write-Success / Write-Warn /
    Write-Fail, and never modify global $ErrorActionPreference.

    Design notes (carry-over from talent_infra_v2/hooks/postprovision.ps1 and
    scripts/Enable-PostgresEntraAuth.ps1):
      * No azd dependency. All env discovery is via $env:* OR an explicit
        -Default argument. Scripts under talent_infra_modules/ are invoked
        directly by the operator (no azd hooks).
      * az CLI is the source of truth. We never parse az output without
        --output json | ConvertFrom-Json.
      * Native az errors (WARNING/ERROR lines on stdout) are filtered out
        of -o tsv reads so callers see only the value.
      * Get-ParameterValue is the SINGLE entry point for any required
        parameter  -  env var first, then prompt, then default. Secure
        values are read via Read-Host -AsSecureString and returned as a
        SecureString.

    Style:
      * Verb-Noun PowerShell function names where natural.
      * Write-* helpers prefixed with the script's contract verb.
      * No global state. Helpers take what they need as parameters.
#>

# ------------------------------------------------------------------------------
# Coloured output helpers
# ------------------------------------------------------------------------------

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "    OK  $Message" -ForegroundColor Green
}

function Write-Warn {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "    !!  $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "    XX  $Message" -ForegroundColor Red
}

function Write-Info {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "    $Message" -ForegroundColor Gray
}

# ------------------------------------------------------------------------------
# Native command runner  -  keeps $ErrorActionPreference local to the call
# ------------------------------------------------------------------------------

function Invoke-Native {
    <#
    .SYNOPSIS
        Run a native command (az, docker, etc.) without letting native
        non-zero exits stop the surrounding script. Returns the command
        output. Caller MUST check $LASTEXITCODE.
    #>
    param([Parameter(Mandatory)][scriptblock]$Command)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command }
    finally { $ErrorActionPreference = $saved }
}

# ------------------------------------------------------------------------------
# Az CLI sign-in & subscription
# ------------------------------------------------------------------------------

function Test-AzLoggedIn {
    <#
    .SYNOPSIS
        Verifies `az account show` works. Exits with a clear message
        otherwise.
    .OUTPUTS
        [pscustomobject] account object on success (user.name, tenantId,
        id, name).
    #>
    Write-Step "Verifying Azure CLI sign-in"
    $raw = Invoke-Native { az account show --output json 2>$null }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        Write-Fail "Not signed in to Azure CLI."
        Write-Info "Run: az login"
        exit 1
    }
    try { $acct = $raw | ConvertFrom-Json } catch {
        Write-Fail "Could not parse 'az account show' output."
        exit 1
    }
    Write-Success "Signed in as $($acct.user.name) (tenant $($acct.tenantId))"
    Write-Info "Subscription: $($acct.name) [$($acct.id)]"
    return $acct
}

function Test-AzSubscription {
    <#
    .SYNOPSIS
        Verifies the active subscription matches -SubscriptionId. Switches
        if it doesn't.
    .PARAMETER SubscriptionId
        Target subscription GUID.
    #>
    param([Parameter(Mandatory)][string]$SubscriptionId)
    Write-Step "Ensuring active subscription is $SubscriptionId"
    $current = (Invoke-Native { az account show --query id -o tsv 2>$null } | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }) -join ""
    $current = $current.Trim()
    if ($current -eq $SubscriptionId) {
        Write-Success "Already on $SubscriptionId"
        return
    }
    Write-Info "Switching from $current to $SubscriptionId"
    Invoke-Native { az account set --subscription $SubscriptionId 2>&1 | Out-Null }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Could not switch subscription. Check that you have access to $SubscriptionId."
        exit 1
    }
    Write-Success "Switched to $SubscriptionId"
}

# ------------------------------------------------------------------------------
# Parameter resolution (env var -> prompt -> default)
# ------------------------------------------------------------------------------

function Get-ParameterValue {
    <#
    .SYNOPSIS
        Resolve a required parameter value from (in order):
          1. The -Value parameter, if non-empty (script-arg pass-through).
          2. The env var named -EnvVar, if set and non-empty.
          3. An interactive Read-Host prompt, defaulting to -Default.
          4. The -Default value if running non-interactively with no input.

        When -AlwaysPrompt is set, steps 1 and 2 are downgraded to default
        suggestions for the prompt; the operator is always asked to
        confirm (Enter accepts the suggestion) or type an override. Use
        this for env-specific Azure resource names (subnets, NSGs,
        peering, route tables, etc.) where a silent default is unsafe
        across environments. See .PARAMETER AlwaysPrompt.

    .PARAMETER Name
        Display name for log/prompt text.

    .PARAMETER Prompt
        Prompt text shown to the user. Defaults to "$Name".

    .PARAMETER Value
        Optional script-arg pre-supplied value. When non-empty, returned
        as-is (no prompt, no env var lookup). Lets a script wire its own
        named param directly through.

    .PARAMETER Default
        Default value if user just presses Enter at the prompt. Shown in
        the prompt as "(default: <value>)".

    .PARAMETER EnvVar
        Environment variable name to check before prompting. When the
        env var is set and non-empty, its value is returned without
        prompting.

    .PARAMETER Secure
        When set, the prompt uses Read-Host -AsSecureString and returns
        a SecureString. The env var is converted to SecureString if set.

    .PARAMETER AlwaysPrompt
        When set, the function ALWAYS displays the interactive prompt
        even if -Value or the env var resolved to a non-empty string.
        The resolved value (Value > env var > Default) is shown as the
        suggested default in the usual "(default: X)" format, and
        pressing Enter accepts it. Reserved for env-specific Azure
        resource names (subnets, NSGs, peering, route tables) where a
        silent default is unsafe across environments  -  never apply to
        platform invariants like PG version, SKU tier, or admin login.

    .OUTPUTS
        [string] or [SecureString] depending on -Secure.

    .EXAMPLE
        $rg = Get-ParameterValue -Name "Resource group" -EnvVar "AZURE_RESOURCE_GROUP" -Default "rg-talent-prod"

    .EXAMPLE
        $pw = Get-ParameterValue -Name "Postgres admin password" -EnvVar "POSTGRESQL_ADMIN_PASSWORD" -Secure

    .EXAMPLE
        # Subnet names differ per environment  -  always confirm with the
        # operator, even when a param-block default is wired through as
        # -Value. Pressing Enter accepts "pe-subnet"; anything else wins.
        $subnet = Get-ParameterValue -Name "PE subnet name" `
            -Value $PeSubnetName -EnvVar "AZURE_PE_SUBNET_NAME" `
            -Default "pe-subnet" -AlwaysPrompt
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$Prompt = "",
        [string]$Value = "",
        [string]$Default = "",
        [string]$EnvVar = "",
        [switch]$Secure,
        [switch]$AlwaysPrompt
    )

    # Resolve env-var value once  -  used both as a fast-path source and as
    # a default suggestion under -AlwaysPrompt.
    $envVal = $null
    if (-not [string]::IsNullOrEmpty($EnvVar)) {
        $envVal = [Environment]::GetEnvironmentVariable($EnvVar)
    }

    # Fast path (historical behaviour): script-arg wins, then env var,
    # then prompt. Skipped entirely when -AlwaysPrompt is set so the
    # operator is always asked to confirm env-specific resource names
    # (subnets, NSGs, peering, route tables, etc.).
    if (-not $AlwaysPrompt) {
        if (-not [string]::IsNullOrEmpty($Value)) {
            if ($Secure) {
                return (ConvertTo-SecureString $Value -AsPlainText -Force)
            }
            return $Value
        }
        if (-not [string]::IsNullOrEmpty($envVal)) {
            Write-Info "$Name = (from `$env:$EnvVar)"
            if ($Secure) {
                return (ConvertTo-SecureString $envVal -AsPlainText -Force)
            }
            return $envVal
        }
    }

    # Interactive prompt. Reached when:
    #   (a) Neither -Value nor env var supplied a value, OR
    #   (b) -AlwaysPrompt was set.
    # Suggested-default priority: -Value > env var > -Default. Operator
    # hits Enter to accept the suggestion, otherwise types an override.
    $suggested = ""
    if     (-not [string]::IsNullOrEmpty($Value))   { $suggested = $Value }
    elseif (-not [string]::IsNullOrEmpty($envVal))  { $suggested = $envVal }
    elseif (-not [string]::IsNullOrEmpty($Default)) { $suggested = $Default }

    $promptText = if ([string]::IsNullOrEmpty($Prompt)) { $Name } else { $Prompt }
    if (-not [string]::IsNullOrEmpty($suggested)) {
        $promptText = "$promptText (default: $suggested)"
    }

    if ($Secure) {
        # NOTE: local must NOT be named $secure  -  PowerShell is case-insensitive
        # for variables, so $secure would shadow/overwrite the [switch]$Secure
        # parameter and trip a SwitchParameter<->SecureString type-coercion error.
        $secureValue = Read-Host -Prompt $promptText -AsSecureString
        if ($null -eq $secureValue -or $secureValue.Length -eq 0) {
            if (-not [string]::IsNullOrEmpty($suggested)) {
                return (ConvertTo-SecureString $suggested -AsPlainText -Force)
            }
            Write-Fail "No value supplied for required secure parameter '$Name'."
            exit 1
        }
        return $secureValue
    }

    $entered = Read-Host -Prompt $promptText
    if ([string]::IsNullOrWhiteSpace($entered)) {
        if (-not [string]::IsNullOrEmpty($suggested)) {
            return $suggested
        }
        Write-Fail "No value supplied for required parameter '$Name'."
        exit 1
    }
    return $entered.Trim()
}

function ConvertFrom-SecureStringPlain {
    <#
    .SYNOPSIS
        Convert a [SecureString] back to plain text for use with az CLI
        (which takes passwords as positional args). Avoid logging the
        result.
    #>
    param([Parameter(Mandatory)][SecureString]$Secure)
    $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

# ------------------------------------------------------------------------------
# Resource existence checks
# ------------------------------------------------------------------------------

function Test-ResourceGroup {
    <#
    .SYNOPSIS
        True if the resource group exists in the current subscription.
    #>
    param([Parameter(Mandatory)][string]$Name)
    $exists = Invoke-Native { az group exists --name $Name --output tsv 2>$null }
    return ($exists -eq 'true')
}

function Test-ResourceExists {
    <#
    .SYNOPSIS
        Generic wrapper around `az resource show`. Returns $true if the
        named resource exists in -ResourceGroup, $false otherwise.

        Supported -ResourceType values (azure resource-type strings or
        the short aliases below):

          Alias               Azure resource type
          ----------------    -----------------------------------------------
          vnet                Microsoft.Network/virtualNetworks
          containerappenv     Microsoft.App/managedEnvironments
          containerapp        Microsoft.App/containerApps
          acr                 Microsoft.ContainerRegistry/registries
          postgres            Microsoft.DBforPostgreSQL/flexibleServers
          foundry             Microsoft.CognitiveServices/accounts
          cosmos              Microsoft.DocumentDB/databaseAccounts
          keyvault            Microsoft.KeyVault/vaults
          uami                Microsoft.ManagedIdentity/userAssignedIdentities

        Any other -ResourceType is passed through to `az resource show`
        as-is.
    #>
    param(
        [Parameter(Mandatory)][string]$ResourceGroup,
        [Parameter(Mandatory)][string]$ResourceType,
        [Parameter(Mandatory)][string]$Name
    )

    $typeMap = @{
        vnet            = 'Microsoft.Network/virtualNetworks'
        containerappenv = 'Microsoft.App/managedEnvironments'
        containerapp    = 'Microsoft.App/containerApps'
        acr             = 'Microsoft.ContainerRegistry/registries'
        postgres        = 'Microsoft.DBforPostgreSQL/flexibleServers'
        foundry         = 'Microsoft.CognitiveServices/accounts'
        cosmos          = 'Microsoft.DocumentDB/databaseAccounts'
        keyvault        = 'Microsoft.KeyVault/vaults'
        uami            = 'Microsoft.ManagedIdentity/userAssignedIdentities'
    }
    $fullType = if ($typeMap.ContainsKey($ResourceType.ToLower())) {
        $typeMap[$ResourceType.ToLower()]
    } else { $ResourceType }

    $null = Invoke-Native {
        az resource show `
            --resource-group $ResourceGroup `
            --resource-type $fullType `
            --name $Name `
            --output none 2>$null
    }
    return ($LASTEXITCODE -eq 0)
}

function Test-VnetExists {
    <#
    .SYNOPSIS
        True if -VnetName exists in -ResourceGroup.

        Use this instead of Test-ResourceExists -ResourceType 'vnet' when
        the caller may only have Microsoft.Network/virtualNetworks/read
        on the VNet's resource group (e.g. cross-tenant / cross-team
        network RGs). `az resource show` hits the generic ARM
        Microsoft.Resources endpoint and requires broader RBAC than the
        resource-provider-specific `az network vnet show`.
    #>
    param(
        [Parameter(Mandatory)][string]$ResourceGroup,
        [Parameter(Mandatory)][string]$VnetName
    )
    $null = Invoke-Native {
        az network vnet show `
            --resource-group $ResourceGroup `
            --name $VnetName `
            --output none 2>$null
    }
    return ($LASTEXITCODE -eq 0)
}

function Resolve-VnetResourceGroupByName {
    <#
    .SYNOPSIS
        Finds the resource group for a VNet name when it is unique in the
        active subscription. Returns $null when not found or ambiguous.
    #>
    param([Parameter(Mandatory)][string]$VnetName)

    $vnetJson = Invoke-Native {
        az network vnet list --output json 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($vnetJson)) {
        return $null
    }

    try { $vnets = @($vnetJson | ConvertFrom-Json) } catch { return $null }
    $matches = @($vnets | Where-Object { $_.name -eq $VnetName })
    if ($matches.Count -eq 1) {
        return [string]$matches[0].resourceGroup
    }
    if ($matches.Count -gt 1) {
        Write-Warn "VNet name '$VnetName' exists in multiple resource groups: $((@($matches | ForEach-Object { $_.resourceGroup })) -join ', ')"
        Write-Info "Set -VnetResourceGroup or AZURE_VNET_RESOURCE_GROUP to choose one."
    }
    return $null
}

function Test-VnetSubnetExists {
    <#
    .SYNOPSIS
        True if -SubnetName exists inside -VnetName in -ResourceGroup.

        Use this instead of Test-ResourceExists for subnets  -  subnets are
        child resources, so `az resource show` requires a different shape.
    #>
    param(
        [Parameter(Mandatory)][string]$ResourceGroup,
        [Parameter(Mandatory)][string]$VnetName,
        [Parameter(Mandatory)][string]$SubnetName
    )
    $null = Invoke-Native {
        az network vnet subnet show `
            --resource-group $ResourceGroup `
            --vnet-name $VnetName `
            --name $SubnetName `
            --output none 2>$null
    }
    return ($LASTEXITCODE -eq 0)
}

function Get-LinkedPrivateDnsZoneId {
    <#
    .SYNOPSIS
        Return the resource ID of a Private DNS zone named -ZoneName that
        is already linked to -VnetId. Returns $null if no such zone is
        linked, OR if the lister hits an RBAC wall.

    .DESCRIPTION
        Azure enforces "at most one Private DNS zone per namespace per
        VNet"  -  attempting to link a second zone with the same name to
        the same VNet fails with:

            "A virtual network cannot be linked to multiple zones with
             overlapping namespaces."

        Before a per-component deploy creates a brand-new
        privatelink.<service>.<region>.azure.com zone + VNet link, it
        should ask: "Is there already a zone of that name linked to my
        target VNet?"  -  and reuse it if so.

        This is the resource-provider-specific call (`az network
        private-dns ...`)  -  same RBAC posture as Test-VnetExists /
        Test-VnetSubnetExists, so it works in shared-tenant subs where
        the existing zone lives in a network team's RG and the deployer
        only has Microsoft.Network/privateDnsZones/read scoped there.

        Implementation: list all zones across the subscription, filter
        by exact name, then per-zone enumerate virtualNetworkLinks and
        case-insensitively compare each link's virtualNetwork.id to the
        passed -VnetId.

    .PARAMETER SubscriptionId
        Subscription to search. Must already be set as the active
        subscription (call Test-AzSubscription first).

    .PARAMETER ZoneName
        Exact zone DNS name, e.g. 'privatelink.postgres.database.azure.com'.

    .PARAMETER VnetId
        Full ARM resource ID of the target VNet, e.g.
        /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{name}.
        Comparison is case-insensitive (Azure resource IDs are not
        case-sensitive in practice).

    .OUTPUTS
        [string] zone resource ID when found AND linked.
        $null otherwise.
    #>
    param(
        [Parameter(Mandatory)][string]$SubscriptionId,
        [Parameter(Mandatory)][string]$ZoneName,
        [Parameter(Mandatory)][string]$VnetId
    )

    $zonesJson = Invoke-Native {
        az network private-dns zone list `
            --subscription $SubscriptionId `
            --output json 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($zonesJson)) {
        return $null
    }
    try { $zones = @($zonesJson | ConvertFrom-Json) } catch { return $null }

    $matching = @($zones | Where-Object { $_.name -eq $ZoneName })
    foreach ($zone in $matching) {
        $zoneId = [string]$zone.id
        # /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/privateDnsZones/{name}
        $segments = $zoneId.Split('/')
        if ($segments.Length -lt 5) { continue }
        $zoneRg = $segments[4]
        $zoneNm = [string]$zone.name

        $linksJson = Invoke-Native {
            az network private-dns link vnet list `
                --subscription $SubscriptionId `
                --resource-group $zoneRg `
                --zone-name $zoneNm `
                --output json 2>$null
        }
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($linksJson)) {
            continue
        }
        try { $links = @($linksJson | ConvertFrom-Json) } catch { continue }

        foreach ($link in $links) {
            $linkVnetId = [string]$link.virtualNetwork.id
            if ($linkVnetId -ieq $VnetId) {
                return $zoneId
            }
        }
    }
    return $null
}

function Get-LinkedPostgresqlPrivateDnsZoneId {
    <#
    .SYNOPSIS
        Return a PostgreSQL Private DNS zone already linked to the supplied VNet.

    .DESCRIPTION
        PostgreSQL environments may use the standard private endpoint zone
        (privatelink.postgres.database.azure.com), the private-access zone
        (private.postgres.database.azure.com), or an environment-specific
        sub-zone ending in .private.postgres.database.azure.com. This resolver
        prefers a zone that is already linked to the target VNet over any
        unlinked same-name zone elsewhere in the subscription.
    #>
    param(
        [Parameter(Mandatory)][string]$SubscriptionId,
        [Parameter(Mandatory)][string]$VnetId,
        [string]$VnetName = '',
        [switch]$IncludeDetails
    )

    $zonesJson = Invoke-Native {
        az network private-dns zone list `
            --subscription $SubscriptionId `
            --output json 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($zonesJson)) {
        return $null
    }
    try { $zones = @($zonesJson | ConvertFrom-Json) } catch { return $null }

    $postgresZones = @($zones | Where-Object {
        $zoneName = [string]$_.name
        ($zoneName -ieq 'privatelink.postgres.database.azure.com') -or
        ($zoneName -ieq 'private.postgres.database.azure.com') -or
        ($zoneName -ilike '*.private.postgres.database.azure.com')
    })

    $linkedMatches = @()
    foreach ($zone in $postgresZones) {
        $zoneId = [string]$zone.id
        $segments = $zoneId.Split('/')
        if ($segments.Length -lt 5) { continue }
        $zoneRg = $segments[4]
        $zoneNm = [string]$zone.name

        $linksJson = Invoke-Native {
            az network private-dns link vnet list `
                --subscription $SubscriptionId `
                --resource-group $zoneRg `
                --zone-name $zoneNm `
                --output json 2>$null
        }
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($linksJson)) {
            continue
        }
        try { $links = @($linksJson | ConvertFrom-Json) } catch { continue }

        foreach ($link in $links) {
            $linkVnetId = [string]$link.virtualNetwork.id
            $linkVnetName = if ([string]::IsNullOrEmpty($linkVnetId)) { '' } else { $linkVnetId.Split('/')[-1] }
            if (($linkVnetId -ieq $VnetId) -or ((-not [string]::IsNullOrEmpty($VnetName)) -and ($linkVnetName -ieq $VnetName))) {
                $linkedMatches += [pscustomobject]@{
                    Id = $zoneId
                    Name = $zoneNm
                    VnetId = $linkVnetId
                    VnetName = $linkVnetName
                }
                break
            }
        }
    }

    if ($linkedMatches.Count -eq 0) { return $null }

    $preferred = @($linkedMatches | Where-Object { ($_.Name -ilike '*.private.postgres.database.azure.com') -and ($_.Name -ine 'private.postgres.database.azure.com') } | Select-Object -First 1)
    if ($preferred.Count -eq 0) {
        $preferred = @($linkedMatches | Where-Object { $_.Name -ieq 'private.postgres.database.azure.com' } | Select-Object -First 1)
    }
    if ($preferred.Count -eq 0) {
        $preferred = @($linkedMatches | Where-Object { $_.Name -ieq 'privatelink.postgres.database.azure.com' } | Select-Object -First 1)
    }
    if ($preferred.Count -gt 0) {
        if ($IncludeDetails) { return $preferred[0] }
        return [string]$preferred[0].Id
    }

    if ($linkedMatches.Count -eq 1) {
        if ($IncludeDetails) { return $linkedMatches[0] }
        return [string]$linkedMatches[0].Id
    }

    Write-Warn "Multiple PostgreSQL Private DNS zones are linked to the target VNet: $((@($linkedMatches | ForEach-Object { $_.Id })) -join ', ')"
    Write-Info "Set POSTGRESQL_DNS_ZONE_ID or -ExistingDnsZoneId to choose one."
    return $null
}

function Get-PrivateDnsZoneIdByName {
    <#
    .SYNOPSIS
        Return the resource ID of ANY Private DNS zone named -ZoneName
        in the subscription, regardless of whether it is linked to a
        particular VNet. Returns $null when no zone of that name exists
        (or the lister hits an RBAC wall).

    .DESCRIPTION
        Use this as the second-tier check after Get-LinkedPrivateDnsZoneId
         -  when no zone of that name is linked to the target VNet, an
        UNLINKED zone may still exist somewhere in the subscription
        (typical for fresh shared infra where the network team has
        created the zone but not yet linked it). Reuse that zone and
        let Bicep create the VNet link.

        When multiple zones with the same name exist in different
        resource groups (rare  -  happens in subs that mix per-app and
        shared private DNS), returns the FIRST one returned by Azure.
        Operators who need deterministic selection should set the
        env-var override (e.g. POSTGRESQL_DNS_ZONE_ID) instead of
        relying on auto-discovery.

    .PARAMETER SubscriptionId
        Subscription to search. Must already be set as the active
        subscription (call Test-AzSubscription first).

    .PARAMETER ZoneName
        Exact zone DNS name, e.g. 'privatelink.postgres.database.azure.com'.

    .OUTPUTS
        [string] zone resource ID when any zone with that name exists.
        $null otherwise.
    #>
    param(
        [Parameter(Mandatory)][string]$SubscriptionId,
        [Parameter(Mandatory)][string]$ZoneName
    )

    $zonesJson = Invoke-Native {
        az network private-dns zone list `
            --subscription $SubscriptionId `
            --output json 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($zonesJson)) {
        return $null
    }
    try { $zones = @($zonesJson | ConvertFrom-Json) } catch { return $null }

    $match = $zones | Where-Object { $_.name -eq $ZoneName } | Select-Object -First 1
    if ($null -eq $match) { return $null }
    return [string]$match.id
}

function Test-FoundryProject {
    <#
    .SYNOPSIS
        Validates that an Azure AI Foundry account exists, has the named
        project, and has at least one model deployment.

    .OUTPUTS
        [pscustomobject] with .Endpoint, .Deployments (string[]) on
        success. $null on failure (caller decides whether to abort).
    #>
    param(
        [Parameter(Mandatory)][string]$ResourceGroup,
        [Parameter(Mandatory)][string]$AccountName,
        [Parameter(Mandatory)][string]$ProjectName
    )

    # 1. Account.
    $acctJson = Invoke-Native {
        az cognitiveservices account show `
            --resource-group $ResourceGroup `
            --name $AccountName `
            --output json 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($acctJson)) {
        Write-Fail "Foundry account '$AccountName' not found in '$ResourceGroup'."
        return $null
    }
    $acct = $acctJson | ConvertFrom-Json
    $endpoint = $acct.properties.endpoint

    # 2. Project (Foundry projects use the cognitiveservices/accounts/projects
    # subresource; query directly via REST/CLI). The project list call is
    # only available on AIServices SKUs.
    $projJson = Invoke-Native {
        az resource show `
            --resource-group $ResourceGroup `
            --resource-type "Microsoft.CognitiveServices/accounts/projects" `
            --name "$AccountName/$ProjectName" `
            --api-version 2025-04-01-preview `
            --output json 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($projJson)) {
        Write-Fail "Foundry project '$ProjectName' not found under account '$AccountName'."
        return $null
    }

    # 3. Model deployments.
    $depsJson = Invoke-Native {
        az cognitiveservices account deployment list `
            --resource-group $ResourceGroup `
            --name $AccountName `
            --output json 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($depsJson)) {
        Write-Fail "Could not list model deployments on '$AccountName'."
        return $null
    }
    $deps = @($depsJson | ConvertFrom-Json)
    if ($deps.Count -eq 0) {
        Write-Fail "Foundry account '$AccountName' has no model deployments. Deploy at least gpt-4.1 and text-embedding-ada-002 before continuing."
        return $null
    }

    $depNames = @($deps | ForEach-Object { $_.name })
    Write-Success "Foundry: account=$AccountName project=$ProjectName endpoint=$endpoint"
    Write-Info "Deployments: $($depNames -join ', ')"

    return [pscustomobject]@{
        Endpoint    = $endpoint
        Deployments = $depNames
        AccountId   = $acct.id
    }
}

# ------------------------------------------------------------------------------
# ACR helpers
# ------------------------------------------------------------------------------

function Get-AcrLoginServer {
    <#
    .SYNOPSIS
        Returns the loginServer string (e.g. 'acrxyz.azurecr.io') for an
        existing ACR. Returns $null if not found.
    #>
    param(
        [Parameter(Mandatory)][string]$ResourceGroup,
        [Parameter(Mandatory)][string]$AcrName
    )
    $login = (Invoke-Native {
        az acr show `
            --resource-group $ResourceGroup `
            --name $AcrName `
            --query loginServer -o tsv 2>$null `
        | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
    }) -join ""
    $login = $login.Trim()
    if ([string]::IsNullOrEmpty($login)) {
        return $null
    }
    return $login
}

# ------------------------------------------------------------------------------
# Interactive confirmation
# ------------------------------------------------------------------------------

function Confirm-Action {
    <#
    .SYNOPSIS
        y/N prompt. Returns $true when the user confirms.

        Auto-confirms (returns $true) when EITHER:
          * The -Force switch is supplied.
          * The CI env var is set (any value)  -  common CI convention.

        Auto-denies (returns $false) when running non-interactively with
        no -Force and no CI env var, to avoid hanging in pipelines.
    #>
    param(
        [Parameter(Mandatory)][string]$Message,
        [switch]$Force
    )
    if ($Force) {
        Write-Info "Auto-confirmed (-Force): $Message"
        return $true
    }
    if (-not [string]::IsNullOrEmpty($env:CI)) {
        Write-Info "Auto-confirmed (`$env:CI is set): $Message"
        return $true
    }
    if (-not [Environment]::UserInteractive) {
        Write-Warn "Non-interactive session and no -Force / `$env:CI  -  denying: $Message"
        return $false
    }

    $ans = Read-Host -Prompt "$Message [y/N]"
    return ($ans -match '^(y|yes)$')
}

# ------------------------------------------------------------------------------
# Convenience: bulk-verify pre-existing infrastructure
# ------------------------------------------------------------------------------

function Assert-PrerequisitesExist {
    <#
    .SYNOPSIS
        Verifies a hashtable of expected resources all exist. Aborts the
        script if any are missing.

    .PARAMETER ResourceGroup
        Resource group that should contain the resources (subnet checks
        always use -VnetResourceGroup if supplied, otherwise this RG).

    .PARAMETER VnetResourceGroup
        Optional  -  RG holding the VNet (if different from -ResourceGroup).
        Subnet checks query against this RG.

    .PARAMETER Checks
        Array of hashtables. Each entry has:
          Type   = 'rg' | 'vnet' | 'subnet' | 'containerappenv' | 'acr' |
                   'postgres' | 'foundry' | 'cosmos' | 'keyvault' | 'uami' |
                   any other Azure resource-type string
          Name   = the resource's name
          Vnet   = (subnet only) parent vnet name
          Label  = display label for log output (optional, defaults to Name)

    .EXAMPLE
        Assert-PrerequisitesExist -ResourceGroup 'rg-talent-prod' -VnetResourceGroup 'rg-network' -Checks @(
            @{ Type='rg';              Name='rg-talent-prod' },
            @{ Type='vnet';            Name='vnet-prod' },
            @{ Type='subnet';          Vnet='vnet-prod'; Name='aca-subnet' },
            @{ Type='subnet';          Vnet='vnet-prod'; Name='pe-subnet' },
            @{ Type='containerappenv'; Name='cae-prod' },
            @{ Type='acr';             Name='acrprod001' },
            @{ Type='foundry';         Name='aif-prod' }
        )
    #>
    param(
        [Parameter(Mandatory)][string]$ResourceGroup,
        [string]$VnetResourceGroup = "",
        [Parameter(Mandatory)][array]$Checks
    )

    Write-Step "Verifying pre-existing infrastructure"
    $vnetRg = if ([string]::IsNullOrEmpty($VnetResourceGroup)) { $ResourceGroup } else { $VnetResourceGroup }
    $missing = @()

    foreach ($c in $Checks) {
        $type   = [string]$c.Type
        $name   = [string]$c.Name
        $label  = if ($c.Label) { [string]$c.Label } else { "$type/$name" }

        switch ($type.ToLower()) {
            'rg' {
                if (Test-ResourceGroup -Name $name) {
                    Write-Success "RG $name"
                } else {
                    Write-Fail "RG $name not found"
                    $missing += $label
                }
            }
            'subnet' {
                if (Test-VnetSubnetExists -ResourceGroup $vnetRg -VnetName $c.Vnet -SubnetName $name) {
                    Write-Success "Subnet $($c.Vnet)/$name"
                } else {
                    Write-Fail "Subnet $($c.Vnet)/$name not found in RG $vnetRg"
                    $missing += $label
                }
            }
            'vnet' {
                if (Test-VnetExists -ResourceGroup $vnetRg -VnetName $name) {
                    Write-Success "VNet $name"
                } else {
                    Write-Fail "VNet $name not found in RG $vnetRg"
                    $missing += $label
                }
            }
            default {
                if (Test-ResourceExists -ResourceGroup $ResourceGroup -ResourceType $type -Name $name) {
                    Write-Success "$type $name"
                } else {
                    Write-Fail "$type $name not found in RG $ResourceGroup"
                    $missing += $label
                }
            }
        }
    }

    if ($missing.Count -gt 0) {
        Write-Host ""
        Write-Fail "$($missing.Count) pre-existing resource(s) missing:"
        foreach ($m in $missing) { Write-Host "      - $m" -ForegroundColor Red }
        Write-Host ""
        Write-Host "These scripts assume RG / VNet / ACA env / ACR / Foundry already exist." -ForegroundColor Yellow
        Write-Host "Provision the missing resources first (or use talent_infra_v2/ for full-stack azd deployment)." -ForegroundColor Yellow
        exit 1
    }
}
