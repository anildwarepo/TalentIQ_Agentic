<#
.SYNOPSIS
    talent_infra_modules / 02-backend  -  build, push, and deploy the
    TalentIQ backend Container App with the MCP server as a sidecar.

.DESCRIPTION
    Read 02-backend/README.md, ../AUTH-DISABLED.md, and
    ../DEPLOYMENT-ORDER.md for the full contract. This script:

      1. Reads PG connection info from 01-postgresql/.outputs.json.
      2. Verifies pre-existing infra (RG, ACR, ACA env, Foundry).
      3. Builds + pushes two ACR images: backend, mcp-server.
      4. Resolves the Foundry endpoint via az.
      5. Deploys infra/main.bicep  -  one Container App with two
         containers (backend + mcp-server sidecar) sharing one UAMI.
      6. Registers the new UAMI as a PG Entra ServicePrincipal admin
         via control-plane API (display-name MUST equal UAMI name).
      7. Optionally restarts the active revision so the MCP client's
         cached Mcp-Session-Id is flushed.
      8. Emits .outputs.json for 03-frontend/deploy.ps1 to read.

    Idempotent. Re-runnable. Failures are loud and instructive.

.NOTES
    Auth-disable contract: AZURE_TENANT_ID is NEVER set on either
    container  -  talent_backend/auth.py short-circuits to dev mode
    without it. See ../AUTH-DISABLED.md.
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$Location = "westus",

    [string]$AcrName,
    [string]$AcrResourceGroup,
    [string]$ContainerAppsEnvironmentId,
    [string]$ContainerAppsEnvName,
    [string]$ContainerAppsEnvResourceGroup,

    [string]$BackendAppName,
    [string]$BackendImageTag = "latest",
    [string]$McpImageTag = "latest",

    [string]$FoundryAccountName,
    [string]$FoundryResourceGroup,
    [string]$FoundryProjectName,
    [string]$ChatModelDeployment = "gpt-4.1",

    [string]$CosmosAccountName,
    [string]$CosmosResourceGroup,
    [string]$CosmosDatabase = "talent_db",
    [string]$CosmosContainer = "chat_history_db",

    [string]$AppInsightsConnectionString,

    [string]$PostgresqlResourceGroup,
    [string]$PostgresqlOutputsFile,

    [string]$BackendSourcePath = "..\..\talent_backend",
    [string]$BackendCpu = "0.5",
    [string]$BackendMemory = "1Gi",
    [string]$McpCpu = "0.5",
    [string]$McpMemory = "1Gi",

    [switch]$SkipBuild,
    [switch]$Force,
    [switch]$RestartActive
)

# ------------------------------------------------------------------------------
# Bootstrapping
# ------------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here "..\shared\common.ps1")

Show-AppConfigEnvPreflight -Import -Override -Force:$Force

Write-Host ""
Write-Host "--------------------------------------------------------------"
Write-Host " 02-backend  -  Backend + MCP sidecar deployment"
Write-Host "--------------------------------------------------------------"
Write-Host ""

# ------------------------------------------------------------------------------
# 1. Az sign-in
# ------------------------------------------------------------------------------

$null = Test-AzLoggedIn

# ------------------------------------------------------------------------------
# 2. Read 01-postgresql/.outputs.json
# ------------------------------------------------------------------------------

Write-Step "Reading 01-postgresql outputs"

if ([string]::IsNullOrEmpty($PostgresqlOutputsFile)) {
    $PostgresqlOutputsFile = Join-Path $here "..\01-postgresql\.outputs.json"
}
$PostgresqlOutputsFile = (Resolve-Path -LiteralPath $PostgresqlOutputsFile -ErrorAction SilentlyContinue)?.Path `
    ?? $PostgresqlOutputsFile

if (-not (Test-Path -LiteralPath $PostgresqlOutputsFile)) {
    Write-Fail "01-postgresql outputs not found: $PostgresqlOutputsFile"
    Write-Info "Run ../01-postgresql/deploy.ps1 first, OR see ../DEPLOYMENT-ORDER.md"
    Write-Info "for the schema needed to synthesize this file when PG already exists."
    exit 1
}

$pgOutputs = Get-Content -LiteralPath $PostgresqlOutputsFile -Raw | ConvertFrom-Json
$pgServerName = [string]$pgOutputs.postgresqlServerName
$pgServerFqdn = [string]$pgOutputs.postgresqlServerFqdn
$pgPrivateFqdn = [string]$pgOutputs.postgresqlPrivateFqdn
$pgPrivateIp = if ($pgOutputs.PSObject.Properties.Name -contains 'postgresqlPrivateIp') {
    [string]$pgOutputs.postgresqlPrivateIp
} else { "" }

if ([string]::IsNullOrEmpty($pgServerName) -or [string]::IsNullOrEmpty($pgServerFqdn)) {
    Write-Fail "01-postgresql outputs are missing required keys (postgresqlServerName, postgresqlServerFqdn)."
    exit 1
}

# Prefer the privatelink FQDN whenever PE is in use (i.e. postgresqlPrivateIp
# is present and non-empty). The container apps live in the VNet and resolve
# the privatelink CNAME to the private IP via Azure DNS.
$pgFqdn = if ((-not [string]::IsNullOrEmpty($pgPrivateIp)) -and (-not [string]::IsNullOrEmpty($pgPrivateFqdn))) {
    $pgPrivateFqdn
} else {
    $pgServerFqdn
}

Write-Success "PG server: $pgServerName"
Write-Info "FQDN used: $pgFqdn"
if (-not [string]::IsNullOrEmpty($pgPrivateIp)) {
    Write-Info "Private IP (PE detected): $pgPrivateIp"
}

# ------------------------------------------------------------------------------
# 3. Resolve required parameters
# ------------------------------------------------------------------------------

$SubscriptionId = Resolve-AzSubscriptionId -Value $SubscriptionId -EnvVar 'AZURE_SUBSCRIPTION_ID'
$ResourceGroup = Resolve-AzResourceGroupName -SubscriptionId $SubscriptionId -Name 'Resource group' -EnvVar 'AZURE_RESOURCE_GROUP' -Value $ResourceGroup
$Location = Get-ParameterValue -Name 'Location' -EnvVar 'AZURE_LOCATION' -Value $Location -Default 'westus'
$AcrName = Get-ParameterValue -Name 'ACR name' -EnvVar 'AZURE_ACR_NAME' -Value $AcrName

# Soft fallback: read 00-container-apps-env/.outputs.json when the ACA env
# name (and its RG) were not supplied via -ContainerAppsEnvName /
# -ContainerAppsEnvResourceGroup / -ContainerAppsEnvironmentId or
# AZURE_ACA_ENV_NAME / AZURE_ACA_ENV_RESOURCE_GROUP / AZURE_ACA_ENV_ID.
# This makes `00 -> 02` a one-shot hand-off without forcing operators to
# copy values by hand. Never fails if the file is missing.
if ([string]::IsNullOrEmpty($ContainerAppsEnvironmentId) `
        -and [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('AZURE_ACA_ENV_ID')) `
        -and [string]::IsNullOrEmpty($ContainerAppsEnvName) `
        -and [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('AZURE_ACA_ENV_NAME'))) {
    $caeOutputsPath = Join-Path $PSScriptRoot "..\00-container-apps-env\.outputs.json"
    if (Test-Path $caeOutputsPath) {
        try {
            $caeOutputs = Get-Content -LiteralPath $caeOutputsPath -Raw | ConvertFrom-Json
            $caeOutputSubscriptionId = ""
            if ($caeOutputs -and $caeOutputs.PSObject.Properties.Name -contains 'containerAppsEnvId') {
                $match = [regex]::Match([string]$caeOutputs.containerAppsEnvId, '/subscriptions/([^/]+)/', 'IgnoreCase')
                if ($match.Success) { $caeOutputSubscriptionId = $match.Groups[1].Value }
            }
            if (-not [string]::IsNullOrEmpty($caeOutputSubscriptionId) -and $caeOutputSubscriptionId -ne $SubscriptionId) {
                Write-Warn "Ignoring 00-container-apps-env/.outputs.json because it targets subscription $caeOutputSubscriptionId, not $SubscriptionId."
            } elseif ($caeOutputs -and -not [string]::IsNullOrEmpty($caeOutputs.containerAppsEnvId)) {
                $ContainerAppsEnvironmentId = [string]$caeOutputs.containerAppsEnvId
                Write-Info "Container Apps environment ID = (from 00-container-apps-env/.outputs.json)"
            } elseif ($caeOutputs -and -not [string]::IsNullOrEmpty($caeOutputs.containerAppsEnvName)) {
                $ContainerAppsEnvName = [string]$caeOutputs.containerAppsEnvName
                Write-Info "Container Apps environment name = (from 00-container-apps-env/.outputs.json)"
                if ([string]::IsNullOrEmpty($ContainerAppsEnvResourceGroup) `
                        -and [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('AZURE_ACA_ENV_RESOURCE_GROUP')) `
                        -and -not [string]::IsNullOrEmpty($caeOutputs.containerAppsEnvResourceGroup)) {
                    $ContainerAppsEnvResourceGroup = [string]$caeOutputs.containerAppsEnvResourceGroup
                    Write-Info "Container Apps environment RG = (from 00-container-apps-env/.outputs.json)"
                }
            }
        } catch {
            Write-Warn "Could not parse $caeOutputsPath; falling back to prompt."
        }
    }
}

$envContainerAppsEnvironmentId = Get-ProcessEnvValue -Name 'AZURE_ACA_ENV_ID'
if ([string]::IsNullOrEmpty($ContainerAppsEnvironmentId) -and -not [string]::IsNullOrEmpty($envContainerAppsEnvironmentId)) {
    $ContainerAppsEnvironmentId = $envContainerAppsEnvironmentId
    Write-Info "Container Apps environment resource ID = (from `$env:AZURE_ACA_ENV_ID)"
}
if ([string]::IsNullOrEmpty($ContainerAppsEnvironmentId)) {
    $ContainerAppsEnvName = Get-ParameterValue -Name 'Container Apps environment name' -EnvVar 'AZURE_ACA_ENV_NAME' -Value $ContainerAppsEnvName
}
$FoundryAccountName = Get-ParameterValue -Name 'Foundry account name' -EnvVar 'FOUNDRY_ACCOUNT_NAME' -Value $FoundryAccountName
$FoundryProjectName = Get-ParameterValue -Name 'Foundry project name' -EnvVar 'FOUNDRY_PROJECT_NAME' -Value $FoundryProjectName -Default 'talentiq'
if (-not $PSBoundParameters.ContainsKey('ChatModelDeployment')) {
    $envChatModelDeployment = Get-ProcessEnvValue -Name 'FOUNDRY_CHAT_DEPLOYMENT_NAME'
    if (-not [string]::IsNullOrEmpty($envChatModelDeployment)) {
        $ChatModelDeployment = $envChatModelDeployment
        Write-Info "Chat model deployment = (from `$env:FOUNDRY_CHAT_DEPLOYMENT_NAME)"
    }
}

# Default secondary RGs to the main RG.
if ([string]::IsNullOrEmpty($AcrResourceGroup)) { $AcrResourceGroup = $ResourceGroup }
if ([string]::IsNullOrEmpty($ContainerAppsEnvResourceGroup) -and [string]::IsNullOrEmpty($ContainerAppsEnvironmentId)) { $ContainerAppsEnvResourceGroup = $ResourceGroup }
if ([string]::IsNullOrEmpty($FoundryResourceGroup)) { $FoundryResourceGroup = $ResourceGroup }
if ([string]::IsNullOrEmpty($CosmosResourceGroup)) { $CosmosResourceGroup = $ResourceGroup }
if ([string]::IsNullOrEmpty($PostgresqlResourceGroup)) { $PostgresqlResourceGroup = $ResourceGroup }

# Bicep main.bicep requires ACR + Foundry + Cosmos to be in the deployment RG
# (inline existing refs + role assignments). Cross-RG deploys would need
# sub-modules per scope  -  out of scope for this MVP.
$crossRgFatal = $false
if ($AcrResourceGroup -ne $ResourceGroup) {
    Write-Fail "AcrResourceGroup ($AcrResourceGroup) differs from ResourceGroup ($ResourceGroup)."
    Write-Info "talent_infra_modules/02-backend requires ACR in the deployment RG."
    $crossRgFatal = $true
}
if ($FoundryResourceGroup -ne $ResourceGroup) {
    Write-Fail "FoundryResourceGroup ($FoundryResourceGroup) differs from ResourceGroup ($ResourceGroup)."
    Write-Info "talent_infra_modules/02-backend requires the Foundry account in the deployment RG."
    $crossRgFatal = $true
}
if (-not [string]::IsNullOrEmpty($CosmosAccountName) -and $CosmosResourceGroup -ne $ResourceGroup) {
    Write-Fail "CosmosResourceGroup ($CosmosResourceGroup) differs from ResourceGroup ($ResourceGroup)."
    Write-Info "talent_infra_modules/02-backend requires the Cosmos account in the deployment RG."
    $crossRgFatal = $true
}
if ($crossRgFatal) {
    Write-Info ""
    Write-Info "Use talent_infra_v2/ for full-stack azd deployment with cross-RG support."
    exit 1
}

# Stable per-(subscription,RG) BackendAppName when the operator did not pin one.
if ([string]::IsNullOrEmpty($BackendAppName)) {
    $envBackend = [Environment]::GetEnvironmentVariable('BACKEND_CONTAINER_APP_NAME')
    if (-not [string]::IsNullOrEmpty($envBackend)) {
        $BackendAppName = $envBackend
    } else {
        $hashInput = "$SubscriptionId|$ResourceGroup|backend"
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($hashInput)
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $hash = $sha.ComputeHash($bytes)
        } finally { $sha.Dispose() }
        $shortHash = ([System.BitConverter]::ToString($hash) -replace '-', '').ToLower().Substring(0, 5)
        $BackendAppName = "tiq-backend-$shortHash"
    }
}

# Container Apps names: 2-32 chars, lower alphanumerics + hyphens, must
# start with letter and end with alphanumeric.
if ($BackendAppName.Length -gt 32) {
    Write-Fail "BackendAppName '$BackendAppName' exceeds the 32-char Container App name limit."
    exit 1
}
if ($BackendAppName -notmatch '^[a-z][a-z0-9-]*[a-z0-9]$') {
    Write-Fail "BackendAppName '$BackendAppName' is not a valid Container App name (lower-case, hyphens, must start with letter)."
    exit 1
}

# ------------------------------------------------------------------------------
# 4. Set subscription
# ------------------------------------------------------------------------------

Test-AzSubscription -SubscriptionId $SubscriptionId

# ------------------------------------------------------------------------------
# 5. Prerequisite checks
# ------------------------------------------------------------------------------

$checks = @(
    @{ Type = 'rg';              Name = $ResourceGroup },
    @{ Type = 'acr';             Name = $AcrName }
)
if (-not [string]::IsNullOrEmpty($CosmosAccountName)) {
    $checks += @{ Type = 'cosmos'; Name = $CosmosAccountName }
}

Assert-PrerequisitesExist -ResourceGroup $ResourceGroup -Checks $checks

Write-Step "Resolving Container Apps environment resource ID"
if ([string]::IsNullOrEmpty($ContainerAppsEnvironmentId)) {
    $ContainerAppsEnvResourceGroup = Get-ParameterValue -Name 'Container Apps environment resource group' -EnvVar 'AZURE_ACA_ENV_RESOURCE_GROUP' -Value $ContainerAppsEnvResourceGroup -Default $ResourceGroup
    $ContainerAppsEnvironmentId = (Invoke-Native {
        az containerapp env show `
            --resource-group $ContainerAppsEnvResourceGroup `
            --name $ContainerAppsEnvName `
            --query id -o tsv 2>$null `
        | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
    }) -join ""
    $ContainerAppsEnvironmentId = $ContainerAppsEnvironmentId.Trim()
    if ([string]::IsNullOrEmpty($ContainerAppsEnvironmentId)) {
        Write-Fail "Container Apps environment '$ContainerAppsEnvName' not found in RG '$ContainerAppsEnvResourceGroup'."
        Write-Info "Pass -ContainerAppsEnvironmentId <resource-id>, or pass both -ContainerAppsEnvName and -ContainerAppsEnvResourceGroup."
        exit 1
    }
} else {
    $ContainerAppsEnvironmentId = $ContainerAppsEnvironmentId.Trim()
    $idMatch = [regex]::Match($ContainerAppsEnvironmentId, '^/subscriptions/[^/]+/resourceGroups/([^/]+)/providers/Microsoft\.App/managedEnvironments/([^/]+)$', 'IgnoreCase')
    if ($idMatch.Success) {
        $ContainerAppsEnvResourceGroup = $idMatch.Groups[1].Value
        $ContainerAppsEnvName = $idMatch.Groups[2].Value
    } else {
        Write-Fail "ContainerAppsEnvironmentId is not a valid Microsoft.App/managedEnvironments resource ID."
        exit 1
    }
}
Write-Success "ACA env ID: $ContainerAppsEnvironmentId"

# Foundry account + project + at least one model deployment.
$foundry = Test-FoundryProject `
    -ResourceGroup $FoundryResourceGroup `
    -AccountName $FoundryAccountName `
    -ProjectName $FoundryProjectName
if ($null -eq $foundry) {
    Write-Fail "Foundry validation failed. Aborting."
    exit 1
}

if (-not ($foundry.Deployments -contains $ChatModelDeployment)) {
    Write-Fail "Foundry account '$FoundryAccountName' has no deployment named '$ChatModelDeployment'."
    Write-Info "Available deployments: $($foundry.Deployments -join ', ')"
    Write-Info "Either deploy '$ChatModelDeployment' or pass -ChatModelDeployment <existing>."
    exit 1
}

# Resolve ACR loginServer + Container Apps env id for the bicep deploy.
$acrLoginServer = Get-AcrLoginServer -ResourceGroup $AcrResourceGroup -AcrName $AcrName
if ([string]::IsNullOrEmpty($acrLoginServer)) {
    Write-Fail "Could not resolve ACR login server for '$AcrName'."
    exit 1
}
Write-Success "ACR login server: $acrLoginServer"

# ------------------------------------------------------------------------------
# 6. Show summary + confirm
# ------------------------------------------------------------------------------

$backendImage = "$acrLoginServer/backend:$BackendImageTag"
$mcpImage = "$acrLoginServer/mcp-server:$McpImageTag"

Write-Step "Deployment plan"
Write-Info "Subscription           : $SubscriptionId"
Write-Info "Resource group         : $ResourceGroup"
Write-Info "Location               : $Location"
Write-Info "Backend Container App  : $BackendAppName"
Write-Info "Backend image          : $backendImage"
Write-Info "MCP sidecar image      : $mcpImage"
Write-Info "ACR                    : $AcrName ($AcrResourceGroup)"
Write-Info "ACA environment        : $ContainerAppsEnvName ($ContainerAppsEnvResourceGroup)"
Write-Info "PostgreSQL FQDN        : $pgFqdn"
Write-Info "PostgreSQL server name : $pgServerName"
Write-Info "Foundry account        : $FoundryAccountName ($FoundryResourceGroup)"
Write-Info "Foundry endpoint       : $($foundry.Endpoint)"
Write-Info "Chat model deployment  : $ChatModelDeployment"
if ([string]::IsNullOrEmpty($CosmosAccountName)) {
    Write-Info "Cosmos                 : (disabled  -  no account supplied)"
} else {
    Write-Info "Cosmos account         : $CosmosAccountName ($CosmosResourceGroup)"
}
if ($SkipBuild) {
    Write-Warn "-SkipBuild set: assuming both images already exist with the supplied tags."
}
if ($RestartActive) {
    Write-Info "Post-deploy revision restart: ENABLED"
}
Write-Warn "AZURE_TENANT_ID will NOT be set on either container (auth-disable contract)."

if (-not (Confirm-Action -Message "Proceed with deployment?" -Force:$Force)) {
    Write-Warn "User cancelled. No changes made."
    exit 0
}

# ------------------------------------------------------------------------------
# 7. Build + push images via az acr build
# ------------------------------------------------------------------------------

if (-not $SkipBuild) {
    Write-Step "Building + pushing backend image"

    $backendSourceResolved = (Resolve-Path -LiteralPath (Join-Path $here $BackendSourcePath) -ErrorAction SilentlyContinue)?.Path
    if ([string]::IsNullOrEmpty($backendSourceResolved)) {
        Write-Fail "BackendSourcePath '$BackendSourcePath' does not exist."
        exit 1
    }
    $backendDockerfilePath = Join-Path $backendSourceResolved 'Dockerfile'
    $mcpDockerfilePath = Join-Path $backendSourceResolved 'Dockerfile.mcp'

    if (-not (Test-Path $backendDockerfilePath)) {
        Write-Fail "No Dockerfile found at $backendSourceResolved"
        exit 1
    }
    if (-not (Test-Path $mcpDockerfilePath)) {
        Write-Fail "No Dockerfile.mcp found at $backendSourceResolved"
        exit 1
    }

    Write-Info "Source: $backendSourceResolved"
    Write-Info "Target: $backendImage"
    Invoke-Native {
        az acr build `
            --registry $AcrName `
            --resource-group $AcrResourceGroup `
            --image "backend:$BackendImageTag" `
            --file $backendDockerfilePath `
            $backendSourceResolved
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "az acr build (backend) failed with exit code $LASTEXITCODE."
        exit 1
    }
    Write-Success "Built and pushed $backendImage"

    Write-Step "Building + pushing MCP sidecar image"
    Write-Info "Target: $mcpImage"
    Invoke-Native {
        az acr build `
            --registry $AcrName `
            --resource-group $AcrResourceGroup `
            --image "mcp-server:$McpImageTag" `
            --file $mcpDockerfilePath `
            $backendSourceResolved
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "az acr build (mcp-server) failed with exit code $LASTEXITCODE."
        exit 1
    }
    Write-Success "Built and pushed $mcpImage"
} else {
    Write-Step "Skipping image build (-SkipBuild)"
    Write-Info "Assuming $backendImage and $mcpImage already exist in $AcrName."
}

# ------------------------------------------------------------------------------
# 8. Deploy main.bicep
# ------------------------------------------------------------------------------

Write-Step "Deploying Container App + sidecar via Bicep"

$bicepPath = Join-Path $here 'infra\main.bicep'
$paramsPath = Join-Path $here 'infra\main.parameters.json'

if (-not (Test-Path $bicepPath)) {
    Write-Fail "Missing $bicepPath"
    exit 1
}
if (-not (Test-Path $paramsPath)) {
    Write-Fail "Missing $paramsPath"
    exit 1
}

$deploymentName = "02-backend-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"

# Compose the parameter override args. Each --parameters key=value overrides
# the value in the parameters JSON. CLI gobbles unquoted spaces, so build the
# argument list explicitly.
$paramOverrides = @(
    "location=$Location",
    "backendAppName=$BackendAppName",
    "backendImage=$backendImage",
    "mcpImage=$mcpImage",
    "containerAppsEnvironmentId=$ContainerAppsEnvironmentId",
    "acrName=$AcrName",
    "pgFqdn=$pgFqdn",
    "graphName=talent_graph",
    "foundryEndpoint=$($foundry.Endpoint)",
    "foundryAccountName=$FoundryAccountName",
    "chatModelDeployment=$ChatModelDeployment",
    "cosmosDatabase=$CosmosDatabase",
    "cosmosContainer=$CosmosContainer",
    "backendCpu=$BackendCpu",
    "backendMemory=$BackendMemory",
    "mcpCpu=$McpCpu",
    "mcpMemory=$McpMemory"
)
if (-not [string]::IsNullOrEmpty($CosmosAccountName)) {
    # Resolve the Cosmos endpoint from az so the operator does not have to
    # pass it explicitly.
    $cosmosEndpoint = (Invoke-Native {
        az cosmosdb show `
            --resource-group $CosmosResourceGroup `
            --name $CosmosAccountName `
            --query documentEndpoint -o tsv 2>$null `
        | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
    }) -join ""
    $cosmosEndpoint = $cosmosEndpoint.Trim()
    if ([string]::IsNullOrEmpty($cosmosEndpoint)) {
        Write-Fail "Could not resolve Cosmos endpoint for account '$CosmosAccountName'."
        exit 1
    }
    $paramOverrides += "cosmosEndpoint=$cosmosEndpoint"
    $paramOverrides += "cosmosAccountName=$CosmosAccountName"
}
if (-not [string]::IsNullOrEmpty($AppInsightsConnectionString)) {
    $paramOverrides += "appInsightsConnectionString=$AppInsightsConnectionString"
}

Write-Info "Deployment name: $deploymentName"

# Build the az invocation in pieces so each --parameters override is its own
# argv slot. PowerShell splatting on native commands needs an @() array.
$azArgs = @(
    'deployment', 'group', 'create',
    '--resource-group', $ResourceGroup,
    '--name', $deploymentName,
    '--template-file', $bicepPath,
    '--parameters', $paramsPath
)
foreach ($p in $paramOverrides) {
    $azArgs += '--parameters'
    $azArgs += $p
}
$azArgs += @('--output', 'json')

$deployJson = Invoke-Native { az @azArgs }
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Bicep deployment failed with exit code $LASTEXITCODE."
    if (-not [string]::IsNullOrEmpty($deployJson)) {
        Write-Host $deployJson
    }
    exit 1
}

$deployment = $deployJson | ConvertFrom-Json
$outputs = $deployment.properties.outputs
if ($null -eq $outputs) {
    Write-Fail "Bicep deployment returned no outputs. Aborting."
    exit 1
}

$backendContainerAppName = [string]$outputs.backendContainerAppName.value
$backendContainerAppFqdn = [string]$outputs.backendContainerAppFqdn.value
$backendUamiName = [string]$outputs.backendUamiName.value
$backendUamiClientId = [string]$outputs.backendUamiClientId.value
$backendUamiPrincipalId = [string]$outputs.backendUamiPrincipalId.value
$backendLatestRevisionName = if ($outputs.PSObject.Properties.Name -contains 'backendLatestRevisionName') {
    [string]$outputs.backendLatestRevisionName.value
} else { "" }

Write-Success "Container App: $backendContainerAppName"
Write-Info "FQDN          : https://$backendContainerAppFqdn"
Write-Info "UAMI name     : $backendUamiName"
Write-Info "UAMI clientId : $backendUamiClientId"
Write-Info "UAMI principal: $backendUamiPrincipalId"

# ------------------------------------------------------------------------------
# 9. Post-deploy PG Entra admin registration (control plane)
# ------------------------------------------------------------------------------

Write-Step "Registering UAMI as PG Entra ServicePrincipal admin"

# Display-name MUST equal the UAMI name (that's the PG username the app uses).
# Idempotent: az returns "already exists" non-zero, so we list first.
$existingAdminsJson = Invoke-Native {
    az postgres flexible-server ad-admin list `
        --resource-group $PostgresqlResourceGroup `
        --server-name $pgServerName `
        --output json 2>$null
}
$alreadyRegistered = $false
if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($existingAdminsJson)) {
    try {
        $existingAdmins = @($existingAdminsJson | ConvertFrom-Json)
        foreach ($admin in $existingAdmins) {
            $adminOid = if ($admin.PSObject.Properties.Name -contains 'objectId') { [string]$admin.objectId } else { '' }
            $adminSid = if ($admin.PSObject.Properties.Name -contains 'sid') { [string]$admin.sid } else { '' }
            if ($adminOid -eq $backendUamiPrincipalId -or $adminSid -eq $backendUamiPrincipalId) {
                $alreadyRegistered = $true
                break
            }
        }
    } catch {
        Write-Warn "Could not parse existing PG admin list  -  will attempt registration anyway."
    }
}

if ($alreadyRegistered) {
    Write-Success "UAMI already registered as PG Entra admin."
} else {
    Invoke-Native {
        az postgres flexible-server microsoft-entra-admin create `
            --resource-group $PostgresqlResourceGroup `
            --server-name $pgServerName `
            --display-name $backendUamiName `
            --object-id $backendUamiPrincipalId `
            --type 'ServicePrincipal' `
            --output none 2>&1 | Out-String | Write-Verbose
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "PG Entra admin registration failed with exit code $LASTEXITCODE."
        Write-Info "Backend will fail to connect to PG until this UAMI is registered."
        Write-Info "Retry with: az postgres flexible-server microsoft-entra-admin create -g $PostgresqlResourceGroup -s $pgServerName --display-name $backendUamiName --object-id $backendUamiPrincipalId --type ServicePrincipal"
        exit 1
    }
    Write-Success "Registered $backendUamiName as PG Entra admin."
}

# ------------------------------------------------------------------------------
# 10. Optional revision restart
# ------------------------------------------------------------------------------

if ($RestartActive) {
    Write-Step "Restarting active revision"

    # Resolve the current active revision in case the bicep output was
    # the pre-update revision name.
    $activeRevision = (Invoke-Native {
        az containerapp revision list `
            --resource-group $ResourceGroup `
            --name $backendContainerAppName `
            --query "[?properties.active].name | [0]" -o tsv 2>$null `
        | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
    }) -join ""
    $activeRevision = $activeRevision.Trim()
    if ([string]::IsNullOrEmpty($activeRevision)) {
        $activeRevision = $backendLatestRevisionName
    }
    if ([string]::IsNullOrEmpty($activeRevision)) {
        Write-Warn "Could not resolve an active revision to restart. Skipping."
    } else {
        Write-Info "Restarting revision: $activeRevision"
        Invoke-Native {
            az containerapp revision restart `
                --resource-group $ResourceGroup `
                --name $backendContainerAppName `
                --revision $activeRevision `
                --output none 2>&1 | Out-String | Write-Verbose
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Revision restart returned exit code $LASTEXITCODE (continuing)."
        } else {
            Write-Success "Restarted $activeRevision"
        }
    }
}

# ------------------------------------------------------------------------------
# 11. Emit .outputs.json
# ------------------------------------------------------------------------------

Write-Step "Writing .outputs.json"

$outputsPayload = [ordered]@{
    backendContainerAppName = $backendContainerAppName
    backendContainerAppFqdn = $backendContainerAppFqdn
    backendUamiName         = $backendUamiName
    backendUamiClientId     = $backendUamiClientId
    backendUamiPrincipalId  = $backendUamiPrincipalId
    mcpServerImage          = $mcpImage
    backendImage            = $backendImage
}

$outputsFile = Join-Path $here '.outputs.json'
$outputsPayload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $outputsFile -Encoding UTF8
Write-Success "Wrote $outputsFile"

# ------------------------------------------------------------------------------
# 12. What next
# ------------------------------------------------------------------------------

Write-Host ""
Write-Host "--------------------------------------------------------------"
Write-Host " [OK] 02-backend deployment complete"
Write-Host "--------------------------------------------------------------"
Write-Host ""
Write-Host "Backend URL : https://$backendContainerAppFqdn"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Build + deploy the webapp:"
Write-Host "       ../03-frontend/deploy.ps1 -ResourceGroup $ResourceGroup -SubscriptionId $SubscriptionId"
Write-Host "  2. Install PG extensions + load data (also narrows the UAMI grant):"
Write-Host "       ../04-data-loading/deploy.ps1 -ResourceGroup $ResourceGroup -SubscriptionId $SubscriptionId"
Write-Host ""
Write-Host "Smoke check (auth-disabled, no bearer token required):"
Write-Host "  Invoke-WebRequest -Uri 'https://$backendContainerAppFqdn/health' -UseBasicParsing"
Write-Host ""
