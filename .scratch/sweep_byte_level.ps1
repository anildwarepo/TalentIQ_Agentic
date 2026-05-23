#requires -Version 5.1
<#
    Byte-level non-ASCII-only substitution sweep for .ps1 files.

    Reads each file as raw bytes, decodes as UTF-8 to a .NET string,
    iterates char-by-char. For each char:
      - If codepoint < 0x80 (ASCII): passthrough UNTOUCHED.
      - If codepoint in $subs: emit ASCII replacement.
      - Otherwise: emit '?' and warn (tracked in unknown[]).
    Writes back with UTF-8-with-BOM encoding.

    NEVER applies regex to ASCII bytes. This is the cardinal rule.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)] [string] $Path,
    [Parameter()] [string] $SourceContent
)

$ErrorActionPreference = 'Stop'

# Substitution table — keys are non-ASCII codepoints (>= 0x80), values are ASCII replacements.
$subs = @{
    0x2014 = ' - '       # U+2014 em-dash
    0x2013 = '-'         # U+2013 en-dash
    0x2018 = "'"         # U+2018 left single quote
    0x2019 = "'"         # U+2019 right single quote
    0x201C = '"'         # U+201C left double quote
    0x201D = '"'         # U+201D right double quote
    0x00A0 = ' '         # U+00A0 non-breaking space
    0x2026 = '...'       # U+2026 horizontal ellipsis
    0x2192 = '->'        # U+2192 right arrow
    0x2190 = '<-'        # U+2190 left arrow
    0x2500 = '-'         # U+2500 box drawing horizontal
    0x2194 = '<->'       # U+2194 left-right arrow
    0x2550 = '='         # U+2550 box drawing double horizontal
    0x2588 = '#'         # U+2588 full block
    0x26A0 = '[WARN]'    # U+26A0 warning sign
    0x2705 = '[OK]'      # U+2705 check mark button
    0x2713 = '[OK]'      # U+2713 check mark
    0xFEFF = ''          # U+FEFF BOM — strip from interior; we add a fresh leading BOM via encoding
}

if ($SourceContent) {
    $text = $SourceContent
} else {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $text  = [System.Text.Encoding]::UTF8.GetString($bytes)
}

$sb        = New-Object System.Text.StringBuilder
$subCount  = 0
$asciiCount= 0
$unknown   = @{}

foreach ($ch in $text.ToCharArray()) {
    $cp = [int]$ch
    if ($cp -lt 0x80) {
        # ASCII passthrough — NEVER touch
        [void]$sb.Append($ch)
        $asciiCount++
    } elseif ($subs.ContainsKey($cp)) {
        [void]$sb.Append($subs[$cp])
        $subCount++
    } else {
        # Unknown non-ASCII — emit '?' and track
        [void]$sb.Append('?')
        $key = "U+{0:X4}" -f $cp
        if ($unknown.ContainsKey($key)) { $unknown[$key]++ } else { $unknown[$key] = 1 }
    }
}

$result = $sb.ToString()

# Write back with UTF-8-with-BOM (BOM emitted via encoding ctor $true)
$utf8WithBom = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText($Path, $result, $utf8WithBom)

# Verify BOM
$writtenBytes = [System.IO.File]::ReadAllBytes($Path)
$bomOk = ($writtenBytes.Length -ge 3) -and ($writtenBytes[0] -eq 0xEF) -and ($writtenBytes[1] -eq 0xBB) -and ($writtenBytes[2] -eq 0xBF)

# Verify no non-ASCII remains in written file (other than the leading BOM bytes)
$residualNonAscii = 0
for ($i = 3; $i -lt $writtenBytes.Length; $i++) {
    if ($writtenBytes[$i] -ge 0x80) { $residualNonAscii++ }
}

[pscustomobject]@{
    Path             = $Path
    ASCIIChars       = $asciiCount
    Substituted      = $subCount
    UnknownCount     = ($unknown.Values | Measure-Object -Sum).Sum
    UnknownByCode    = $unknown
    BomVerified      = $bomOk
    ResidualNonAscii = $residualNonAscii
    OutputBytes      = $writtenBytes.Length
}
