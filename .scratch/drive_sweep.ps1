#requires -Version 5.1
<#
    Driver: apply byte-level non-ASCII-only sweep to all 12 files.

    Special handling for talent_infra_modules/01-postgresql/deploy.ps1:
      HEAD content was committed with regex-mangled parameter prefixes (commit 53a94e9).
      Source from HEAD~2 (pristine pre-sweep content) instead of the working tree.
      All OTHER 11 files: source from working tree (which now matches pristine HEAD post-rollback).
#>

$ErrorActionPreference = 'Stop'

$files = @(
    'talent_infra_modules/shared/common.ps1'
    'talent_infra_modules/01-postgresql/deploy.ps1'
    'talent_infra_modules/02-backend/deploy.ps1'
    'talent_infra_modules/03-frontend/deploy.ps1'
    'talent_infra_modules/04-data-loading/deploy.ps1'
    'talent_infra_modules/00-container-apps-env/deploy.ps1'
    'talent_infra/hooks/postprovision.ps1'
    'talent_infra_v2/hooks/postprovision.ps1'
    'talent_infra/hooks/postup.ps1'
    'talent_infra_v2/hooks/postup.ps1'
    'talent_infra/hooks/preprovision.ps1'
    'talent_infra_v2/hooks/preprovision.ps1'
)

$pgFile  = 'talent_infra_modules/01-postgresql/deploy.ps1'
$sweeper = Join-Path $PSScriptRoot 'sweep_byte_level.ps1'
$report  = @()

foreach ($f in $files) {
    Write-Host "==> Sweeping $f"
    if ($f -ieq $pgFile) {
        # Source from HEAD~2 — pristine pre-sweep content.
        $source = git show "HEAD~2:$f"
        if (-not $source) { throw "Failed to retrieve HEAD~2 content for $f" }
        # git show returns string[] when piped; join with LF to preserve line endings.
        $sourceText = ($source -join "`n")
        # Add trailing newline if missing (git show strips the final newline in some cases)
        if (-not $sourceText.EndsWith("`n")) { $sourceText += "`n" }
        $r = & $sweeper -Path $f -SourceContent $sourceText
    } else {
        $r = & $sweeper -Path $f
    }
    $report += $r
}

Write-Host ""
Write-Host "============================================================"
Write-Host "SWEEP REPORT"
Write-Host "============================================================"
$report | ForEach-Object {
    Write-Host ""
    Write-Host "FILE: $($_.Path)"
    Write-Host "  ASCII chars (passthrough)  : $($_.ASCIIChars)"
    Write-Host "  Non-ASCII chars substituted: $($_.Substituted)"
    Write-Host "  Unknown non-ASCII chars    : $($_.UnknownCount)"
    if ($_.UnknownByCode.Count -gt 0) {
        Write-Host "  Unknown codepoints:"
        $_.UnknownByCode.GetEnumerator() | Sort-Object Name | ForEach-Object {
            Write-Host "    $($_.Name) => $($_.Value) occurrences"
        }
    }
    Write-Host "  BOM verified               : $($_.BomVerified)"
    Write-Host "  Residual non-ASCII bytes   : $($_.ResidualNonAscii)"
    Write-Host "  Output bytes               : $($_.OutputBytes)"
}
