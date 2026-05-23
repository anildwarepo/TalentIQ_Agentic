$ErrorActionPreference = 'Stop'
$f = "talent_infra_modules/01-postgresql/deploy.ps1"

foreach ($rev in @("HEAD~2", "HEAD~3")) {
    Write-Host "==> $rev :"
    $content = git show "${rev}:${f}" 2>$null
    if (-not $content) {
        Write-Host "  (file does not exist at $rev)"
        continue
    }
    $lines = $content -split "`n"
    for ($i = 117; $i -le 134 -and $i -lt $lines.Length; $i++) {
        "{0,3}: {1}" -f ($i + 1), $lines[$i]
    }
    Write-Host ""
}
