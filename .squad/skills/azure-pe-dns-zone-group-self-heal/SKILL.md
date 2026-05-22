---
name: "azure-pe-dns-zone-group-self-heal"
description: "When a re-deploy resolves a different Private DNS zone than the one wired into an existing Private Endpoint's privateDnsZoneGroup, Bicep cannot fix the mismatch — Azure rejects in-place mutation of privateDnsZoneConfigs[*].privateDnsZoneId with UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed. This skill provides the PowerShell self-heal pattern: detect the mismatch read-only, fail loud by default, and delete the offending zone group under an explicit opt-in switch so the next Bicep run recreates it pointing at the canonical zone. Includes a conservative best-effort orphan-zone cleanup (empty + unlinked guard)."
domain: "deployment"
confidence: "low"
source: "earned"
---

## Context

Use this skill whenever a `talent_infra_modules/*/deploy.ps1` script
(or any analogous Bicep-orchestrating PowerShell deploy) provisions a
Private Endpoint into a shared subscription AND the deploy may run on
top of artifacts produced by an earlier (pre-discover-and-reuse) version
of the same script. The companion skill `azure-private-dns-discover-reuse`
covers the *resolve the canonical zone* half of the problem; **this**
skill covers the *get the existing PE to point at it* half.

### The Azure rule (load-bearing)

`Microsoft.Network/privateEndpoints/privateDnsZoneGroups` has child
`privateDnsZoneConfigs` whose `properties.privateDnsZoneId` is
**immutable** once set. Any redeploy that tries to in-place mutate it
fails fast at the Network RP with:

```
UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed:
Updating PrivateDnsZoneId on existing privateDnsZoneConfig is not allowed.
```

No amount of Bicep template wizardry routes around this — the
constraint is enforced at the ARM/Network RP layer. The ONLY
remediation is to **delete the parent `privateDnsZoneGroup`** before
the next deploy, so Bicep recreates it pointing at the right zone.

### When this triggers in practice

- A first deploy (before the `azure-private-dns-discover-reuse`
  pattern was added) created its own `privatelink.<service>.*` zone in
  the local resource group and wired the PE's `default` zone group to
  it.
- A later deploy adds the discovery patch. Discovery resolves the
  **canonical** zone in the shared network RG (e.g. `vnet`).
- Bicep tries to update the existing PE's zone group to point at the
  new zone → Azure rejects.

This happens once per environment that pre-dates the discover-and-reuse
patch. After this self-heal runs once, subsequent re-deploys are no-ops.

## How — PowerShell template

Drop this into the deploy script in three sections AFTER the canonical
zone is resolved and BEFORE `az deployment group create`. Assumes
`Invoke-Native`, `Write-Step/Success/Warn/Info/Fail` from
`talent_infra_modules/shared/common.ps1` are dot-sourced.

### 1. Parameter (gate the destructive action)

```powershell
[CmdletBinding()]
param(
    # ... existing params ...
    [switch]$FixStaleDnsZoneGroup,
    [switch]$Force   # Force MUST imply FixStaleDnsZoneGroup
)
```

### 2. Detection (read-only) — between zone-resolve and Confirm-Action

```powershell
$StaleZoneGroup = $null
$StaleZoneGroupOldZoneId = $null
$peName = "${ServerName}-pe"   # or however the script derives the PE name

if ($EnablePrivateEndpoint -and -not [string]::IsNullOrEmpty($ExistingDnsZoneId)) {
    Write-Step "Checking for stale Private DNS zone group on PE '$peName'"

    $peJson = Invoke-Native {
        az network private-endpoint show -g $ResourceGroup -n $peName -o json 2>$null
    }
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($peJson)) {
        $zgJson = Invoke-Native {
            az network private-endpoint dns-zone-group list `
                -g $ResourceGroup --endpoint-name $peName -o json 2>$null
        }
        $zgList = @()
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($zgJson)) {
            try { $zgList = @($zgJson | ConvertFrom-Json) } catch { $zgList = @() }
        }
        foreach ($zg in $zgList) {
            foreach ($cfg in @($zg.privateDnsZoneConfigs)) {
                $currentZoneId = [string]$cfg.privateDnsZoneId
                if (-not ($currentZoneId -ieq $ExistingDnsZoneId)) {
                    $StaleZoneGroup = [string]$zg.name
                    $StaleZoneGroupOldZoneId = $currentZoneId
                    Write-Warn "Stale zone group '$($zg.name)' points at: $currentZoneId"
                    Write-Warn "Resolved canonical zone is        : $ExistingDnsZoneId"
                    Write-Warn "Azure forbids in-place repointing — zone group must be deleted and recreated."
                    break
                }
            }
            if ($null -ne $StaleZoneGroup) { break }
        }
        if ($null -eq $StaleZoneGroup) {
            Write-Success "No stale zone group detected on PE '$peName'."
        }
    } else {
        Write-Info "PE '$peName' not present yet (first run) — nothing to repair."
    }
}
```

**First-run safe**: `az network private-endpoint show ... 2>$null` returns
non-zero / empty when the PE doesn't exist; the outer `if` skips. Run
this section unconditionally — it's read-only.

### 3. Surface in the plan summary

Inside the existing "Deployment plan" block, after the existing zone
status line:

```powershell
if ($null -ne $StaleZoneGroup) {
    $gate = if ($FixStaleDnsZoneGroup -or $Force) {
        'auto-approved (-FixStaleDnsZoneGroup or -Force)'
    } else {
        'BLOCKED — rerun with -FixStaleDnsZoneGroup'
    }
    Write-Host ("    Stale PE zone group   : '{0}' WILL BE DELETED [{1}]" -f $StaleZoneGroup, $gate) -ForegroundColor Yellow
    Write-Host ("      currently points at : {0}" -f $StaleZoneGroupOldZoneId) -ForegroundColor DarkYellow
}
```

### 4. Repair (gated) — after Confirm-Action, before `az deployment group create`

```powershell
if ($null -ne $StaleZoneGroup) {
    if (-not ($FixStaleDnsZoneGroup -or $Force)) {
        Write-Fail "Stale Private DNS zone group '$StaleZoneGroup' on PE '$peName' would block this deploy."
        Write-Info  "Azure forbids in-place mutation of privateDnsZoneConfigs[*].privateDnsZoneId."
        Write-Info  "Rerun with -FixStaleDnsZoneGroup (or -Force) to delete and recreate it."
        exit 1
    }

    Write-Step "Deleting stale Private DNS zone group '$StaleZoneGroup' on PE '$peName'"
    $delOut = Invoke-Native {
        az network private-endpoint dns-zone-group delete `
            -g $ResourceGroup `
            --endpoint-name $peName `
            -n $StaleZoneGroup `
            --output none 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Could not delete stale zone group (exit $LASTEXITCODE):"
        $delOut | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkRed }
        exit 1
    }
    Write-Success "Stale zone group deleted. Bicep will recreate it pointing at the canonical zone."
}
```

> ⚠️ **Do NOT pass `--yes`** to `az network private-endpoint dns-zone-group
> delete` — that subcommand does not accept it and will reject the call.
> The `--yes` flag is only valid on `az network private-dns zone delete`
> (see section 5 below).

### 5. (Optional) Best-effort orphan-zone cleanup

Only when section 4 actually deleted a stale group AND the gate was on
AND the old zone ID resolves to a zone in the SAME `$ResourceGroup` as
the deploy target. Empty + unlinked guard prevents accidental data loss.

```powershell
if ($null -ne $StaleZoneGroup -and ($FixStaleDnsZoneGroup -or $Force) -and -not [string]::IsNullOrEmpty($StaleZoneGroupOldZoneId)) {
    $segments = $StaleZoneGroupOldZoneId.Split('/')
    if ($segments.Length -ge 9) {
        $orphanRg   = $segments[4]
        $orphanName = $segments[8]
        if ($orphanRg -ieq $ResourceGroup) {
            Write-Step "Checking orphan Private DNS zone '$orphanName' in '$orphanRg'"
            $zoneJson = Invoke-Native {
                az network private-dns zone show -g $orphanRg -n $orphanName -o json 2>$null
            }
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($zoneJson)) {
                try {
                    $zone      = $zoneJson | ConvertFrom-Json
                    $rsCount   = [int]$zone.numberOfRecordSets
                    $linkCount = [int]$zone.numberOfVirtualNetworkLinks
                    Write-Info "Orphan zone: $rsCount record set(s), $linkCount VNet link(s)."
                    if ($rsCount -le 1 -and $linkCount -eq 0) {
                        Write-Step "Orphan zone is empty + unlinked — deleting"
                        $delZoneOut = Invoke-Native {
                            az network private-dns zone delete `
                                -g $orphanRg -n $orphanName `
                                --yes --output none 2>&1
                        }
                        if ($LASTEXITCODE -eq 0) {
                            Write-Success "Orphan zone '$orphanName' deleted from '$orphanRg'."
                        } else {
                            Write-Warn "Orphan zone delete failed (exit $LASTEXITCODE). Non-fatal — Bicep will still succeed."
                            $delZoneOut | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkYellow }
                        }
                    } else {
                        Write-Warn "Orphan zone has $rsCount record set(s) and $linkCount VNet link(s) — leaving in place to avoid accidental data loss."
                        Write-Info  "Delete manually with: az network private-dns zone delete -g $orphanRg -n $orphanName --yes"
                    }
                } catch {
                    Write-Warn "Could not parse orphan zone show output — skipping cleanup."
                }
            } else {
                Write-Info "Orphan zone not found (already deleted?) — nothing to clean up."
            }
        }
    }
}
```

`rsCount -le 1` is correct because Azure Private DNS zones always
retain their SOA record set even after every A/CNAME is removed. A
record count of 1 with zero VNet links is the "drained orphan" state.

## Idempotence checklist

- Re-run on clean state → detection finds no mismatches → repair sections
  are no-ops → `Write-Success "No stale zone group detected"`.
- First run (no PE yet) → `az network private-endpoint show` exits non-
  zero → detection logs "PE not present yet" → repair sections skip.
- Stale state detected but operator didn't pass the gate → fail loud with
  rerun instructions → operator decides → no destructive action.
- Stale state detected + gate on → delete zone group → Bicep recreates →
  optional orphan cleanup → next run is clean.

## Generalises to

Every PE in this stack:
- Cosmos: `privatelink.documents.azure.com`
- Foundry / CogServices: `privatelink.cognitiveservices.azure.com` +
  `privatelink.openai.azure.com`
- Key Vault: `privatelink.vaultcore.azure.net`
- ACR: `privatelink.azurecr.io`
- Storage: `privatelink.{blob,file,queue,table}.core.windows.net`

Copy the same 5-section pattern into each new PE-bearing deploy script.
Pair it with `azure-private-dns-discover-reuse` — that skill resolves
the canonical zone, this skill ensures the existing PE can actually be
repointed at it.

## Anti-patterns

- ❌ Trying to fix this in Bicep. The error is at the Network RP, not
  the template. Bicep CAN tell you which zone it wants to bind, but
  it CANNOT mutate an existing config's `privateDnsZoneId`.
- ❌ Auto-repairing without an opt-in switch. Deleting a zone group is
  a name-resolution-breaking operation; operators must consciously
  accept the window.
- ❌ Passing `--yes` to `az network private-endpoint dns-zone-group
  delete`. That subcommand does not accept it; the call will reject.
- ❌ Touching zones in resource groups OTHER than the deploy target's
  RG. Those are someone else's infrastructure. The orphan cleanup
  section guards against this with `orphanRg -ieq $ResourceGroup`.
- ❌ Deleting an orphan zone that still has VNet links or more than
  one record set. Could break name resolution for unrelated services.

## Live verification recipe

When diagnosing this failure mode in a real environment, the reliable
shell capture pattern in this repo is:

```powershell
az network private-endpoint dns-zone-group list `
    -g <rg> --endpoint-name <pe> -o json *> $env:TEMP\zg.json
Get-Content $env:TEMP\zg.json -Raw
```

Multi-line `pwsh + az` calls intermittently return stale/empty stdout
when read directly; routing through `$env:TEMP` flushes the buffer
reliably. Same trick works for `az network private-dns zone show`
when comparing record / link counts.
