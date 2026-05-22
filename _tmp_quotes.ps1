$content = Get-Content c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1 -Raw
$singleQuoteCount = ($content.ToCharArray() | Where-Object { $_ -eq "'" }).Count
Write-Host "Total single quotes: $singleQuoteCount"
$doubleQuoteCount = ($content.ToCharArray() | Where-Object { $_ -eq '"' }).Count
Write-Host "Total double quotes: $doubleQuoteCount"
# Find odd single quotes per line
$lines = Get-Content c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1
for ($i = 0; $i -lt $lines.Count; $i++) {
    $sq = ($lines[$i].ToCharArray() | Where-Object { $_ -eq "'" }).Count
    if ($sq % 2 -ne 0) {
        Write-Host "L$($i+1) has $sq single quotes (odd): $($lines[$i])"
    }
}
