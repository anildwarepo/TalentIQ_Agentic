#requires -Version 5.1
<#
    Re-sweep talent_infra_modules/01-postgresql/deploy.ps1 from HEAD~2 (pristine pre-sweep).

    Bypasses PowerShell's stdout decoding by writing git blob bytes directly to a temp file
    via cmd.exe redirection (byte-level), then reading raw bytes via .NET.
#>

$ErrorActionPreference = 'Stop'
$file = 'talent_infra_modules/01-postgresql/deploy.ps1'
$tmp  = [System.IO.Path]::GetTempFileName()

try {
    # cmd.exe '>' redirection is byte-level; git emits raw blob bytes.
    cmd.exe /c "git show HEAD~2:$file > `"$tmp`""
    if ($LASTEXITCODE -ne 0) { throw "git show failed with exit $LASTEXITCODE" }

    $rawBytes = [System.IO.File]::ReadAllBytes($tmp)
    Write-Host "Captured $($rawBytes.Length) bytes from HEAD~2:$file"

    # Verify we have the expected em-dash byte sequence (E2 80 94)
    $emCount = 0
    for ($i = 0; $i -le $rawBytes.Length - 3; $i++) {
        if ($rawBytes[$i] -eq 0xE2 -and $rawBytes[$i+1] -eq 0x80 -and $rawBytes[$i+2] -eq 0x94) { $emCount++ }
    }
    Write-Host "Em-dash (E2 80 94) byte sequences in captured blob: $emCount"
    if ($emCount -eq 0) { throw "Captured blob has no em-dashes — capture likely failed" }

    $text = [System.Text.Encoding]::UTF8.GetString($rawBytes)

    # Now apply the byte-level sweep (same as sweep_byte_level.ps1)
    $subs = @{
        0x2014 = ' - '
        0x2013 = '-'
        0x2018 = "'"
        0x2019 = "'"
        0x201C = '"'
        0x201D = '"'
        0x00A0 = ' '
        0x2026 = '...'
        0x2192 = '->'
        0x2190 = '<-'
        0x2500 = '-'
        0x2194 = '<->'
        0x2550 = '='
        0x2588 = '#'
        0x26A0 = '[WARN]'
        0x2705 = '[OK]'
        0x2713 = '[OK]'
        0xFEFF = ''
    }

    $sb = New-Object System.Text.StringBuilder
    $subCount = 0
    $asciiCount = 0
    $unknown = @{}
    foreach ($ch in $text.ToCharArray()) {
        $cp = [int]$ch
        if ($cp -lt 0x80) {
            [void]$sb.Append($ch)
            $asciiCount++
        } elseif ($subs.ContainsKey($cp)) {
            [void]$sb.Append($subs[$cp])
            $subCount++
        } else {
            [void]$sb.Append('?')
            $key = "U+{0:X4}" -f $cp
            if ($unknown.ContainsKey($key)) { $unknown[$key]++ } else { $unknown[$key] = 1 }
        }
    }

    $result = $sb.ToString()
    $utf8WithBom = New-Object System.Text.UTF8Encoding $true
    [System.IO.File]::WriteAllText($file, $result, $utf8WithBom)

    $writtenBytes = [System.IO.File]::ReadAllBytes($file)
    $bomOk = ($writtenBytes.Length -ge 3) -and ($writtenBytes[0] -eq 0xEF) -and ($writtenBytes[1] -eq 0xBB) -and ($writtenBytes[2] -eq 0xBF)
    $residual = 0
    for ($i = 3; $i -lt $writtenBytes.Length; $i++) {
        if ($writtenBytes[$i] -ge 0x80) { $residual++ }
    }

    Write-Host ""
    Write-Host "==> Re-sweep report for $file"
    Write-Host "  ASCII chars (passthrough)  : $asciiCount"
    Write-Host "  Non-ASCII chars substituted: $subCount"
    Write-Host "  Unknown non-ASCII chars    : $(($unknown.Values | Measure-Object -Sum).Sum)"
    if ($unknown.Count -gt 0) {
        $unknown.GetEnumerator() | Sort-Object Name | ForEach-Object {
            Write-Host "    $($_.Name) => $($_.Value)"
        }
    }
    Write-Host "  BOM verified               : $bomOk"
    Write-Host "  Residual non-ASCII bytes   : $residual"
    Write-Host "  Output bytes               : $($writtenBytes.Length)"
}
finally {
    Remove-Item $tmp -ErrorAction SilentlyContinue
}
