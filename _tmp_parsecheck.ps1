$errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile('c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1', [ref]$null, [ref]$errors)
if ($errors -and $errors.Count -gt 0) {
    $errors | ForEach-Object { "$($_.Extent.StartLineNumber):$($_.Extent.StartColumnNumber)  $($_.Message)" }
    exit 1
} else {
    'OK - no parse errors'
}
