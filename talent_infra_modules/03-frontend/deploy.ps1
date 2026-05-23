<#
.SYNOPSIS
    Build, push, and deploy the TalentIQ frontend (React/Vite + nginx) as
    a standalone Azure Container App with external HTTPS ingress.

.DESCRIPTION
    Sister script to 02-backend/deploy.ps1. Assumes the resource group,
    Azure Container Apps managed environment, and Azure Container
    Registry already exist (see ../README.md for the prerequisite
    matrix).

    Phases:
      1. Sign-in + subscription check
      2. Read ../02-backend/.outputs.json for backendContainerAppFqdn
         (unless -BackendFqdn explicitly provided)
      3. Parameter resolution (env -> prompt -> default)
      4. Prerequisite existence checks (RG, ACR, ACA env)
      5. Inspect talent_ui/Dockerfile for the ARG declarations the
         build args require; warn Anil if any are missing (Dallas owns
         that change)
      6. Confirm + summary
      7. az acr build with VITE_* build args (the auth-disable contract:
         VITE_DISABLE_AUTH=true is baked here)
      8. az deployment group create against infra/main.bicep
      9. Write .outputs.json
     10. Print "what next" footer

    This is the AUTH-DISABLED deployment path. We deliberately do not set
    VITE_MSAL_CLIENT_ID / VITE_MSAL_AUTHORITY / VITE_MSAL_REDIRECT_URI as
    build args. See ../AUTH-DISABLED.md for the full contract.

    Author: Bishop (Deployment Engineer)
    Date:   2026-05-21
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$Location = "westus",
    [string]$AcrName,
    [string]$AcrResourceGroup,
    [string]$ContainerAppsEnvName,
    [string]$ContainerAppsEnvResourceGroup,
    [string]$WebappAppName,
    [string]$WebappImageTag = "latest",
    [string]$BackendFqdn,
    [string]$WebappSourcePath = "..\..\talent_ui",
    [switch]$SkipBuild,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------------------------
# Bootstrap
# ------------------------------------------------------------------------------

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "..\shared\common.ps1")

Write-Host ""
Write-Host "############################################################" -ForegroundColor Cyan
Write-Host "  TalentIQ 03-frontend - webapp Container App deployment" -ForegroundColor Cyan
Write-Host "############################################################" -ForegroundColor Cyan

# ------------------------------------------------------------------------------
# Phase 1 - Azure sign-in
# ------------------------------------------------------------------------------

$account = Test-AzLoggedIn

# ------------------------------------------------------------------------------
# Phase 2 - Read backend FQDN from 02-backend/.outputs.json
# ------------------------------------------------------------------------------

if ([string]::IsNullOrEmpty($BackendFqdn)) {
    Write-Step "Reading backend FQDN from ../02-backend/.outputs.json"
    $backendOutputsPath = Resolve-Path (Join-Path $scriptDir "..\02-backend\.outputs.json") -ErrorAction SilentlyContinue
    if (-not $backendOutputsPath -or -not (Test-Path $backendOutputsPath.Path)) {
        Write-Fail "Cannot read ../02-backend/.outputs.json. Run ../02-backend/deploy.ps1 first,"
        Write-Info "or pass -BackendFqdn <backend-public-fqdn> to override."
        exit 1
    }
    try {
        $backendOutputs = Get-Content -Raw $backendOutputsPath.Path | ConvertFrom-Json
    } catch {
        Write-Fail "Could not parse ../02-backend/.outputs.json as JSON: $_"
        exit 1
    }
    $BackendFqdn = [string]$backendOutputs.backendContainerAppFqdn
    if ([string]::IsNullOrWhiteSpace($BackendFqdn)) {
        Write-Fail "backendContainerAppFqdn missing or empty in ../02-backend/.outputs.json."
        Write-Info "Re-run ../02-backend/deploy.ps1 or pass -BackendFqdn <fqdn>."
        exit 1
    }
    Write-Success "Backend FQDN = $BackendFqdn"
} else {
    Write-Step "Using -BackendFqdn override"
    Write-Success "Backend FQDN = $BackendFqdn"
}

# Strip any accidental scheme / trailing slash - Bicep expects bare FQDN.
$BackendFqdn = $BackendFqdn -replace '^https?://', '' -replace '/+$', ''

# ------------------------------------------------------------------------------
# Phase 3 - Parameter resolution
# ------------------------------------------------------------------------------

$SubscriptionId       = Get-ParameterValue -Name "Subscription ID"               -Value $SubscriptionId       -EnvVar "AZURE_SUBSCRIPTION_ID"
$ResourceGroup        = Get-ParameterValue -Name "Resource group"                -Value $ResourceGroup        -EnvVar "AZURE_RESOURCE_GROUP"
$Location             = Get-ParameterValue -Name "Location"                      -Value $Location             -EnvVar "AZURE_LOCATION"             -Default "westus"
$AcrName              = Get-ParameterValue -Name "ACR name"                      -Value $AcrName              -EnvVar "AZURE_ACR_NAME"
$AcrResourceGroup     = Get-ParameterValue -Name "ACR resource group"            -Value $AcrResourceGroup     -EnvVar "AZURE_ACR_RESOURCE_GROUP"   -Default $ResourceGroup

# Soft fallback: read 00-container-apps-env/.outputs.json when the ACA env
# name (and its RG) were not supplied via -ContainerAppsEnvName /
# -ContainerAppsEnvResourceGroup or AZURE_ACA_ENV_NAME / AZURE_ACA_ENV_RESOURCE_GROUP.
# This makes `00 -> 03` a one-shot hand-off without forcing operators to
# copy values by hand. Never fails if the file is missing.
if ([string]::IsNullOrEmpty($ContainerAppsEnvName) `
        -and [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('AZURE_ACA_ENV_NAME'))) {
    $caeOutputsPath = Join-Path $PSScriptRoot "..\00-container-apps-env\.outputs.json"
    if (Test-Path $caeOutputsPath) {
        try {
            $caeOutputs = Get-Content -LiteralPath $caeOutputsPath -Raw | ConvertFrom-Json
            if ($caeOutputs -and -not [string]::IsNullOrEmpty($caeOutputs.containerAppsEnvName)) {
                $ContainerAppsEnvName = [string]$caeOutputs.containerAppsEnvName
                Write-Info "Container Apps env name = (from 00-container-apps-env/.outputs.json)"
                if ([string]::IsNullOrEmpty($ContainerAppsEnvResourceGroup) `
                        -and [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('AZURE_ACA_ENV_RESOURCE_GROUP')) `
                        -and -not [string]::IsNullOrEmpty($caeOutputs.containerAppsEnvResourceGroup)) {
                    $ContainerAppsEnvResourceGroup = [string]$caeOutputs.containerAppsEnvResourceGroup
                    Write-Info "Container Apps env RG = (from 00-container-apps-env/.outputs.json)"
                }
            }
        } catch {
            Write-Warn "Could not parse $caeOutputsPath; falling back to prompt."
        }
    }
}

$ContainerAppsEnvName = Get-ParameterValue -Name "Container Apps env name"       -Value $ContainerAppsEnvName -EnvVar "AZURE_ACA_ENV_NAME"
$ContainerAppsEnvResourceGroup = Get-ParameterValue -Name "Container Apps env resource group" -Value $ContainerAppsEnvResourceGroup -EnvVar "AZURE_ACA_ENV_RESOURCE_GROUP" -Default $ResourceGroup
$WebappImageTag       = Get-ParameterValue -Name "Webapp image tag"              -Value $WebappImageTag       -EnvVar "WEBAPP_IMAGE_TAG"           -Default "latest"

# Compute a stable 5-char hash from subscription + RG so re-running this
# script against the same target produces the same Container App name
# (idempotent). Override via -WebappAppName or $env:WEBAPP_CONTAINER_APP_NAME.
if ([string]::IsNullOrEmpty($WebappAppName)) {
    $envOverride = [Environment]::GetEnvironmentVariable("WEBAPP_CONTAINER_APP_NAME")
    if (-not [string]::IsNullOrEmpty($envOverride)) {
        $WebappAppName = $envOverride
    } else {
        $hashInput = "$SubscriptionId|$ResourceGroup|webapp"
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($hashInput)
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $hashBytes = $sha.ComputeHash($bytes)
        } finally {
            $sha.Dispose()
        }
        $hashHex = ($hashBytes | ForEach-Object { $_.ToString("x2") }) -join ""
        $short = $hashHex.Substring(0, 5)
        $WebappAppName = "tiq-webapp-$short"
    }
}

# Resolve webapp source path to an absolute path so Push-Location works
# regardless of where the operator invoked the script from.
$webappFullPath = Resolve-Path (Join-Path $scriptDir $WebappSourcePath) -ErrorAction SilentlyContinue
if (-not $webappFullPath) {
    Write-Fail "Webapp source path '$WebappSourcePath' (resolved against script dir) does not exist."
    exit 1
}
$WebappSourcePath = $webappFullPath.Path

# Cross-RG ACR is not supported by the copied container-app.bicep module
# (it uses an existing-resource lookup scoped to the deployment RG). If
# the operator pointed us at a cross-RG ACR, fail fast with a clear
# message rather than have ARM emit a confusing 'resource not found'.
if ($AcrResourceGroup -ne $ResourceGroup) {
    Write-Fail "Cross-resource-group ACR is not supported in 03-frontend v1."
    Write-Info "  Deployment RG: $ResourceGroup"
    Write-Info "  ACR RG:        $AcrResourceGroup"
    Write-Info ""
    Write-Info "The copied modules/container-app.bicep references the ACR via an"
    Write-Info "existing-resource lookup in the deployment scope. Move the ACR into"
    Write-Info "$ResourceGroup, or extend modules/container-app.bicep with an"
    Write-Info "acrResourceGroup param + a sub-module for the AcrPull role assignment."
    exit 1
}

# ------------------------------------------------------------------------------
# Phase 4 - Set subscription and verify prerequisites exist
# ------------------------------------------------------------------------------

Test-AzSubscription -SubscriptionId $SubscriptionId

Assert-PrerequisitesExist -ResourceGroup $ResourceGroup -Checks @(
    @{ Type = 'rg';              Name = $ResourceGroup },
    @{ Type = 'acr';             Name = $AcrName },
    @{ Type = 'containerappenv'; Name = $ContainerAppsEnvName }
)

# Resolve the full ACA env resource ID. The bicep module takes the ID,
# not the name, so it works for cross-RG ACA envs.
Write-Step "Resolving Container Apps environment resource ID"
$envIdRaw = (Invoke-Native {
    az containerapp env show `
        --name $ContainerAppsEnvName `
        --resource-group $ContainerAppsEnvResourceGroup `
        --query id -o tsv 2>$null `
    | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
}) -join ""
$containerAppsEnvironmentId = $envIdRaw.Trim()
if ([string]::IsNullOrEmpty($containerAppsEnvironmentId)) {
    Write-Fail "Could not resolve Container Apps environment ID for '$ContainerAppsEnvName' in '$ContainerAppsEnvResourceGroup'."
    exit 1
}
Write-Success "ACA env ID: $containerAppsEnvironmentId"

$acrLoginServer = Get-AcrLoginServer -ResourceGroup $AcrResourceGroup -AcrName $AcrName
if ([string]::IsNullOrEmpty($acrLoginServer)) {
    Write-Fail "Could not resolve ACR loginServer for '$AcrName'."
    exit 1
}
Write-Success "ACR loginServer: $acrLoginServer"

$webappImageRef = "${acrLoginServer}/webapp:${WebappImageTag}"

# ------------------------------------------------------------------------------
# Phase 5 - Inspect talent_ui/Dockerfile for the required ARG declarations
# ------------------------------------------------------------------------------
#
# The Vite build inlines `import.meta.env.VITE_*` at `npm run build` time
# ONLY for variables that are declared as `ARG <name>` (with optional
# `ENV <name>=$<name>`) BEFORE the `RUN npm run build` line in the
# builder stage. If an ARG is missing, --build-arg is silently a no-op
# and the value never reaches the JS bundle.
#
# We do NOT modify the Dockerfile - that's Dallas's deliverable per the
# AUTH-DISABLED.md contract. We warn loudly so Anil knows what to ask
# Dallas to add before this script can produce a working bundle.

Write-Step "Inspecting talent_ui/Dockerfile for required ARG declarations"
$dockerfilePath = Join-Path $WebappSourcePath "Dockerfile"
if (-not (Test-Path $dockerfilePath)) {
    Write-Fail "Dockerfile not found at $dockerfilePath"
    exit 1
}

$dockerfileText = Get-Content -Raw $dockerfilePath
$requiredArgs = @(
    'VITE_API_BASE',
    'VITE_AF_BACKEND_URL',
    'VITE_AGENT_NAME',
    'VITE_DISABLE_AUTH',
    'VITE_API_BASE_URL'
)
$presentArgs = @()
$missingArgs = @()
foreach ($argName in $requiredArgs) {
    # Single-quoted pieces so PowerShell never interpolates the regex anchors
    # (the '$' in '(\s|=|$)' would otherwise read as a variable reference).
    $pattern = '(?m)^\s*ARG\s+' + [regex]::Escape($argName) + '(\s|=|$)'
    if ($dockerfileText -match $pattern) {
        $presentArgs += $argName
    } else {
        $missingArgs += $argName
    }
}

Write-Info "ARG present:  $($presentArgs -join ', ')"
if ($missingArgs.Count -gt 0) {
    Write-Warn "ARG MISSING in talent_ui/Dockerfile: $($missingArgs -join ', ')"
    Write-Host ""
    Write-Host "    >>> Dallas action required <<<" -ForegroundColor Yellow
    Write-Host "    Add the following lines to talent_ui/Dockerfile BEFORE 'RUN npm run build'" -ForegroundColor Yellow
    Write-Host "    in the builder stage (so Vite picks them up at build time):" -ForegroundColor Yellow
    Write-Host ""
    foreach ($a in $missingArgs) {
        # -f format strings avoid PowerShell trying to parse '$$' as the PID variable.
        Write-Host ('        ARG {0}=""' -f $a) -ForegroundColor Yellow
        Write-Host ('        ENV {0}=${0}'  -f $a) -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "    Without these ARG declarations the --build-arg values this script" -ForegroundColor Yellow
    Write-Host "    passes will be SILENTLY DROPPED and the deployed bundle will fall" -ForegroundColor Yellow
    Write-Host "    back to the dev defaults from talent_ui/.env.example (which still" -ForegroundColor Yellow
    Write-Host "    enable MSAL - defeating the auth-disable purpose of this folder)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    Continuing anyway - the deploy.ps1 will still build, push, and" -ForegroundColor Yellow
    Write-Host "    create the Container App, but the bundle will NOT honor" -ForegroundColor Yellow
    Write-Host "    VITE_DISABLE_AUTH until Dallas's Dockerfile change ships." -ForegroundColor Yellow
} else {
    Write-Success "All required ARG declarations are present in the Dockerfile."
}

# ------------------------------------------------------------------------------
# Phase 6 - Summary + confirm
# ------------------------------------------------------------------------------

Write-Step "Deployment summary"
Write-Host "  Subscription:        $SubscriptionId" -ForegroundColor Gray
Write-Host "  Tenant:              $($account.tenantId)" -ForegroundColor Gray
Write-Host "  Resource group:      $ResourceGroup" -ForegroundColor Gray
Write-Host "  Location:            $Location" -ForegroundColor Gray
Write-Host "  ACR:                 $AcrName  (RG: $AcrResourceGroup)" -ForegroundColor Gray
Write-Host "  ACA environment:     $ContainerAppsEnvName  (RG: $ContainerAppsEnvResourceGroup)" -ForegroundColor Gray
Write-Host "  Webapp app name:     $WebappAppName" -ForegroundColor Gray
Write-Host "  Webapp image:        $webappImageRef" -ForegroundColor Gray
Write-Host "  Webapp source path:  $WebappSourcePath" -ForegroundColor Gray
Write-Host "  Backend FQDN:        $BackendFqdn" -ForegroundColor Gray
Write-Host "  Build image:         $(if ($SkipBuild) { 'SKIPPED (-SkipBuild)' } else { 'YES (az acr build)' })" -ForegroundColor Gray
Write-Host "  Auth posture:        DISABLED (VITE_DISABLE_AUTH=true, no MSAL env vars)" -ForegroundColor Gray

if (-not (Confirm-Action -Message "Proceed with deployment?" -Force:$Force)) {
    Write-Warn "Aborted by user."
    exit 0
}

# ------------------------------------------------------------------------------
# Phase 7 - az acr build  (skipped when -SkipBuild)
# ------------------------------------------------------------------------------

if (-not $SkipBuild) {
    Write-Step "Building webapp image via az acr build  (this may take several minutes)"

    # Build args. Order matches the contract documented in
    # ../README.md and ../AUTH-DISABLED.md. VITE_API_BASE_URL is
    # intentionally empty - the Dockerfile already defaults it to ""
    # and the runtime nginx proxy uses BACKEND_URL, not VITE_API_BASE_URL.
    $buildArgPairs = @(
        "VITE_API_BASE=https://$BackendFqdn",
        "VITE_AF_BACKEND_URL=https://$BackendFqdn/af",
        "VITE_AGENT_NAME=talentiq-agent",
        "VITE_DISABLE_AUTH=true",
        "VITE_API_BASE_URL="
    )

    $acrBuildArgs = @(
        'acr', 'build',
        '--registry', $AcrName,
        '--image', "webapp:$WebappImageTag",
        '--image', 'webapp:latest',
        '--file', 'Dockerfile'
    )
    foreach ($pair in $buildArgPairs) {
        $acrBuildArgs += '--build-arg'
        $acrBuildArgs += $pair
    }
    $acrBuildArgs += '.'

    Push-Location $WebappSourcePath
    try {
        Write-Info "az $($acrBuildArgs -join ' ')"
        Invoke-Native { & az @acrBuildArgs }
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "az acr build failed with exit code $LASTEXITCODE."
            exit 1
        }
    } finally {
        Pop-Location
    }
    Write-Success "Image built and pushed: $webappImageRef"
} else {
    Write-Step "Skipping image build (-SkipBuild)"
    Write-Info "Assuming $webappImageRef already exists in ACR."
}

# ------------------------------------------------------------------------------
# Phase 8 - az deployment group create
# ------------------------------------------------------------------------------

Write-Step "Deploying Container App via Bicep"

$bicepPath        = Join-Path $scriptDir "infra\main.bicep"
$deploymentName   = "tiq-frontend-$(Get-Date -Format 'yyyyMMddHHmmss')"
$tagsJson         = "{`"component`":`"talent_ui`",`"deployedBy`":`"talent_infra_modules/03-frontend`",`"deployedAt`":`"$(Get-Date -Format 'yyyy-MM-dd')`"}"

$deployArgs = @(
    'deployment', 'group', 'create',
    '--name',          $deploymentName,
    '--resource-group', $ResourceGroup,
    '--template-file',  $bicepPath,
    '--parameters',
        "location=$Location",
        "containerAppsEnvironmentId=$containerAppsEnvironmentId",
        "acrName=$AcrName",
        "webappAppName=$WebappAppName",
        "webappImage=$webappImageRef",
        "backendFqdn=$BackendFqdn",
        "tags=$tagsJson",
    '--output', 'json'
)

Write-Info "az $($deployArgs -join ' ')"
$deployRaw = Invoke-Native { & az @deployArgs }
if ($LASTEXITCODE -ne 0) {
    Write-Fail "az deployment group create failed with exit code $LASTEXITCODE."
    exit 1
}

try {
    $deployResult = ($deployRaw -join "`n") | ConvertFrom-Json
} catch {
    Write-Fail "Could not parse deployment result as JSON: $_"
    Write-Info "Raw output:"
    Write-Host ($deployRaw -join "`n") -ForegroundColor DarkGray
    exit 1
}

$out = $deployResult.properties.outputs
$webappContainerAppName = $out.webappContainerAppName.value
$webappContainerAppFqdn = $out.webappContainerAppFqdn.value
$webappUamiId           = $out.webappUamiId.value
$webappUamiPrincipalId  = $out.webappUamiPrincipalId.value

Write-Success "Container App deployed: $webappContainerAppName"
Write-Success "FQDN:                   https://$webappContainerAppFqdn"
Write-Success "UAMI principalId:       $webappUamiPrincipalId"

# ------------------------------------------------------------------------------
# Phase 9 - Emit .outputs.json
# ------------------------------------------------------------------------------

Write-Step "Writing .outputs.json"
$outputsPath = Join-Path $scriptDir ".outputs.json"
$outputs = [ordered]@{
    webappContainerAppName = $webappContainerAppName
    webappContainerAppFqdn = $webappContainerAppFqdn
    webappImage            = $webappImageRef
    webappUamiId           = $webappUamiId
    webappUamiPrincipalId  = $webappUamiPrincipalId
    viteDisableAuth        = $true
    backendFqdn            = $BackendFqdn
}
$outputs | ConvertTo-Json -Depth 5 | Set-Content -Path $outputsPath -Encoding UTF8
Write-Success ".outputs.json written to $outputsPath"

# ------------------------------------------------------------------------------
# What next
# ------------------------------------------------------------------------------

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  [OK] 03-frontend deployment complete" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Visit the frontend:" -ForegroundColor Cyan
Write-Host "    https://$webappContainerAppFqdn" -ForegroundColor White
Write-Host ""
Write-Host "  If you have not loaded data yet, run:" -ForegroundColor Cyan
Write-Host "    cd ..\04-data-loading; .\deploy.ps1" -ForegroundColor White
Write-Host ""
if ($missingArgs.Count -gt 0) {
    Write-Host "  !! Dallas action still pending:" -ForegroundColor Yellow
    Write-Host "    talent_ui/Dockerfile is missing ARG declarations for:" -ForegroundColor Yellow
    Write-Host "      $($missingArgs -join ', ')" -ForegroundColor Yellow
    Write-Host "    Until added, the deployed bundle will not honor VITE_DISABLE_AUTH." -ForegroundColor Yellow
    Write-Host "    After Dallas's change ships, re-run this script (no -SkipBuild) to" -ForegroundColor Yellow
    Write-Host "    rebuild and redeploy. See ../AUTH-DISABLED.md for the contract." -ForegroundColor Yellow
    Write-Host ""
}
Write-Host "  Force a fresh revision (e.g. after a Dallas-only change):" -ForegroundColor Cyan
$restartLine1 = '    az containerapp revision restart -g {0} -n {1}' -f $ResourceGroup, $webappContainerAppName
$restartLine2 = '      --revision (az containerapp show -g {0} -n {1} --query properties.latestRevisionName -o tsv)' -f $ResourceGroup, $webappContainerAppName
Write-Host $restartLine1 -ForegroundColor White
Write-Host $restartLine2 -ForegroundColor White
Write-Host ""
