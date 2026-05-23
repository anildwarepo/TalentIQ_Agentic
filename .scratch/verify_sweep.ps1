#requires -Version 5.1
<#
    Step 7-9: Regression smoke test + dual-engine parse test + line 118-135 excerpt.
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

Write-Host "============================================================"
Write-Host "STEP 7 — Regression smoke test"
Write-Host "  Pattern: '^\s+-\s+\w+' (leading whitespace + dash + space + word)"
Write-Host "  ANY match is a regression of the mangled-parameter bug."
Write-Host "============================================================"

$regressionTotal = 0
foreach ($f in $files) {
    $hits = Select-String -Path $f -Pattern '^\s+-\s+\w+' -AllMatches
    $count = 0
    if ($hits) { $count = ($hits | ForEach-Object { $_.Matches.Count } | Measure-Object -Sum).Sum }
    $regressionTotal += $count
    if ($count -gt 0) {
        Write-Host "  REGRESSION in $f : $count hits"
        $hits | Select-Object -First 3 | ForEach-Object { Write-Host "    L$($_.LineNumber): $($_.Line.Trim())" }
    } else {
        Write-Host "  OK       $f"
    }
}
Write-Host ""
Write-Host "Total regression matches: $regressionTotal"
if ($regressionTotal -gt 0) { Write-Host "REGRESSION DETECTED — sweep is broken." -ForegroundColor Red }

Write-Host ""
Write-Host "============================================================"
Write-Host "STEP 8a — Parse test in pwsh 7+ (in-session)"
Write-Host "============================================================"
foreach ($f in $files) {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $f), [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) {
        Write-Host "  FAIL  $f : $($errors.Count) parse errors" -ForegroundColor Red
        $errors | Select-Object -First 2 | ForEach-Object { Write-Host "    L$($_.Extent.StartLineNumber): $($_.Message)" }
    } else {
        Write-Host "  OK    $f"
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host "STEP 8b — Parse test in Windows PowerShell 5.1 (external)"
Write-Host "  NOTE: 02-backend/deploy.ps1 EXPECTED to FAIL (?. and ?? are pwsh-7+ syntax)."
Write-Host "============================================================"
foreach ($f in $files) {
    $resolved = (Resolve-Path $f).Path
    $cmd = @"
`$tokens = `$null
`$errors = `$null
`$null = [System.Management.Automation.Language.Parser]::ParseFile('$($resolved.Replace("'", "''"))', [ref]`$tokens, [ref]`$errors)
if (`$errors.Count -gt 0) { Write-Output ('FAIL: ' + `$errors.Count); `$errors | Select-Object -First 2 | ForEach-Object { Write-Output ('  L' + `$_.Extent.StartLineNumber + ': ' + `$_.Message) } } else { Write-Output 'OK' }
"@
    $out = powershell.exe -NoProfile -Command $cmd 2>&1 | Out-String
    $out = $out.Trim()
    if ($out -like 'OK*') {
        Write-Host "  OK    $f"
    } elseif ($f -ieq 'talent_infra_modules/02-backend/deploy.ps1') {
        Write-Host "  EXPECT_FAIL_PS7_ONLY $f"
        $out -split "`r?`n" | ForEach-Object { Write-Host "    $_" }
    } else {
        Write-Host "  FAIL  $f" -ForegroundColor Red
        $out -split "`r?`n" | ForEach-Object { Write-Host "    $_" }
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host "STEP 9 — Visual confirmation: 01-postgresql/deploy.ps1 lines 118-135"
Write-Host "============================================================"
$lines = Get-Content 'talent_infra_modules/01-postgresql/deploy.ps1'
for ($i = 117; $i -le 134; $i++) {
    "{0,3}: {1}" -f ($i + 1), $lines[$i]
}
