<#
.SYNOPSIS
    Quick connectivity test to Azure Database for PostgreSQL Flexible Server
    using Microsoft Entra ID authentication (no passwords).

.DESCRIPTION
    Thin wrapper around test_pg_entra_connection.py. Uses your current
    Azure CLI sign-in (or a specified user-assigned managed identity) to
    acquire an Entra access token and connect to PostgreSQL.

    Defaults target the talent-devtest server (tiqpgsql66lb).

.PARAMETER Host
    PostgreSQL host FQDN. Default: tiqpgsql66lb.postgres.database.azure.com

.PARAMETER Database
    Database name. Default: postgres

.PARAMETER User
    Entra principal username (UPN for users, display name for MSI/SP).
    Default: the current az CLI signed-in user.

.PARAMETER ClientId
    Optional. clientId of a user-assigned managed identity to authenticate
    as. When set, uses ManagedIdentityCredential instead of the az CLI user.

.PARAMETER Port
    PostgreSQL port. Default: 5432

.EXAMPLE
    # Test with your az CLI user
    ./Test-PostgresEntraConnection.ps1

.EXAMPLE
    # Test as a UAMI (e.g. from a VM with that identity attached)
    ./Test-PostgresEntraConnection.ps1 -ClientId 11111111-2222-3333-4444-555555555555 -User id-talentiq-backend
#>
[CmdletBinding()]
param(
    [Alias('Host')]
    [string]$PgHost = 'tiqpgsql66lb.postgres.database.azure.com',
    [string]$Database = 'postgres',
    [string]$User,
    [string]$ClientId,
    [int]$Port = 5432
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $PSCommandPath
$pyScript  = Join-Path $scriptDir 'test_pg_entra_connection.py'

if (-not (Test-Path $pyScript)) {
    throw "Could not find $pyScript"
}

# Prefer the repo virtualenv if it exists, otherwise fall back to `python`
$repoRoot = Resolve-Path (Join-Path $scriptDir '..\..')
$venvPy   = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python   = if (Test-Path $venvPy) { $venvPy } else { 'python' }

$pyArgs = @(
    $pyScript,
    '--host',   $PgHost,
    '--port',   $Port,
    '--dbname', $Database
)
if ($User)     { $pyArgs += @('--user', $User) }
if ($ClientId) { $pyArgs += @('--client-id', $ClientId) }

Write-Host "Running: $python $($pyArgs -join ' ')" -ForegroundColor Cyan
& $python @pyArgs
exit $LASTEXITCODE
