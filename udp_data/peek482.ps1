$lines = Get-Content talent_infra_modules/shared/common.ps1
for ($i = 478; $i -le 488; $i++) {
    "{0,4}: {1}" -f ($i + 1), $lines[$i]
}
