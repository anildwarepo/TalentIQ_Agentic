<#
.SYNOPSIS
    Pre-provision hook to get the client IP address for PostgreSQL firewall rule
    and ensure the PostgreSQL admin password is set as an azd environment variable.
#>

Write-Host "=========================================="
Write-Host "Pre-provision hook starting..."
Write-Host "=========================================="

# Get client public IP
try {
    $clientIp = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).Content.Trim()
    Write-Host "Client IP: $clientIp"
    
    # Set it as an azd environment variable
    cmd /c "azd env set CLIENT_IP_ADDRESS $clientIp 2>&1"
    Write-Host "CLIENT_IP_ADDRESS set to: $clientIp"
} catch {
    Write-Host "WARNING: Could not get client IP address. PostgreSQL firewall rule will not be created."
    Write-Host "Error: $_"
    # Set empty value
    cmd /c "azd env set CLIENT_IP_ADDRESS '' 2>&1"
}

# Ensure POSTGRESQL_ADMIN_PASSWORD is set as a regular env value so the
# postprovision hook can read it via 'azd env get-value'. Without this,
# azd stores @secure() parameter values only in its encrypted vault,
# which is not accessible from hooks.
# Use cmd /c to avoid PS5.1 NativeCommandError on azd stderr warnings
$existingPassword = (cmd /c "azd env get-value POSTGRESQL_ADMIN_PASSWORD 2>nul")
if ($existingPassword) { $existingPassword = $existingPassword.Trim() }
if ([string]::IsNullOrEmpty($existingPassword)) {
    # Try to read PGPASSWORD from the local postgresql_age/.env file first.
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $localEnvFile = Resolve-Path (Join-Path $scriptDir "../../postgresql_age/.env") -ErrorAction SilentlyContinue
    $envPassword = ""
    if ($localEnvFile -and (Test-Path $localEnvFile)) {
        $match = Select-String -Path $localEnvFile -Pattern '^PGPASSWORD=(.+)$' | Select-Object -First 1
        if ($match) {
            $envPassword = $match.Matches[0].Groups[1].Value.Trim()
        }
    }

    if (-not [string]::IsNullOrEmpty($envPassword)) {
        Write-Host "Using PGPASSWORD from postgresql_age/.env"
        $password = $envPassword
    } else {
        Write-Host "Generating PostgreSQL admin password..."
        # Generate a random password that meets Azure PostgreSQL complexity requirements.
        # IMPORTANT: Avoid characters that are shell metacharacters (! @ # $ % ^ & * ` |)
        # because they corrupt cmd /c and cause azd env set to silently fail.
        $upper = -join ((65..90) | Get-Random -Count 5 | ForEach-Object { [char]$_ })
        $lower = -join ((97..122) | Get-Random -Count 5 | ForEach-Object { [char]$_ })
        $digits = -join ((48..57) | Get-Random -Count 4 | ForEach-Object { [char]$_ })
        $special = -join (('.', '-', '_', '~') | Get-Random -Count 2)
        $all = ($upper + $lower + $digits + $special).ToCharArray() | Sort-Object { Get-Random }
        $password = -join $all
    }
    # Use cmd /c to avoid PS5.1 NativeCommandError on azd stderr warnings.
    cmd /c "azd env set POSTGRESQL_ADMIN_PASSWORD `"$password`" 2>&1"
    # Verify the value was actually persisted.
    $verify = (cmd /c "azd env get-value POSTGRESQL_ADMIN_PASSWORD 2>nul")
    if ($verify) { $verify = $verify.Trim() }
    if ([string]::IsNullOrEmpty($verify)) {
        Write-Host "ERROR: Failed to persist POSTGRESQL_ADMIN_PASSWORD in azd env." -ForegroundColor Red
        Write-Host "Set it manually: azd env set POSTGRESQL_ADMIN_PASSWORD `"<password>`""
        exit 1
    }
    Write-Host "POSTGRESQL_ADMIN_PASSWORD has been set and verified."
} else {
    Write-Host "POSTGRESQL_ADMIN_PASSWORD is already set."
}

# Reset container app deployment flags to false so the initial azd provision
# (run by 'azd up') only creates infrastructure.  The postprovision hook will
# Reset container app deployment flags to false so the initial azd provision
# (run by 'azd up') only creates infrastructure.  The postprovision hook will
# deploy container apps directly via az deployment group create.
Write-Host "Resetting container app deployment flags for clean provision..."
cmd /c "azd env set deployMcpServerContainerApp false 2>&1"
cmd /c "azd env set deployFastApiContainerApp false 2>&1"
cmd /c "azd env set deployWebappContainerApp false 2>&1"

Write-Host "=========================================="
