---
name: "powershell-parameter-shadowing"
description: "PowerShell variable identifiers are case-insensitive. Local variables that match a parameter name in any casing silently shadow and overwrite the parameter, corrupting its type and value. Always pick local names that differ from parameters by more than case."
domain: "powershell, infrastructure-scripting"
confidence: "low"
source: "earned"
---

## Context

Applies to any PowerShell function (in `.ps1`, `.psm1`, or inline `function` blocks) that declares a typed parameter — especially `[switch]`, `[SecureString]`, `[bool]`, or any other strongly-typed parameter where a type-coercion failure at assignment time produces a confusing, non-local runtime error.

Especially dangerous in **shared helpers** (e.g., `talent_infra_modules/shared/common.ps1`) where one variable-shadowing bug surfaces at every dot-sourcing caller, with the stack trace pointing to the caller (not the bug site).

## Patterns

**The trap:** PowerShell variable names are case-insensitive at the language level. `$Secure`, `$secure`, `$SECURE`, and `$Secure` all refer to **the same variable** within a scope. There is no warning when a local assignment overwrites a parameter — the assignment just happens and any type constraint on the parameter is silently dropped (for `[switch]` and `[SecureString]`) or triggers a confusing coercion error at the assignment site.

**Naming rule:** When a local variable would naturally share a name with a parameter, suffix the local to distinguish them:

| Parameter | Bad local | Good local |
|-----------|-----------|------------|
| `[switch]$Secure` | `$secure` | `$secureValue`, `$secureString`, `$enteredSecure` |
| `[string]$Name` | `$name` | `$nameStr`, `$resolvedName`, `$displayName` |
| `[string]$Prompt` | `$prompt` | `$promptText`, `$promptMsg` |
| `[bool]$Force` | `$force` | `$forced`, `$forceFlag` |

**Audit recipe** for any new PowerShell helper:

```powershell
# Inside a function with parameters P1, P2, ..., grep for
#   ^\s*\$(p1|p2|...) =
# (case-insensitive). Any hit that is NOT the parameter declaration itself
# is a shadow waiting to break the function.
```

## Examples

**Broken — single line, hours to diagnose:**

```powershell
function Get-ParameterValue {
    param([switch]$Secure)
    if ($Secure) {
        $secure = Read-Host -AsSecureString    # shadows [switch]$Secure
        return $secure                          # returns a SwitchParameter, not a SecureString
    }
}
# Caller:
[SecureString]$p = Get-ParameterValue -Secure
# → MetadataError: Cannot convert "SwitchParameter" to "SecureString"
```

**Fixed:**

```powershell
function Get-ParameterValue {
    param([switch]$Secure)
    if ($Secure) {
        $secureValue = Read-Host -AsSecureString   # distinct name
        return $secureValue
    }
}
```

**Real-world incident:** See `.squad/agents/bishop/history.md` (2026-05-21 entry). One-line bug in `talent_infra_modules/shared/common.ps1::Get-ParameterValue` broke the secure-password prompt for all 5 component deployers. Fix: rename `$secure` → `$secureValue` (3 references) in the `if ($Secure) {...}` branch.

## Anti-Patterns

- **Trusting parameter typing alone.** `[switch]$Secure` does NOT protect the slot from being overwritten by a same-name local of a different type.
- **Using single-word locals matching common parameter names** (`$name`, `$value`, `$path`, `$force`, `$secure`) inside any function that already takes a parameter by the same name. Even if no parameter exists today, future signature changes will silently break behavior.
- **Relying on PSScriptAnalyzer to catch this.** PSScriptAnalyzer has rules for many things but does NOT flag parameter-shadowing-by-case-mismatch as of the version pinned in this repo's toolkit.
- **Diagnosing the error at the call site.** The cascade error appears at the caller's typed assignment. Always trace one frame deeper into the helper.
