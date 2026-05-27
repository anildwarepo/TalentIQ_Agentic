$ErrorActionPreference = 'Stop'
$f = "talent_infra_modules/01-postgresql/deploy.ps1"

Write-Host "==> Lines 118-135 of $f"
$lines = Get-Content $f
for ($i = 117; $i -le 134; $i++) {
    "{0,3}: {1}" -f ($i + 1), $lines[$i]
}
Write-Host ""

$bytes = [System.IO.File]::ReadAllBytes($f)
$emCount = 0
for ($i = 0; $i -le $bytes.Length - 3; $i++) {
    if ($bytes[$i] -eq 0xE2 -and $bytes[$i+1] -eq 0x80 -and $bytes[$i+2] -eq 0x94) { $emCount++ }
}
$bom = ($bytes[0] -eq 0xEF) -and ($bytes[1] -eq 0xBB) -and ($bytes[2] -eq 0xBF)
Write-Host "==> Byte audit"
Write-Host "  Em-dash (E2 80 94) count: $emCount"
Write-Host "  BOM present: $bom"
Write-Host "  Total bytes: $($bytes.Length)"

# Also enumerate any non-ASCII codepoints present
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$nonAscii = @{}
foreach ($ch in $text.ToCharArray()) {
    $cp = [int]$ch
    if ($cp -ge 0x80) {
        $key = ("U+{0:X4}" -f $cp)
        if ($nonAscii.ContainsKey($key)) { $nonAscii[$key]++ } else { $nonAscii[$key] = 1 }
    }
}
Write-Host "==> Non-ASCII codepoints in file:"
if ($nonAscii.Count -eq 0) {
    Write-Host "  (none — pure ASCII)"
} else {
    $nonAscii.GetEnumerator() | Sort-Object Name | ForEach-Object { "  {0} => {1}" -f $_.Name, $_.Value }
}
