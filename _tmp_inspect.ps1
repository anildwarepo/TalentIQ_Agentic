$line = (Get-Content c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1)[438]
Write-Host "Length: $($line.Length)"
Write-Host "Content: |$line|"
$col = 49
if ($col -le $line.Length) {
    Write-Host "Char at col $col`: |$($line[$col-1])| (0x$('{0:X}' -f [int]$line[$col-1]))"
    $startIdx = [Math]::Max(0, $col-10)
    $len = [Math]::Min(20, $line.Length - $startIdx)
    Write-Host "Context col $($startIdx+1)-$($startIdx+$len)`: |$($line.Substring($startIdx, $len))|"
} else {
    Write-Host "Line is shorter than col $col"
}
# Also dump 437-441
437..441 | ForEach-Object {
    $l = (Get-Content c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1)[$_ - 1]
    Write-Host "L${_} (len $($l.Length)): $l"
}
