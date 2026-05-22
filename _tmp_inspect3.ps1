$f = 'c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1'
$line = (Get-Content $f)[438]
Write-Host "Length: $($line.Length)"
$col = 116
Write-Host "Char at col $col`: |$($line[$col-1])| (0x$('{0:X}' -f [int]$line[$col-1]))"
$startIdx = [Math]::Max(0, $col-15)
$len = [Math]::Min(30, $line.Length - $startIdx)
Write-Host "Context col $($startIdx+1)..$($startIdx+$len)`: |$($line.Substring($startIdx, $len))|"
# Also try to parse just this line in isolation
$tmp = New-TemporaryFile
$tmpPath = "$($tmp.FullName).ps1"
Remove-Item $tmp.FullName -Force
$line | Set-Content -Path $tmpPath -Encoding UTF8
$errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($tmpPath, [ref]$null, [ref]$errors)
if ($errors) {
    Write-Host "Line parses with errors:"
    $errors | ForEach-Object { Write-Host "  $($_.Extent.StartLineNumber):$($_.Extent.StartColumnNumber)  $($_.Message)" }
} else {
    Write-Host "Line parses cleanly in isolation."
}
Remove-Item $tmpPath -Force
