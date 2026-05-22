<#
.SYNOPSIS
    Post-up hook for TalentIQ — runs after every `azd up`, regardless of whether
    provision was skipped due to state cache. Ensures the deployed webapp's URL
    is registered as a SPA redirect URI on the Entra app registration so MSAL
    sign-in works.

.NOTES
    Idempotent. Safe to re-run. Failures are logged as warnings but do NOT abort
    the `azd up` flow — manual registration via the Entra portal remains an option.

    The postprovision hook also performs this registration on full provisions;
    this hook is the safety net for cached `azd up` runs where postprovision is
    skipped entirely.
#>

param(
    [string]$WebappPath = "../../talent_ui"
)

$ErrorActionPreference = "Stop"

# Skip if running inside a nested provision context (defensive)
if ($env:AZD_POSTPROVISION_PHASE -eq "1") {
    Write-Host "Skipping postup hook (nested provision phase in progress)."
    exit 0
}

Write-Host "=========================================="
Write-Host "Post-up hook: SPA redirect URI sync"
Write-Host "=========================================="

function Get-AzdEnvValue {
    param([string]$Name)
    # azd writes errors like "ERROR: key '<name>' not found" to stdout, not stderr.
    $raw = & cmd /c "azd env get-value $Name 2>&1"
    if ($null -eq $raw) { return "" }
    $lines = @(@($raw) | Where-Object { $_ -ne $null -and $_ -ne "" } | Where-Object {
        $line = $_.ToString().Trim()
        -not ($line.StartsWith("ERROR:") -or
              $line.StartsWith("WARNING:") -or
              $line.StartsWith("To update") -or
              $line -eq "" -or
              $line.StartsWith("winget upgrade"))
    })
    if ($lines.Count -eq 0) { return "" }
    return $lines[0].ToString().Trim()
}

function Get-EntraSpaClientId {
    <#
        Resolves the Entra SPA app registration client ID.
        Priority:
          1. azd env value `entraSpaClientId`
          2. Hardcoded clientId in talent_ui/src/authConfig.js (regex)
    #>
    param([string]$WebappSourcePath)

    $fromEnv = Get-AzdEnvValue "entraSpaClientId"
    if (-not [string]::IsNullOrEmpty($fromEnv)) { return $fromEnv.Trim() }

    $authConfigPath = Join-Path $WebappSourcePath "src\authConfig.js"
    if (Test-Path $authConfigPath) {
        $content = Get-Content $authConfigPath -Raw
        $m = [regex]::Match($content, 'clientId\s*:\s*["'']([0-9a-fA-F-]{36})["'']')
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return ""
}

function Register-WebappRedirectUri {
    param(
        [string]$AppClientId,
        [string]$WebappFqdn
    )

    if ([string]::IsNullOrEmpty($AppClientId)) {
        Write-Host "  ⚠ Skipping — no SPA client ID resolved." -ForegroundColor Yellow
        Write-Host "    To enable automatic registration:"
        Write-Host "      azd env set entraSpaClientId <your-spa-app-client-id>"
        return
    }
    if ([string]::IsNullOrEmpty($WebappFqdn)) {
        Write-Host "  ⚠ Skipping — no webapp FQDN in azd env." -ForegroundColor Yellow
        return
    }

    $newUri = "https://$WebappFqdn"
    Write-Host "  App:  $AppClientId"
    Write-Host "  URI:  $newUri"

    try {
        $objectId = & az ad app show --id $AppClientId --query id -o tsv 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($objectId)) {
            Write-Host "  ⚠ App $AppClientId not found or unreadable." -ForegroundColor Yellow
            Write-Host "    Add the URI manually in the Entra portal (Single-page application)."
            return
        }

        $existingJson = & az ad app show --id $AppClientId --query "spa.redirectUris" -o json 2>$null
        $existing = @()
        if (-not [string]::IsNullOrEmpty($existingJson) -and $existingJson -ne "null") {
            $existing = $existingJson | ConvertFrom-Json
            if ($null -eq $existing) { $existing = @() }
        }

        if ($existing -contains $newUri) {
            Write-Host "  ✓ Redirect URI already registered. No action needed." -ForegroundColor Green
            return
        }

        $merged = @($existing) + $newUri
        $body = @{ spa = @{ redirectUris = $merged } } | ConvertTo-Json -Depth 5 -Compress

        $bodyFile = Join-Path $env:TEMP "azd-spa-redirect-patch.json"
        $body | Set-Content -Path $bodyFile -Encoding UTF8 -NoNewline

        $patchOutput = & az rest --method PATCH `
            --uri "https://graph.microsoft.com/v1.0/applications/$objectId" `
            --headers "Content-Type=application/json" `
            --body "@$bodyFile" 2>&1
        $patchExit = $LASTEXITCODE

        Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue

        if ($patchExit -ne 0) {
            Write-Host "  ⚠ Failed to update app registration (az rest exit $patchExit)." -ForegroundColor Yellow
            if ($patchOutput) { Write-Host "    $patchOutput" }
            Write-Host "    Likely cause: signed-in user lacks Application.ReadWrite.OwnedBy"
            Write-Host "                  or is not an owner of the app registration."
            Write-Host "    Manual add: $newUri (Single-page application platform)"
            return
        }

        Write-Host "  ✓ Added $newUri to SPA redirect URIs." -ForegroundColor Green
    } catch {
        Write-Host "  ⚠ Exception: $_" -ForegroundColor Yellow
        Write-Host "    Manual add: $newUri (Single-page application platform)"
    }
}

function Get-WebappFqdnFromAzure {
    <#
        Fallback when azd env's webappContainerAppFqdn is empty (which happens
        when bicep outputs are gated behind deployWebappContainerApp and that
        flag is false even though the container app exists in Azure).
        Lists all container apps in the resource group and picks the one whose
        name starts with "webapp-".

        Note: avoid passing JMESPath via --query — PowerShell → az.cmd → cmd.exe
        strips outer quotes and cmd then chokes on [] {} metacharacters. Get
        all apps as JSON and filter in PowerShell instead.
    #>
    param([string]$ResourceGroup)
    if ([string]::IsNullOrEmpty($ResourceGroup)) {
        Write-Host "  (no AZURE_RESOURCE_GROUP in azd env)" -ForegroundColor DarkGray
        return ""
    }
    Write-Host "  Querying: az containerapp list -g $ResourceGroup -o json ..." -ForegroundColor DarkGray
    try {
        # Route stderr to a temp file so warnings (e.g. CLI upgrade notices)
        # don't contaminate the stdout JSON we're about to parse.
        $tmpErr = [System.IO.Path]::GetTempFileName()
        try {
            $json = az containerapp list -g $ResourceGroup -o json 2>$tmpErr | Out-String
            $azExit = $LASTEXITCODE
            $stderr = if (Test-Path $tmpErr) { (Get-Content $tmpErr -Raw -ErrorAction SilentlyContinue) } else { "" }
        } finally {
            Remove-Item $tmpErr -Force -ErrorAction SilentlyContinue
        }
        if ($azExit -ne 0) {
            Write-Host "  ⚠ az containerapp list failed (exit $azExit):" -ForegroundColor Yellow
            if (-not [string]::IsNullOrWhiteSpace($stderr)) { Write-Host "    $stderr" -ForegroundColor DarkGray }
            if (-not [string]::IsNullOrWhiteSpace($json))   { Write-Host "    $json" -ForegroundColor DarkGray }
            return ""
        }
        $apps = $json | ConvertFrom-Json -ErrorAction SilentlyContinue
        if (-not $apps -or @($apps).Count -eq 0) {
            Write-Host "  ⚠ No container apps found in resource group $ResourceGroup" -ForegroundColor Yellow
            return ""
        }
        # Filter in PowerShell (avoids JMESPath quoting issues).
        $candidates = @($apps) | Where-Object { $_.name -like "webapp-*" }
        if (@($candidates).Count -eq 0) {
            $allNames = (@($apps) | ForEach-Object { $_.name }) -join ", "
            Write-Host "  ⚠ No container apps matched 'webapp-*'. Found: $allNames" -ForegroundColor Yellow
            return ""
        }
        # Prefer apps with external ingress FQDN.
        $candidate = $candidates | Where-Object { $_.properties.configuration.ingress.fqdn } | Select-Object -First 1
        if ($candidate) { return $candidate.properties.configuration.ingress.fqdn }
        Write-Host "  ⚠ Found webapp container app(s) but none have an external FQDN." -ForegroundColor Yellow
        return ""
    } catch {
        Write-Host "  ⚠ Exception calling az: $_" -ForegroundColor Yellow
        return ""
    }
}

# ============================================================
# MAIN
# ============================================================

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$webappFqdn = Get-AzdEnvValue "webappContainerAppFqdn"
if ([string]::IsNullOrEmpty($webappFqdn)) {
    Write-Host "azd env 'webappContainerAppFqdn' is empty - falling back to Azure query..."
    $resourceGroup = Get-AzdEnvValue "AZURE_RESOURCE_GROUP"
    $webappFqdn = Get-WebappFqdnFromAzure -ResourceGroup $resourceGroup
    if ([string]::IsNullOrEmpty($webappFqdn)) {
        Write-Host "Could not resolve webapp FQDN from azd env or Azure - skipping redirect URI sync."
        Write-Host "(The webapp may not have been deployed yet, or 'az' is not logged in.)"
        exit 0
    }
    Write-Host "  Resolved from Azure: $webappFqdn" -ForegroundColor Cyan
}

$webappSourcePath = Resolve-Path (Join-Path $scriptDir $WebappPath) -ErrorAction SilentlyContinue
if (-not $webappSourcePath) {
    Write-Host "⚠ Could not resolve webapp source path '$WebappPath' — skipping." -ForegroundColor Yellow
    exit 0
}

$entraSpaClientId = Get-EntraSpaClientId -WebappSourcePath $webappSourcePath.Path
Register-WebappRedirectUri -AppClientId $entraSpaClientId -WebappFqdn $webappFqdn

Write-Host "=========================================="
Write-Host "Post-up hook complete."
Write-Host "=========================================="
