$lines = Get-Content c:\repos\TalentIQ_Agentic\talent_infra_modules\03-frontend\deploy.ps1
Write-Host "Total lines: $($lines.Count)"
246..248 | ForEach-Object { Write-Host "L${_}: $($lines[$_ - 1])" }
Write-Host "---"
260..268 | ForEach-Object { Write-Host "L${_}: $($lines[$_ - 1])" }
Write-Host "---"
436..442 | ForEach-Object { Write-Host "L${_}: $($lines[$_ - 1])" }
