# shared/ — common helpers for `talent_infra_modules` deploy scripts

This folder contains **PowerShell helpers** that every per-component
deployment script (`01-postgresql/`, `02-backend/`, `03-frontend/`,
`04-data-loading/`) is expected to dot-source. There is no separate
package — everything lives in [common.ps1](common.ps1) so a script only
ever needs one `Join-Path` to wire it up.

## Usage

At the top of any per-component `deploy.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot "..\shared\common.ps1")

Test-AzLoggedIn | Out-Null
Test-AzSubscription -SubscriptionId (Get-ParameterValue `
    -Name "Azure subscription ID" `
    -EnvVar "AZURE_SUBSCRIPTION_ID")
```

## What's in `common.ps1`

### Output helpers

| Function          | Purpose                                  |
|-------------------|------------------------------------------|
| `Write-Step`      | Cyan `==> heading` — start of a phase    |
| `Write-Success`   | Green `OK ...` — phase OK                |
| `Write-Warn`      | Yellow `!! ...` — non-fatal warning      |
| `Write-Fail`      | Red `XX ...` — phase failed              |
| `Write-Info`      | Gray indented info text                  |

### Native command wrapper

`Invoke-Native { az ... }` runs a native command with
`$ErrorActionPreference = 'Continue'` so a non-zero exit doesn't unwind
the whole script. Callers MUST check `$LASTEXITCODE`.

### Azure CLI sign-in

| Function                | Purpose                                         |
|-------------------------|-------------------------------------------------|
| `Test-AzLoggedIn`       | Verifies `az account show`; exits if not logged in. Returns the account object. |
| `Test-AzSubscription`   | Switches to a target subscription when not active. |

### Parameter resolution

`Get-ParameterValue -Name <label> [-EnvVar <NAME>] [-Default <val>]
[-Value <override>] [-Prompt <text>] [-Secure]`

Layered resolution:

1. **`-Value`** — explicit script-arg pass-through.
2. **`-EnvVar`** — environment variable.
3. **Interactive prompt** with `-Default`.
4. **`-Default`** if not running interactively.

Use `-Secure` for passwords; the returned `SecureString` can be unwrapped
with `ConvertFrom-SecureStringPlain` immediately before passing to `az`.

### Resource existence

| Function                       | Purpose                                                       |
|--------------------------------|---------------------------------------------------------------|
| `Test-ResourceGroup`           | True if the RG exists.                                        |
| `Test-ResourceExists`          | Generic `az resource show` wrapper with short-name aliases (`vnet`, `containerappenv`, `containerapp`, `acr`, `postgres`, `foundry`, `cosmos`, `keyvault`, `uami`). |
| `Test-VnetSubnetExists`        | True if a subnet exists inside a vnet.                        |
| `Test-FoundryProject`          | Verifies Foundry account + project + at least one deployment exists. Returns endpoint and deployment names. |
| `Get-AcrLoginServer`           | Returns `<name>.azurecr.io` for an existing ACR.              |

### Bulk precondition check

`Assert-PrerequisitesExist` takes a hashtable list and verifies every
expected pre-existing resource exists; aborts the script with a clear
list of what's missing. This is the **first thing** every per-component
script should call after `Test-AzLoggedIn`.

### Confirmation

`Confirm-Action -Message "..." [-Force]` prompts `y/N`. Auto-confirms
when `-Force` is supplied or when `$env:CI` is set. Auto-denies in
non-interactive sessions without those signals.

## What's NOT here

These scripts are **standalone**. There is intentionally no:

- `azd env get-value` helper. We do not use azd in this folder.
- Bicep parameter file generator. Bicep modules consumed by the
  per-component scripts are kept thin enough to be invoked with `az
  deployment group create --parameters Name=Value` directly.
- Docker hash-cache helper. The per-component scripts always rebuild
  (caller may opt into `--cache-from` themselves).

If you reach for one of those, you are probably re-implementing
`talent_infra_v2/` — use that folder instead.
