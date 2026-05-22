<#
.SYNOPSIS
    Pre-provision hook for TalentIQ: get client IP, generate PG password,
    reset container app deploy flags for two-phase deployment.
#>

Write-Host "=========================================="
Write-Host "Pre-provision hook starting..."
Write-Host "=========================================="

# Get client public IP
try {
    $clientIp = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).Content.Trim()
    Write-Host "Client IP: $clientIp"
    cmd /c "azd env set CLIENT_IP_ADDRESS $clientIp 2>&1"
    Write-Host "CLIENT_IP_ADDRESS set to: $clientIp"
} catch {
    Write-Host "WARNING: Could not get client IP address. PostgreSQL firewall rule will not be created."
    Write-Host "Error: $_"
    cmd /c "azd env set CLIENT_IP_ADDRESS '' 2>&1"
}

# Ensure POSTGRESQL_ADMIN_PASSWORD is set
# Robust read: azd writes "ERROR: key '...' not found..." to stdout (not stderr), so
# 2>nul does NOT suppress it. Filter out error/warning chatter explicitly.
function Read-AzdEnvValue($Name) {
    $raw = & cmd /c "azd env get-value $Name 2>&1"
    if ($null -eq $raw) { return "" }
    # Force array semantics — PowerShell unwraps single-element collections to scalars.
    $lines = @(@($raw) | Where-Object { $_ -ne $null -and $_ -ne "" } | Where-Object {
        $line = $_.ToString().Trim()
        $line -ne "" -and
        -not $line.StartsWith("ERROR:") -and
        -not $line.StartsWith("WARNING:") -and
        -not $line.StartsWith("To update") -and
        -not $line.StartsWith("winget upgrade")
    })
    if ($lines.Count -eq 0) { return "" }
    return $lines[0].ToString().Trim()
}
$existingPassword = Read-AzdEnvValue "POSTGRESQL_ADMIN_PASSWORD"
if ([string]::IsNullOrEmpty($existingPassword)) {
    # Try to read from app_config/.env
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $localEnvFile = Resolve-Path (Join-Path $scriptDir "../../app_config/.env") -ErrorAction SilentlyContinue
    $envPassword = ""
    if ($localEnvFile -and (Test-Path $localEnvFile)) {
        $match = Select-String -Path $localEnvFile -Pattern '^PGPASSWORD=(.+)$' | Select-Object -First 1
        if ($match) {
            $envPassword = $match.Matches[0].Groups[1].Value.Trim()
        }
    }

    if (-not [string]::IsNullOrEmpty($envPassword)) {
        Write-Host "Using PGPASSWORD from app_config/.env"
        $password = $envPassword
    } else {
        Write-Host "Generating PostgreSQL admin password..."
        # Shell-safe characters only
        $upper = -join ((65..90) | Get-Random -Count 5 | ForEach-Object { [char]$_ })
        $lower = -join ((97..122) | Get-Random -Count 5 | ForEach-Object { [char]$_ })
        $digits = -join ((48..57) | Get-Random -Count 4 | ForEach-Object { [char]$_ })
        $special = -join (('.', '-', '_', '~') | Get-Random -Count 2)
        $all = ($upper + $lower + $digits + $special).ToCharArray() | Sort-Object { Get-Random }
        $password = -join $all
    }
    cmd /c "azd env set POSTGRESQL_ADMIN_PASSWORD `"$password`" 2>&1"
    # Verify
    $verify = Read-AzdEnvValue "POSTGRESQL_ADMIN_PASSWORD"
    if ([string]::IsNullOrEmpty($verify)) {
        Write-Host "ERROR: Failed to persist POSTGRESQL_ADMIN_PASSWORD in azd env." -ForegroundColor Red
        Write-Host "Set it manually: azd env set POSTGRESQL_ADMIN_PASSWORD `"<password>`""
        exit 1
    }
    Write-Host "POSTGRESQL_ADMIN_PASSWORD has been set and verified."
} else {
    Write-Host "POSTGRESQL_ADMIN_PASSWORD is already set."
}

# Reset container app deployment flags for clean provision (Phase 1 = infra only)
Write-Host "Resetting container app deployment flags for clean provision..."
cmd /c "azd env set deployMcpServerContainerApp false 2>&1"
cmd /c "azd env set deployBackendContainerApp false 2>&1"
cmd /c "azd env set deployWebappContainerApp false 2>&1"

# Capture deploying user's Entra identity → registered as the initial PostgreSQL
# Entra ID administrator by the Bicep `administrators` child resource. The
# postprovision hook then connects with this identity (via OSSRDBMS token) to
# provision additional Entra principals (container app UAMIs, app users).
Write-Host "Capturing deploying Entra identity for PostgreSQL admin..."
try {
    $signedInUserJson = & az ad signed-in-user show --query "{id:id, upn:userPrincipalName}" -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($signedInUserJson)) {
        $signedInUser = $signedInUserJson | ConvertFrom-Json
        if ($signedInUser.id) {
            cmd /c "azd env set POSTGRESQL_ENTRA_ADMIN_OBJECT_ID $($signedInUser.id) 2>&1" | Out-Null
            cmd /c "azd env set POSTGRESQL_ENTRA_ADMIN_PRINCIPAL_NAME $($signedInUser.upn) 2>&1" | Out-Null
            cmd /c "azd env set POSTGRESQL_ENTRA_ADMIN_PRINCIPAL_TYPE User 2>&1" | Out-Null
            Write-Host "  PG Entra admin: $($signedInUser.upn) ($($signedInUser.id))"
        }
    } else {
        Write-Host "  WARNING: az CLI not signed in or returned no user — run 'az login' first." -ForegroundColor Yellow
        Write-Host "  Bicep will skip the initial Entra admin assignment; postprovision will retry." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  WARNING: failed to capture signed-in user: $_" -ForegroundColor Yellow
}

Write-Host "=========================================="
Write-Host "Pre-provision hook complete."
Write-Host "=========================================="
