<#
.SYNOPSIS
    Deploy PostgreSQL using the Dev EUS shared network parameters.
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$Location = "eastus",
    [string]$ServerName,
    [SecureString]$AdminPassword,
    [string]$ExtraEntraUserUpns = "anil.dwarakanath@dxc.com",
    [switch]$Force,
    [switch]$EntraOnly
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$deployScript = Join-Path $scriptDir "deploy.ps1"

$params = @{
    ResourceGroup = "RG-Mgmt-AI-Apps-Dev-EUS"
    Location = $Location
    VnetResourceGroup = "RG-Mgmt-AI-Apps-Dev-EUS"
    VnetName = "VNET-Mgmt-AI-Apps-Dev-EUS"
    PeSubnetName = "SNET-Private-Endpoints"
    EnablePrivateEndpoint = $true
    ExtraEntraUserUpns = $ExtraEntraUserUpns
}

if (-not [string]::IsNullOrEmpty($SubscriptionId)) { $params.SubscriptionId = $SubscriptionId }
if (-not [string]::IsNullOrEmpty($ServerName)) { $params.ServerName = $ServerName }
if ($null -ne $AdminPassword -and $AdminPassword.Length -gt 0) { $params.AdminPassword = $AdminPassword }
if ($Force) { $params.Force = $true }
if ($EntraOnly) { $params.EntraOnly = $true }

& $deployScript @params
