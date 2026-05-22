$bytes = [System.IO.File]::ReadAllBytes("c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1")
$content = [System.Text.Encoding]::UTF8.GetString($bytes)
$replaced = $content -replace [char]0x2014, '-' -replace [char]0x2013, '-' -replace [char]0x2018, "''" -replace [char]0x2019, "''"
[System.IO.File]::WriteAllText("c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1", $replaced, [System.Text.UTF8Encoding]::new($false))
Write-Host "Replaced em-dashes and smart quotes. Bytes before: $($bytes.Length); after: $((Get-Item c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1).Length)"
