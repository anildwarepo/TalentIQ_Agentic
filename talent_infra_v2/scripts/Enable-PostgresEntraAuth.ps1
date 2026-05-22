<#
.SYNOPSIS
    Enable Microsoft Entra ID authentication on an Azure Database for PostgreSQL
    Flexible Server and register Entra administrator(s).

.DESCRIPTION
    Idempotently performs the steps described in
    https://learn.microsoft.com/azure/postgresql/security/security-entra-configure :

      1. Verifies you are signed in to Azure CLI and selects the target subscription.
      2. Enables `microsoft-entra-auth` on the Flexible Server
         (keeps password auth ON by default for safety; opt into Entra-only with -EntraOnly).
      3. Adds the currently signed-in Azure CLI user as an Entra administrator.
      4. Optionally adds a user-assigned managed identity (UAMI) as an Entra administrator
         (Type = ServicePrincipal, which is correct for both UAMI and SAMI).
      5. Prints a ready-to-use psql connection snippet that uses a fresh access token.

    Defaults target the `talent-devtest` environment for this repo
    (server tiqpgsql66lb, resource group rg-talent-devtest).

.PARAMETER ServerName
    PostgreSQL Flexible Server name (without the `.postgres.database.azure.com` suffix).

.PARAMETER ResourceGroup
    Resource group containing the server.

.PARAMETER SubscriptionId
    Azure subscription ID. If omitted, the CLI's current subscription is used.

.PARAMETER ManagedIdentityName
    Optional. Name of a user-assigned managed identity to add as an Entra admin.

.PARAMETER ManagedIdentityResourceGroup
    Resource group of the managed identity. Defaults to -ResourceGroup if omitted.

.PARAMETER EntraOnly
    If set, also disables password authentication (Entra-only mode).
    Default keeps both PostgreSQL and Entra authentication enabled.

.PARAMETER SkipAddSelf
    If set, do NOT add the current signed-in user as Entra admin.

.EXAMPLE
    # Minimal: add yourself (az login user) as Entra admin, keep password auth on
    ./Enable-PostgresEntraAuth.ps1

.EXAMPLE
    # Add yourself + a managed identity used by the backend container app
    ./Enable-PostgresEntraAuth.ps1 -ManagedIdentityName id-talentiq-backend

.EXAMPLE
    # Only add a managed identity (do not add yourself), and switch to Entra-only auth
    ./Enable-PostgresEntraAuth.ps1 `
        -ManagedIdentityName id-talentiq-backend `
        -SkipAddSelf `
        -EntraOnly

.NOTES
    Requires: Azure CLI 2.53+ signed in (`az login`) with rights on the server
    (Contributor or PostgreSQL-specific role).
#>
[CmdletBinding()]
param(
    [string]$ServerName = 'tiqpgsql66lb',
    [string]$ResourceGroup = 'rg-talent-devtest',
    [string]$SubscriptionId = 'e4718866-4e88-411f-a0b8-10c8051dc165',
    [string]$ManagedIdentityName,
    [string]$ManagedIdentityResourceGroup,
    [switch]$EntraOnly,
    [switch]$SkipAddSelf
)

$ErrorActionPreference = 'Stop'

function Write-Step  { param([string]$Msg) Write-Host "==> $Msg" -ForegroundColor Cyan }
function Write-Ok    { param([string]$Msg) Write-Host "    OK  $Msg" -ForegroundColor Green }
function Write-Info  { param([string]$Msg) Write-Host "    $Msg" -ForegroundColor Gray }
function Write-Warn2 { param([string]$Msg) Write-Host "    !!  $Msg" -ForegroundColor Yellow }

# -------------------------------------------------------------------------
# 0. Prerequisites
# -------------------------------------------------------------------------
Write-Step 'Verifying Azure CLI sign-in'
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    throw "Not signed in. Run 'az login' first."
}
Write-Ok "Signed in as $($account.user.name) (tenant $($account.tenantId))"

if ($SubscriptionId) {
    Write-Step "Setting subscription to $SubscriptionId"
    az account set --subscription $SubscriptionId | Out-Null
    Write-Ok 'Subscription set'
}

# Confirm server exists
Write-Step "Checking server $ServerName in $ResourceGroup"
$server = az postgres flexible-server show `
    --resource-group $ResourceGroup `
    --name $ServerName `
    --output json 2>$null | ConvertFrom-Json
if (-not $server) {
    throw "PostgreSQL Flexible Server '$ServerName' not found in resource group '$ResourceGroup'."
}
Write-Ok "Found server $($server.fullyQualifiedDomainName)"

# -------------------------------------------------------------------------
# 1. Enable Entra ID authentication on the server
# -------------------------------------------------------------------------
$currentAuthCfg = $server.authConfig
$entraAuthEnabled = $currentAuthCfg.activeDirectoryAuth -eq 'Enabled'
$pwAuthEnabled    = $currentAuthCfg.passwordAuth        -eq 'Enabled'

Write-Step 'Current authentication configuration'
Write-Info "ActiveDirectoryAuth: $($currentAuthCfg.activeDirectoryAuth)"
Write-Info "PasswordAuth:        $($currentAuthCfg.passwordAuth)"
Write-Info "TenantId:            $($currentAuthCfg.tenantId)"

$desiredPwAuth = if ($EntraOnly.IsPresent) { 'Disabled' } else { 'Enabled' }
$needsUpdate = (-not $entraAuthEnabled) -or ($currentAuthCfg.passwordAuth -ne $desiredPwAuth)

if ($needsUpdate) {
    Write-Step "Enabling Entra auth (password-auth = $desiredPwAuth)"
    az postgres flexible-server update `
        --resource-group $ResourceGroup `
        --name $ServerName `
        --microsoft-entra-auth Enabled `
        --password-auth $desiredPwAuth `
        --output none
    Write-Ok 'Authentication configuration updated'
} else {
    Write-Ok 'Entra auth already enabled with desired password-auth setting'
}

# -------------------------------------------------------------------------
# 2. Add the currently signed-in user as an Entra admin
# -------------------------------------------------------------------------
if (-not $SkipAddSelf) {
    Write-Step 'Adding current signed-in user as Entra admin'
    $me = az ad signed-in-user show --output json | ConvertFrom-Json
    $myObjectId = $me.id
    $myUpn      = $me.userPrincipalName
    Write-Info "User: $myUpn ($myObjectId)"

    $existing = az postgres flexible-server microsoft-entra-admin list `
        --resource-group $ResourceGroup `
        --server-name $ServerName `
        --output json 2>$null | ConvertFrom-Json

    if ($existing | Where-Object { $_.objectId -eq $myObjectId }) {
        Write-Ok 'User already an Entra admin'
    } else {
        az postgres flexible-server microsoft-entra-admin create `
            --resource-group $ResourceGroup `
            --server-name $ServerName `
            --display-name $myUpn `
            --object-id $myObjectId `
            --type User `
            --output none
        Write-Ok "Added $myUpn as Entra admin"
    }
}

# -------------------------------------------------------------------------
# 3. Optionally add a user-assigned managed identity as an Entra admin
# -------------------------------------------------------------------------
if ($ManagedIdentityName) {
    $miRg = if ($ManagedIdentityResourceGroup) { $ManagedIdentityResourceGroup } else { $ResourceGroup }
    Write-Step "Adding managed identity '$ManagedIdentityName' (rg=$miRg) as Entra admin"

    $mi = az identity show `
        --name $ManagedIdentityName `
        --resource-group $miRg `
        --output json 2>$null | ConvertFrom-Json
    if (-not $mi) {
        throw "Managed identity '$ManagedIdentityName' not found in resource group '$miRg'."
    }
    Write-Info "principalId: $($mi.principalId)"
    Write-Info "clientId:    $($mi.clientId)"

    $existing = az postgres flexible-server microsoft-entra-admin list `
        --resource-group $ResourceGroup `
        --server-name $ServerName `
        --output json 2>$null | ConvertFrom-Json

    if ($existing | Where-Object { $_.objectId -eq $mi.principalId }) {
        Write-Ok 'Managed identity already an Entra admin'
    } else {
        # Managed identities are added with Type = ServicePrincipal
        az postgres flexible-server microsoft-entra-admin create `
            --resource-group $ResourceGroup `
            --server-name $ServerName `
            --display-name $ManagedIdentityName `
            --object-id $mi.principalId `
            --type ServicePrincipal `
            --output none
        Write-Ok "Added managed identity '$ManagedIdentityName' as Entra admin"
    }
}

# -------------------------------------------------------------------------
# 4. Summary + connection snippet
# -------------------------------------------------------------------------
Write-Step 'Current Entra administrators'
az postgres flexible-server microsoft-entra-admin list `
    --resource-group $ResourceGroup `
    --server-name $ServerName `
    --output table

$fqdn = $server.fullyQualifiedDomainName
$dbName = 'postgres'

Write-Host ''
Write-Step 'Connect with your az CLI identity (token expires in 5-60 min):'
Write-Host @"
    `$env:PGPASSWORD = (az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
    psql "host=$fqdn user=$($me.userPrincipalName) dbname=$dbName sslmode=require"
"@ -ForegroundColor White

if ($ManagedIdentityName) {
    Write-Host ''
    Write-Step 'Connect from code with the managed identity (Python azure-identity example):'
    Write-Host @"
    from azure.identity import ManagedIdentityCredential
    cred = ManagedIdentityCredential(client_id="$($mi.clientId)")
    token = cred.get_token("https://ossrdbms-aad.database.windows.net/.default").token

    # Use this token as the PostgreSQL password.
    # Username = the managed identity display name: $ManagedIdentityName
    # Host     = $fqdn
"@ -ForegroundColor White
}

Write-Host ''
Write-Ok 'Done.'
