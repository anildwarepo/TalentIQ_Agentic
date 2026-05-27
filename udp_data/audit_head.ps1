$ErrorActionPreference = 'Stop'

$files = @(
    'talent_infra_modules/shared/common.ps1',
    'talent_infra_modules/02-backend/deploy.ps1',
    'talent_infra_modules/03-frontend/deploy.ps1',
    'talent_infra_modules/04-data-loading/deploy.ps1',
    'talent_infra_modules/00-container-apps-env/deploy.ps1'
)

foreach ($f in $files) {
    Write-Host "==================================================================="
    Write-Host "FILE: $f"
    Write-Host "==================================================================="

    $bytes = [System.IO.File]::ReadAllBytes($f)
    $bom = ($bytes.Length -ge 3) -and ($bytes[0] -eq 0xEF) -and ($bytes[1] -eq 0xBB) -and ($bytes[2] -eq 0xBF)
    $emCount = 0
    for ($i = 0; $i -le $bytes.Length - 3; $i++) {
        if ($bytes[$i] -eq 0xE2 -and $bytes[$i+1] -eq 0x80 -and $bytes[$i+2] -eq 0x94) { $emCount++ }
    }
    Write-Host "  HEAD bytes: $($bytes.Length)  BOM: $bom  em-dash count: $emCount"

    # Count regression pattern: <whitespace>-<word> with single space before dash and space after
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    $regressionMatches = [regex]::Matches($text, "(?m)^\s+-\s+\w+")
    Write-Host "  Regression pattern '^\s+-\s+\w+' matches: $($regressionMatches.Count)"
    if ($regressionMatches.Count -gt 0 -and $regressionMatches.Count -lt 10) {
        foreach ($m in $regressionMatches) { Write-Host "    > $($m.Value.Trim())" }
    }
}
