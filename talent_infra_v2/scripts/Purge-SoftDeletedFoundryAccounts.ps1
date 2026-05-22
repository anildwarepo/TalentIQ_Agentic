<#
.SYNOPSIS
    Purge all soft-deleted Azure AI Foundry / Cognitive Services accounts (and the
    AI Foundry projects they contain) to permanently release names and quota.

.DESCRIPTION
    When you delete an Azure AI Services / Cognitive Services / OpenAI / Foundry
    account (kind = `AIServices`, `OpenAI`, `CognitiveServices`, ...), Azure puts
    it into a soft-deleted state for 48 hours. During that window:

      * The account name (and FQDN) cannot be re-used in the same region.
      * Any model deployments under the account continue to consume the
        subscription's regional model quota
        (e.g. `gpt-4.1 GlobalStandard` TPM, `text-embedding-ada-002` TPM).
      * Any Foundry projects under the account remain soft-deleted with the
        parent and are purged automatically when the account is purged.

    This script enumerates every soft-deleted Cognitive Services / AI Foundry
    account in the current subscription (optionally filtered by region or kind),
    shows you what it will do, and then permanently purges each one
    (`az cognitiveservices account purge`). Purge is irreversible.

    By default the script runs in WhatIf mode (no destructive action) and prints
    the inventory plus the exact purge commands it would run. Pass `-Confirm:$false`
    AND `-WhatIf:$false` (or just `-Force`) to actually purge.

.PARAMETER SubscriptionId
    Azure subscription ID. If omitted, the CLI's currently selected subscription
    is used. Required if you want to target a different sub than the one the
    CLI currently has active.

.PARAMETER Location
    Optional. Only purge soft-deleted accounts in this Azure region (e.g.
    `westus`, `eastus2`). Match is case-insensitive. When omitted, all regions
    are purged.

.PARAMETER NamePattern
    Optional. Regex match on the account name. Useful for limiting to a project
    prefix (e.g. `^tiqai`) so you don't accidentally purge unrelated accounts
    in a shared subscription. Match is case-insensitive.

.PARAMETER Kind
    Optional. Filter by account `kind`. Accepts one or more values, e.g.
    `AIServices`, `OpenAI`, `CognitiveServices`. When omitted, ALL kinds are
    considered.

.PARAMETER Force
    Skip the interactive confirmation prompt AND run the purge for real.
    Equivalent to passing `-Confirm:$false -WhatIf:$false`. Without `-Force`
    (or explicit `-WhatIf:$false`), the script only prints what it WOULD do.

.EXAMPLE
    # Dry run — list all soft-deleted accounts across the current subscription.
    .\Purge-SoftDeletedFoundryAccounts.ps1

.EXAMPLE
    # Dry run scoped to one region and one name prefix.
    .\Purge-SoftDeletedFoundryAccounts.ps1 -Location westus -NamePattern '^tiqai'

.EXAMPLE
    # Actually purge every soft-deleted AI Foundry account in westus.
    .\Purge-SoftDeletedFoundryAccounts.ps1 -Location westus -Kind AIServices -Force

.NOTES
    Requires:
      * Azure CLI (`az`) signed in (`az login`).
      * Caller must have `Microsoft.CognitiveServices/locations/deletedAccounts/delete`
        permission on the subscription (Contributor or higher on the sub typically works).

    Verifies and re-runs against API surface:
      `az cognitiveservices account list-deleted` / `purge`
      (Azure REST `Microsoft.CognitiveServices/locations/{loc}/resourceGroups/{rg}/deletedAccounts/{name}`)

    Foundry projects (child of an `AIServices` account) do NOT have their own
    soft-delete surface. They are purged together with the parent account.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string] $SubscriptionId,
    [string] $Location,
    [string] $NamePattern,
    [string[]] $Kind,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

# ── 0. Pre-flight: az CLI present + signed in ──────────────────────────────
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI ('az') not found on PATH. Install from https://aka.ms/installazurecli."
}

$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    throw "Not signed in to Azure CLI. Run 'az login' first."
}

if ($SubscriptionId) {
    Write-Host "Selecting subscription $SubscriptionId" -ForegroundColor Cyan
    az account set --subscription $SubscriptionId | Out-Null
    $account = az account show | ConvertFrom-Json
}

Write-Host ""
Write-Host "Subscription : $($account.name) ($($account.id))" -ForegroundColor Cyan
Write-Host "Tenant       : $($account.tenantId)"               -ForegroundColor Cyan
Write-Host ""

# ── 1. Inventory soft-deleted Cognitive Services / AI Foundry accounts ────
Write-Host "Listing soft-deleted Cognitive Services accounts..." -ForegroundColor Cyan
$deletedJson = az cognitiveservices account list-deleted -o json 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "az cognitiveservices account list-deleted failed: $deletedJson"
}

$deleted = @($deletedJson | ConvertFrom-Json)
if ($deleted.Count -eq 0) {
    Write-Host "No soft-deleted Cognitive Services / Foundry accounts found." -ForegroundColor Green
    return
}

# ── 2. Apply filters ──────────────────────────────────────────────────────
$filtered = $deleted
if ($Location) {
    $filtered = $filtered | Where-Object { $_.location -ieq $Location }
}
if ($NamePattern) {
    $filtered = $filtered | Where-Object { $_.name -imatch $NamePattern }
}
if ($Kind) {
    $kindSet = $Kind | ForEach-Object { $_.ToLowerInvariant() }
    $filtered = $filtered | Where-Object { $kindSet -contains $_.kind.ToLowerInvariant() }
}

# Each entry's id is of the form:
#   /subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{loc}/resourceGroups/{rg}/deletedAccounts/{name}
# `az cognitiveservices account purge` needs --location, --resource-group, --name.
$rows = @()
foreach ($d in $filtered) {
    $rg = $null
    if ($d.id -match '/resourceGroups/([^/]+)/deletedAccounts/') {
        $rg = $Matches[1]
    }
    $rows += [pscustomobject]@{
        Name          = $d.name
        Kind          = $d.kind
        Sku           = if ($d.sku) { $d.sku.name } else { '' }
        Location      = $d.location
        ResourceGroup = $rg
        DeletionDate  = $d.deletionDate
        ScheduledPurge = $d.scheduledPurgeDate
        Id            = $d.id
    }
}

if ($rows.Count -eq 0) {
    Write-Host "No soft-deleted accounts matched the supplied filters." -ForegroundColor Green
    Write-Host "(Unfiltered total was $($deleted.Count))." -ForegroundColor DarkGray
    return
}

Write-Host ""
Write-Host "Found $($rows.Count) soft-deleted account(s):" -ForegroundColor Yellow
$rows | Format-Table Name, Kind, Sku, Location, ResourceGroup, DeletionDate, ScheduledPurge -AutoSize | Out-String | Write-Host

# ── 3. Confirm and purge ──────────────────────────────────────────────────
if (-not $Force -and -not $PSCmdlet.ShouldProcess("$($rows.Count) account(s)", "Purge (irreversible)")) {
    Write-Host "Dry-run mode. No accounts purged." -ForegroundColor Yellow
    Write-Host "Re-run with -Force to actually purge, or with -WhatIf:`$false to confirm interactively." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Equivalent purge commands:" -ForegroundColor DarkGray
    foreach ($r in $rows) {
        Write-Host "  az cognitiveservices account purge --location $($r.Location) --resource-group $($r.ResourceGroup) --name $($r.Name)" -ForegroundColor DarkGray
    }
    return
}

$succeeded = @()
$failed    = @()

foreach ($r in $rows) {
    $label = "$($r.Name) [$($r.Kind) @ $($r.Location), rg=$($r.ResourceGroup)]"
    Write-Host ""
    Write-Host "Purging $label ..." -ForegroundColor Cyan

    $out = az cognitiveservices account purge `
        --location $r.Location `
        --resource-group $r.ResourceGroup `
        --name $r.Name `
        2>&1
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "  OK" -ForegroundColor Green
        $succeeded += $r
    } else {
        Write-Host "  FAILED (exit=$code): $out" -ForegroundColor Red
        $failed += [pscustomobject]@{ Account = $r; ExitCode = $code; Output = "$out" }
    }
}

# ── 4. Summary ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  Purged : $($succeeded.Count) / $($rows.Count)" -ForegroundColor Green
if ($failed.Count -gt 0) {
    Write-Host "  Failed : $($failed.Count)" -ForegroundColor Red
    foreach ($f in $failed) {
        Write-Host "    - $($f.Account.Name) (exit=$($f.ExitCode))" -ForegroundColor Red
    }
    exit 1
}
