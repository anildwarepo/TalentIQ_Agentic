$f = 'c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1'
$all = Get-Content $f
425..445 | ForEach-Object {
    $l = $all[$_ - 1]
    Write-Host ("L{0,3} ({1,3}): {2}" -f $_, $l.Length, $l)
}
