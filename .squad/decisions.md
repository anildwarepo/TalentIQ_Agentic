# Decisions

> Shared decision log. All agents read this before starting work.
> Only the Coordinator (via Scribe merge) writes here.

<!-- Decisions appear below, newest first. -->

### 2026-05-22T23:59:30Z: PowerShell deployment scripts — no literal passwords in `.EXAMPLE` blocks; prefer `Read-Host -AsSecureString`, fall back to `<angle-bracket-placeholder>` only

**By:** Bishop (Deployment Engineer) — requested by Anil
**Status:** Implemented (single-file edit) — awaiting Anil git commit + decision on history scrub

**Trigger:** GitGuardian flagged `ConvertTo-SecureString Password` literal in `talent_infra_modules/01-postgresql/deploy.ps1` line 43, pushed 2026-05-22T22:58:37Z. The literal `P@ssw0rd!Strong!` was example documentation inside the script-header `.EXAMPLE` block — never an active credential, never present in any `.env` or `.outputs.json` — but it is a real GitGuardian hit, indexed in two commits (`69af3ac` "add moduler deployment", `cbb8b23` "add modular deployment" — still HEAD on `origin/master`), and looks like a real password to any automated scanner.

**Why a doc-comment example is still a leak:** `.EXAMPLE` blocks in PowerShell are surfaced verbatim by `Get-Help`, ship with the script forever, and get copy-pasted by operators into shell history. A plausible-looking literal there is functionally identical to a hardcoded credential — scanners treat it as one, and humans assume it works. The fix is not "make it a less-real-looking literal" — the fix is "remove the literal entirely."

**Decision (normative for every `*.ps1` script under `talent_infra_modules/`, `talent_infra/`, `talent_infra_v2/`, and any future `talent_infra_*` toolkit):**

1. **`.EXAMPLE` blocks for secret-bearing parameters MUST NOT contain any string that could be interpreted as a real password.** No `'P@...'`, no `'Test@1234'`, no `'changeMe123!'`. Scanners do not read intent — they regex on shape.
2. **Preferred pattern** — `Read-Host -AsSecureString`:
   ```powershell
   -AdminPassword (Read-Host -AsSecureString -Prompt 'Postgres admin password')
   ```
   This is both safer (nothing in shell history, nothing in scripts, nothing in CI logs) AND better documentation: it teaches operators the right interactive flow. `shared/common.ps1::Get-ParameterValue` already falls back to `Read-Host` when `-AdminPassword` is omitted, so the parameter can be dropped entirely.
3. **CI / automated runs** — source from Key Vault / GitHub Actions secret / AZ DevOps variable group, convert to SecureString **at the call site**, never check the literal into a script. When a placeholder is genuinely necessary (e.g., a comment showing the `ConvertTo-SecureString` form), use an obvious `<angle-bracket>` token (`'<your-strong-password>'`) so both humans and scanners can see it's a template:
   ```powershell
   #   -AdminPassword (ConvertTo-SecureString '<your-strong-password>' -AsPlainText -Force)
   ```
4. **Legitimate `ConvertTo-SecureString` call sites** — `shared/common.ps1` lines 195, 206, 225 convert variable / env-var / prompt input to SecureString. Those are correct. The rule targets **literal strings inside `ConvertTo-SecureString '...'`**, not the function itself.

**Pre-commit guardrail:** Recommend adopting `gitleaks` (or equivalent) as a pre-commit hook on this repo before the next `talent_infra_*` PR lands. Gitleaks' default rule `generic-api-key` matches the exact `ConvertTo-SecureString 'literal'` pattern and would have caught this. See remediation runbook (delivered inline to Anil 2026-05-22) for the exact `.pre-commit-config.yaml` snippet.

**Files changed (Bishop, awaiting Anil commit):**
- `talent_infra_modules/01-postgresql/deploy.ps1` — `.EXAMPLE` block (lines 40–55) rewritten:
  - Removed: `(ConvertTo-SecureString 'P@ssw0rd!Strong!' -AsPlainText -Force)`
  - Added: `(Read-Host -AsSecureString -Prompt 'Postgres admin password')` as the primary example
  - Added: explanatory comment noting `Get-ParameterValue` auto-prompts when `-AdminPassword` is omitted, plus a CI guidance block with the `<your-strong-password>` placeholder pattern for documentation use
  - PowerShell parse: 0 errors. Workspace-wide grep for `P@ssw0rd!Strong!`: 0 matches in working tree.

**Scope of remaining exposure (NOT fixed by this edit):**
- Git history commits `69af3ac` and `cbb8b23` still contain the literal. Scrubbing requires `git filter-repo` + force-push, which is Anil's call (see runbook option b). Recommended: **accept the exposure** (option a) — the literal was never active credential and no rotation is required, GitGuardian alert can be resolved as "doc example, no real impact."

**Cross-agent impact:**
- **Lambert (Reviewer):** Pattern is normative for all future `talent_infra_*` PowerShell deploy scripts. Next sweep should grep all `.ps1` `.EXAMPLE` blocks for `ConvertTo-SecureString '<not-angle-bracketed>'` and flag any survivors. Suggested regex: `ConvertTo-SecureString\s+['"][^<].*['"].*-AsPlainText`.
- **Brett (Data Generator & Loader):** Pipeline scripts under `talent_data_pipeline/` are already password-free (Entra-token only via `pg_entra`). No change required.
- **Kane (Backend), Dallas (Frontend):** App code never had hardcoded passwords. No change required.
- **Coordinator / Squad:** Recommend adding a session-init step that runs `gitleaks detect --no-banner` (when available) before any agent spawns that touch `talent_infra_*`. Earned-knowledge candidate for `.squad/skills/` — likely name `azure-ps1-no-literal-secrets-in-example` or fold into existing `azure-postgres` skill.

**Validation (Bishop):**
- Working-tree grep `P@ssw0rd!Strong!` → 0 matches.
- PowerShell parse `[System.Management.Automation.Language.Parser]::ParseFile(...)` on `01-postgresql/deploy.ps1` → 0 errors.
- Sweep across `talent_infra_modules/`, `talent_infra/`, `talent_infra_v2/` for `ConvertTo-SecureString 'literal'` → only the 3 legitimate variable-conversion uses in `shared/common.ps1` remain (lines 195, 206, 225). No other `.ps1` literal-password sites.
- Sweep for `AccountKey=|SharedAccessSignature=|client_secret=|api[_-]?key=|Bearer [A-Za-z0-9]` literals in committed infra files → 0 matches (all 8 hits are doc references to "bearer token", not literals).
- `.env` files containing `POSTGRESQL_ADMIN_PASSWORD="Treetop@1234"` under `talent_infra_v2/.azure/talent-devtest-v{2,8}/` are gitignored by `talent_infra_v2/.azure/.gitignore` line 2 and never committed (`git log --all -S "Treetop@1234"` returns zero commits). Local-dev only — flagged to Anil but not a leak.

### 2026-05-22T23:59:00Z: Phase 1 connectivity test — `PGUSER` must be the full Entra principal; `pg_entra` now emits an actionable hint on libpq `password authentication failed`

**By:** Brett (Data Generator & Loader) — requested by Anil
**Status:** Implemented — awaiting Anil review

**Symptom (Anil's box, 2026-05-22):** `uv run --package talent_data_pipeline python -m talent_data_pipeline.main --mode manual` against `tiqpg9a6d3.postgres.database.azure.com` failed at Phase 1 with libpq `FATAL: password authentication failed for user "anildwa"`. Bewildering because the codebase has been Entra-token-only since 2026-05-12 (no `PGPASSWORD`) and Anil's `talent_infra_v2/scripts/test_pg_entra_connection.py --user anildwa@MngEnvMCAP347541.onmicrosoft.com` proved Entra auth works.

**H1 (Phase 1 bypasses Entra) — FALSIFIED.** `talent_data_pipeline/talent_data_pipeline/main.py:14` imports the inner-package `connectivity_test`; its `_connect()` returns `pg_entra.pg_connect()`. Repo-wide grep of the inner package found exactly one `psycopg2.connect()` call (inside `pg_entra.pg_connect`) and zero `PGPASSWORD` references.

**H2 (PGUSER misconfigured) — CONFIRMED, more pernicious than "short name":**
- `app_config/.env` line 55 is literally `PGUSER=` (empty value).
- `config.DatabaseConfig.user` defaults to `os.getenv("PGUSER", "")`.
- `db_config.connection_dict` passes `user=""` to `psycopg2.connect(...)`.
- libpq treats empty `user` as "use the OS account" → on Anil's Windows box that is `anildwa`.
- The Entra bearer token was issued correctly for `anildwa@MngEnvMCAP347541.onmicrosoft.com`, but PG looked up the role bound to libpq's `user="anildwa"` (not the principal name in the token) and rejected → `password authentication failed for user "anildwa"`.

**Decision:**
1. **Phase 1's connectivity test MUST route through `pg_entra.pg_connect()`** (already true — reaffirmed).
2. **`PGUSER` MUST be the full Entra principal name** that owns the PG role — **UPN** for a human, **UAMI name** for app-hosted compute. Empty / short usernames are operator errors. **NEVER** the object ID or client GUID.
3. **`pg_entra` now wraps `psycopg2.OperationalError` with an actionable hint** when libpq says `password authentication failed` (case-insensitive). Original exception is chained via `raise ... from exc`. Hint surfaces three cases: empty PGUSER (OS-fallback), PGUSER without `@` (short name), PGUSER with `@` (re-raise with host/user context). All other operational errors propagate untouched.
4. **No password fallback introduced. No auto-mutation of PGUSER.** Pipeline still requires the operator to set `PGUSER` correctly in `.env`; we just stop pretending the failure is about a missing password.

**Code changes (Brett, awaiting Anil commit — owner of `talent_data_pipeline/*`):**
- `talent_data_pipeline/talent_data_pipeline/pg_entra.py` — new module-level `_build_pguser_hint(pg_user, host, libpq_message)`. Both `pg_connect()` and `EntraThreadedConnectionPool._connect()` wrap the `psycopg2.connect(**kwargs)` call in `try/except psycopg2.OperationalError`, re-raising with the hint when the message matches `password authentication failed`. No other files touched. No success-path behavior change.

**Operator action required (NOT done by Brett — Anil owns `.env`):** Edit `app_config/.env` line 55 from `PGUSER=` to the full Entra principal name. For Anil's local box: `PGUSER=anildwa@MngEnvMCAP347541.onmicrosoft.com`. For app-hosted compute (Container Apps / Functions), set PGUSER to the UAMI **name** — never the OID or client ID.

**Validation:** `py_compile` on `pg_entra.py` after edits: OK. Isolated Phase-1-only re-run after `.env` update:
```
c:\repos\TalentIQ_Agentic\.venv\Scripts\python.exe -c "from talent_data_pipeline.connectivity_test import run_connectivity_test; import sys; sys.exit(0 if run_connectivity_test() else 1)"
```
(Do NOT run the full pipeline — load takes 60-90 min.)

**Forward guardrail (cross-agent):** Any future module that opens a PG connection inside the pipeline MUST go through `pg_entra.pg_connect()` or `EntraThreadedConnectionPool`. Direct `psycopg2.connect()` calls bypass both the Entra token injection AND this hint — they will silently fall back to libpq password auth and break against the Entra-only server. Pre-commit grep:
```
grep -RInE "psycopg2\.connect\(|psycopg2\.pool" talent_data_pipeline/talent_data_pipeline/
```
should continue to return exactly one match (the call inside `pg_entra.pg_connect`).

**Cross-agent impact:**
- **Bishop (Deployment Engineer):** Every UAMI-bound role provisioned by `talent_infra_modules/01-postgresql/` and `talent_infra_modules/02-backend/` MUST set the consumer's `PGUSER` env var to the **UAMI resource name** (which equals the PG role name after `microsoft-entra-admin create --display-name <UAMI-name>`). Never leave `PGUSER` empty in any Container App env array, Functions app setting, or `.env` template. The decision 2026-05-21 (`talent_infra_modules/02-backend` — Container App + sidecar) already does this (`PGUSER=${backendAppName}-identity`); reaffirmed here for any new compute the toolkit adds.
- **Parker (Data Engineer):** Co-owns the pipeline. Aware of the new hint behavior. Any new connectivity helper or batch loader added to `talent_data_pipeline/talent_data_pipeline/` should route through `pg_entra.pg_connect()` to inherit the hint automatically.

### 2026-05-22T23:55:00Z: `talent_data_pipeline.main` gains `--mode {env,manual}` flag + `DATALOAD_MODE` env var

**By:** Brett (Data Generator & Loader) — requested by Anil
**Status:** Implemented — awaiting Anil review

**What:** New first-class dataload-mode selector on `python -m talent_data_pipeline.main`. Precedence is **CLI flag > env var > default**:

| Source | Value | Wins over |
|---|---|---|
| `--mode env\|manual` CLI flag | explicit | env var, default |
| `DATALOAD_MODE=env\|manual` env var | explicit | default |
| (unset) | `env` | — |

Invalid `DATALOAD_MODE` → fatal exit **2** (typos in automation must never silently re-route the control path).

**Modes**
- **`env`** (default) — identical to today's behavior. Reads `PGHOST` and every other connection field from `.env`. No prompts.
- **`manual`** — prompts interactively at startup: `PG host [<current PGHOST>]: ` (default in brackets when `PGHOST` set). Enter accepts default; whitespace-only = empty; up to **3 attempts** then exit **2**. Only the **host** is prompted — port, user, database, sslmode stay from `.env`.

**Non-interactive guard:** `--mode manual` + `sys.stdin.isatty() == False` → exits **2** immediately with a redirect message to `--mode env` / `DATALOAD_MODE=env`. CI can never hang on `input()`.

**Banner** (printed once before any DB connection opens):
```
[pipeline] mode=env     host=<host>  (from .env)
[pipeline] mode=manual  host=<host>  (overridden via prompt)
```

**Key plumbing decision — `config.apply_host_override(host)`:** mutates the existing `db_config` singleton **in place** via `object.__setattr__` (bypassing `@dataclass(frozen=True)`) and writes `os.environ["PGHOST"]`. Rationale: `base_loader._get_pool()` and several other modules hold `db_config` by reference from import time; rebinding `config.db_config = NewInstance()` would leave those references stale. In-place mutation gives every lazy reader the correct host at next read. **Only the host changes** — Entra `DefaultAzureCredential` path in `pg_entra.pg_connect()` is fully preserved (same user, port, database, sslmode, same bearer-token password injection, no password fallback).

**Files touched (inner package only, per 2026-05-22 outer-folders cleanup):**
- `talent_data_pipeline/talent_data_pipeline/config.py` — added `apply_host_override(host: str) -> None`.
- `talent_data_pipeline/talent_data_pipeline/main.py` — added `_resolve_mode`, `_resolve_manual_host`, `_VALID_MODES`, `_MAX_HOST_PROMPT_ATTEMPTS`; extended `__main__` with `--mode` argparse, no-TTY guard, manual-mode prompt, `apply_host_override()` call, and banner. `--force` flag and downstream `main(force=...)` call unchanged.

Outer stubs at `talent_data_pipeline/{main,config,validate,connectivity_test}.py` **deliberately left alone**.

**Verification:** `py_compile` clean; `--help` shows the new flag; 14/14 isolated unit checks (no DB) covering precedence, override mutation, prompt retry, whitespace handling; live `'' | python -m talent_data_pipeline.main --mode manual` exits 2 with redirect message and never contacts DB.

**Open follow-ups for Anil (3):**
1. Should `manual` also prompt for `PGDATABASE` / `PGUSER`? (Current scope: host only.)
2. Should an audit-log line be written when an override is applied (in addition to the banner)?
3. Should `--mode manual` be allowed inside `python -m talent_data_pipeline.run_all` (the multi-step wrapper)? Currently the new flag only lives on `python -m talent_data_pipeline.main`; the wrapper would need its own flag pass-through.

**Owner of pipeline-code commit:** Anil (Brett's ownership boundary excludes `talent_data_pipeline/*` git stage/commit).

### 2026-05-22T22:20:00Z: Two reusable deploy.ps1 patterns shipped (PG bug fixes 1 + 2)

**By:** Bishop (Deployment Engineer) — requested by Anil
**What:** Patched `talent_infra_modules/01-postgresql/deploy.ps1` for two latent bugs surfaced during yesterday's `-FixStaleDnsZoneGroup` ship. Both fixes are reusable patterns that should be swept across the other four module folders.

**Bug 1 — Section 7c orphan-zone cleanup (Azure Private DNS stale-list trap):**
- `numberOfVirtualNetworkLinks` on `zone show` AND `link vnet list` both reported `0`/`[]` while Azure RP rejected zone delete with `CannotDeleteResource` citing `vnet-westus-link`. Listing endpoints can lag the RP truth by several minutes after a link delete.
- **New pattern:** Guard on `record-set list --query "[?type!='...SOA']"` (record-set listing IS reliable); idempotently delete any visible links via named delete; attempt zone delete; on failure log manual-hint and continue (non-fatal — Bicep does not depend on orphan removal).
- **Applies to:** every Private DNS zone in the stack — cosmos, postgres, cognitive, openai, keyvault, ACR — wherever the 2026-05-22T12:15:00Z discover-and-reuse pattern gets rolled out to other modules.

**Bug 2 — Section 8 Bicep deploy JSON capture (`2>&1` stream pollution):**
- `Invoke-Native { az deployment group create ... --output json 2>&1 }` interleaves stderr (Bicep "new release available" notice and ARM warnings) into stdout, breaking `ConvertFrom-Json` on a successful deploy. Downstream steps (Section 9 PG restart) silently skipped because the script exited 1 right after `Write-Success "Bicep deployment succeeded"`.
- **New pattern:** Redirect stderr to per-run file under `$scriptDir/.deploy-logs/{stamp}-bicep-stderr.txt` (`2>$stderrLog`); capture stdout-only; force `-o json`; validate non-empty before parsing; on parse failure dump raw stdout to disk (never echo inline — may contain secrets/IDs), log both file paths, exit 1; on non-zero exit surface stderr inline (small) + dump stdout to disk; on success delete the stderr file.
- **Applies to:** every `az deployment group create` capture in `talent_infra_modules/*/deploy.ps1` (00, 01, 02, 03, 04). The `2>&1` idiom for JSON capture is unsound across the board — Section-8 shape in `01-postgresql/deploy.ps1` is now the canonical replacement.

**Why:** Both bugs were latent before the discover-and-reuse + self-heal work because the unhappy paths never ran. Bug 2 in particular silently skipped Section 9 (PG flexible server restart for the auth/extensions remount) on every successful deploy — masked because operators were re-running manually. Sweeping the pattern across the other four folders prevents the same blind spot from recurring there.

**Verification:** deploy.ps1 parses clean (`[System.Management.Automation.Language.Parser]::ParseFile` → 0 errors). Live cleanup of `vnet-westus-link` + orphan zone in `rg-talent-devtest-11` completed (exit 0 on each step; `zone show 2>$null` returns empty). Anil can verify with `az network private-dns zone show -g rg-talent-devtest-11 -n privatelink.postgres.database.azure.com 2>$null` (should return empty).

**Follow-up suggested:** Lambert sweep of the four sibling `talent_infra_modules/{00,02,03,04}/deploy.ps1` files for the same `2>&1` JSON-capture idiom, replacing with the Section-8 canonical shape.

### 2026-05-22T18:30:00Z: All squad members MUST use claude-opus-4.6-1m (Opus 4.7 Extra-high reasoning)

**By:** Anil (via Copilot)
**What:** Every agent spawn — including Scribe and any other role normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (displayed as "Claude Opus 4.7 (Extra high reasoning)(Internal only)"). The "never bump Scribe" rule and all per-role fast-tier defaults in the coordinator's task-aware auto-selection table are overridden. `.squad/config.json` `defaultModel` is the source of truth and must be honored on every spawn — coordinator must not hardcode a different model on any agent.
**Why:** User directive — captured for team memory. Anil prefers consistent premium reasoning across the entire team, even for mechanical/logging tasks, over per-task cost optimization.
**Scope:** Applies to all current and future squad members. Applies to Scribe (logging, decisions merge, git commits), Ralph (work-monitor), and any agent added later. Overrides Layer 3 (task-aware auto-selection) and Layer 4 (default) of the coordinator's model-selection hierarchy.
**Honoring:** Coordinator MUST pass `model: "claude-opus-4.6-1m"` on every `runSubagent` / `task` call until the user explicitly changes `defaultModel` in `.squad/config.json` or issues a new directive.

### 2026-05-22T18:00:00Z: PE-bearing deploy scripts MUST pre-flight stale `privateDnsZoneGroup` resources before Bicep, gated by `-FixStaleDnsZoneGroup`

**By:** Bishop (Deployment Engineer) — requested by Anil after `01-postgresql` re-deploy failed with `UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed` on PE `tiqpg9a6d3-pe` (existing `default` zone group pointed at a stale local zone in `rg-talent-devtest-11`; current run resolves the canonical zone in RG `vnet`).

**What:** Every `talent_infra_modules/*/deploy.ps1` script that provisions (or could rebuild) an Azure Private Endpoint MUST pre-flight check for stale `privateDnsZoneGroup` resources on the target PE BEFORE invoking `az deployment group create`, and MUST refuse the destructive cleanup unless the operator explicitly opts in via `-FixStaleDnsZoneGroup` (or the umbrella `-Force` switch). Captured today for `01-postgresql`; applies as future modules add PEs for Cosmos, Foundry/CogServices, Key Vault, ACR, etc.

**Why:** Azure rejects in-place mutation of `privateDnsZoneConfigs[*].properties.privateDnsZoneId` with `UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed`. This blocks re-deploys whenever the discover-and-reuse logic (decision 2026-05-22T12:30:00Z) resolves a different Private DNS zone than the one wired into the existing PE's zone group — typical when a pre-fix deploy created a duplicate zone in the local RG and a later run discovers the canonical zone in the shared network RG. Bicep cannot fix this because the constraint is enforced at the Network RP, not the template. The only remediation is to delete the offending `privateDnsZoneGroup` so Bicep recreates it pointing at the right zone.

**Pattern (normative — every PE-bearing deploy script SHALL implement):**

1. **Detection (read-only).** After canonical zone resolution, probe the PE with `az network private-endpoint show -g <rg> -n <pe> 2>$null`. First-run safe: exit≠0 or empty body → log "PE not present yet" and skip. Otherwise list zone groups via `az network private-endpoint dns-zone-group list` and case-insensitive compare each `privateDnsZoneConfigs[*].privateDnsZoneId` against the resolved canonical zone ID using `-ieq`. Stash the mismatch (zone group name + old zone ID) for later steps.
2. **Surface in plan summary.** Show the stale zone group name and the gate status (`auto-approved (-FixStaleDnsZoneGroup or -Force)` vs `BLOCKED — rerun with -FixStaleDnsZoneGroup`). Yellow / dark-yellow coloring.
3. **Act (gated).** AFTER `Confirm-Action` and BEFORE Bicep deploy:
   - If mismatch detected AND operator did NOT pass `-FixStaleDnsZoneGroup` or `-Force` → `Write-Fail` with rerun instructions and `exit 1`. Never silently let Bicep error half-way.
   - If gated, delete via `az network private-endpoint dns-zone-group delete -g <rg> --endpoint-name <pe> -n <name> --output none`. (That subcommand does NOT accept `--yes`.) Check `$LASTEXITCODE`; `exit 1` with captured stderr on failure.
4. **Optional orphan-zone cleanup (best-effort, narrow).** Only when step 3 deleted a zone group AND the gate was on AND the old zone ID resolves to a zone in the SAME `$ResourceGroup` as the deploy target. Read `numberOfRecordSets` + `numberOfVirtualNetworkLinks` via `az network private-dns zone show`. Delete only if `rsCount -le 1 -and linkCount -eq 0` (≤1 because the SOA always survives). Anything higher → log a manual cleanup command and move on. Non-fatal on failure.

**Switch naming (normative):**
- New per-script switch: `[switch]$FixStaleDnsZoneGroup`.
- Umbrella `[switch]$Force` MUST imply it (CI / unattended deploys already pass `-Force`).
- No env-var binding by default — operators must consciously opt in.
- README rows MUST appear in the Inputs (parameters) table when the switch is present.

**Why not auto-repair without a gate:** Deleting a `privateDnsZoneGroup` is a destructive, name-resolution-breaking operation on a shared piece of infrastructure. The seconds between delete + Bicep recreate are a window where any service depending on the PE's name resolution will fail. Operators MUST explicitly opt into that window. The fail-fast message gives them everything they need to make that call deliberately.

**Reference implementation (done):** `talent_infra_modules/01-postgresql/deploy.ps1` 2026-05-22 — new `-FixStaleDnsZoneGroup` switch in `param()`, Section 6c (detection), Section 7b (delete stale zone group), Section 7c (best-effort orphan zone cleanup guarded by same-RG + empty record/link checks). README updated with switch row + "Deployment lessons encoded" bullet on the immutability rule. PSParser clean on patched script.

**Applies to (future modules — apply when adding PE for the service):**
- Cosmos DB SQL API (`privatelink.documents.azure.com`)
- Azure AI Foundry / Cognitive Services (`privatelink.cognitiveservices.azure.com`, `privatelink.openai.azure.com`)
- Key Vault (`privatelink.vaultcore.azure.net`)
- ACR Premium (`privatelink.azurecr.io`)
- Container Apps Env on internal ingress (`privatelink.<region>.azurecontainerapps.io`)

**Re-run path:** `pwsh .\deploy.ps1 -ResourceGroup rg-talent-devtest-11 -Location westus -FixStaleDnsZoneGroup` (or `-Force` for unattended).

**Skill captured:** `.squad/skills/azure-pe-dns-zone-group-self-heal/SKILL.md` (reusable PowerShell template with anti-patterns).

### 2026-05-22T12:30:00Z: Every PaaS Private Endpoint module must discover-and-reuse its `privatelink.<service>.*` Private DNS zone before creating one

**By:** Bishop (Deployment Engineer) — captured at Anil's direction after the `01-postgresql` overlapping-namespaces failure.

**What:** When a per-component deploy module provisions a Private Endpoint for an Azure PaaS service, it MUST first discover whether a Private DNS zone of the canonical `privatelink.<service>.*` name (a) is already linked to the target VNet, or (b) exists unlinked anywhere in the subscription, and REUSE that zone instead of creating a duplicate. The component module only creates a fresh zone when neither check finds anything.

**Why:** Azure enforces *at most one Private DNS zone per namespace per VNet* via `Microsoft.Network/privateDnsZones/virtualNetworkLinks`. A second zone of the same name linked to the same VNet — even from a different RG, even with the original link untouched — is rejected at create time with `BadRequest — A virtual network cannot be linked to multiple zones with overlapping namespaces`. Shared-tenant subs (where a central network team owns the canonical zones in an RG like `vnet`) hit this every time a new per-component deploy lands. Discover-and-reuse is the only resilient fix; pre-conditioning operators on env-var overrides is brittle.

**Where:** Pattern lives in `talent_infra_modules/shared/common.ps1` as two helpers:
- `Get-LinkedPrivateDnsZoneId -SubscriptionId -ZoneName -VnetId` — returns zone ID when any zone of that name is already linked to the VNet, else `$null`.
- `Get-PrivateDnsZoneIdByName -SubscriptionId -ZoneName` — fallback returning the first zone of that name anywhere in the sub, else `$null`.

Bicep contract at every PE module:
- Param: `param existingPrivateDnsZoneId string = ''`
- Param: `param existingPrivateDnsZoneLinked bool = true` (true = skip link creation; false = create link in zone's RG via a nested module deployed with `scope: resourceGroup(split(existingPrivateDnsZoneId, '/')[4])`).
- Conditional creation: `resource privateDnsZone ... = if (empty(existingPrivateDnsZoneId)) { ... }` and matching `if` on the in-RG `virtualNetworkLinks`.

Deploy script contract: discover before confirm, pass both params via `--parameters` overrides, preserve any explicit env-var override (e.g. `POSTGRESQL_DNS_ZONE_ID`, `COSMOS_DNS_ZONE_ID`) as the highest-priority signal (skip discovery when set).

**Reference implementation (done):** `talent_infra_modules/01-postgresql/` — `deploy.ps1` Section 6b, `infra/main.bicep` + `infra/modules/private-endpoint.bicep` + new `infra/modules/private-dns-zone-vnet-link.bicep`. Validated by `mcp_bicep_build_bicep` with zero diagnostics and live-tested against Anil's subscription where the canonical zone in RG `vnet` was correctly discovered as already linked.

**Applies to (future modules — apply when adding PE for the service):**
| Service | Zone name |
|---------|-----------|
| Postgres Flex Server | `privatelink.postgres.database.azure.com` (DONE — 01-postgresql) |
| Cosmos DB SQL API | `privatelink.documents.azure.com` |
| Azure AI Foundry / Cognitive Services | `privatelink.cognitiveservices.azure.com` |
| Azure OpenAI sub-resource | `privatelink.openai.azure.com` |
| Key Vault | `privatelink.vaultcore.azure.net` |
| ACR Premium | `privatelink.azurecr.io` |
| Container Apps Env (when on internal ingress) | `privatelink.<region>.azurecontainerapps.io` |

**Does NOT apply to:** modules that do not create a PE (e.g., `00-container-apps-env` external-only path, anything using service endpoints or public endpoints). Does NOT apply to `talent_infra_v2/` — that lives untouched as the working reference; per-component re-implementations carry the pattern.

**Skill captured:** `.squad/skills/azure-private-dns-discover-reuse/SKILL.md`.

### 2026-05-22T00:30:00Z: ARM/Bicep parameter files — no comment keys allowed

**By:** Bishop (Deployment Engineer) — requested by Anil
**What:** Every top-level key inside the `parameters` block of an ARM/Bicep parameter file (`*.parameters*.json`) MUST be a `DeploymentParameter` object — i.e. `{"value": ...}`. JSON has no comment syntax, and ARM does **not** honor the `_comment_*` convention some tooling uses. Adding a bare-string key like `"_comment_sku": "..."` causes the entire file to fail deserialization with `az deployment ... validate` / `azd up`:

```
ERROR: Unable to build a model: Unable to deserialize response data.
Data: {..., '_comment_sku': '...', 'skuName': {'value': '...'}, ...}, {DeploymentParameter}
```

**Rule for all future modules** (`02-backend`, `03-frontend`, `04-data-loading`, and any new `talent_infra_modules/*/infra/*.parameters*.json`):
- Never add `_comment_*`, `//`-style, or any non-`DeploymentParameter` keys inside the `parameters` object.
- Put human-readable context on the corresponding `param` in the `.bicep` file using `@description('...')`. The description flows into Azure portal hints, `az deployment ... what-if` output, and IDE tooltips — strictly better than a JSON comment.
- If you need cross-file rationale that doesn't fit on a single `@description`, put it in a sibling `README.md` next to the `infra/` folder, not inside the parameter file.

**Why:** This came up because `01-postgresql/infra/main.parameters.json` had a `_comment_sku` explaining the SKU/tier parity with `talent_infra_v2/`. The Bicep already has `@description('PostgreSQL SKU name...')` on `param skuName`, so the comment was redundant **and** breaking the deploy. Removed.

**Scope check:** Swept `talent_infra_modules/**/*.parameters*.json` (all 4 files: `00-container-apps-env`, `01-postgresql`, `02-backend`, `03-frontend`); only `01-postgresql` had the issue. Fixed.

### 2026-05-22T00:00:00Z: Prereq existence checks must use RP-specific `az <rp> show`, not generic `az resource show`

**By:** Bishop (Deployment Engineer) — requested by Anil
**Scope:** `talent_infra_modules/shared/common.ps1` and all per-component `deploy.ps1` scripts that call `Assert-PrerequisitesExist`.
**What:** When a deployment script needs to verify that a piece of pre-existing Azure infrastructure exists, the check MUST call the resource-provider-specific CLI (e.g. `az network vnet show`, `az containerapp show`, `az acr show`, `az cognitiveservices account show`), wrapped in `Invoke-Native` with `$LASTEXITCODE -eq 0` as the truth test. The generic wrapper `Test-ResourceExists` (which goes through `az resource show` → ARM `Microsoft.Resources/resources` read) is ONLY safe when the operator is guaranteed to have `Microsoft.Resources/resources/read` on the target RG, which is NOT true for cross-team / cross-tenant network or shared-platform RGs.
**Why:** Observed on Anil's `01-postgresql` deploy against RG `vnet` containing `vnet-westus`: `Test-ResourceExists -ResourceType 'vnet'` reported "not found" while `Test-VnetSubnetExists` reported "found" on the same VNet's child subnet — same physical resource, same principal, contradictory result. The generic ARM endpoint silently 403'd (presents as 404 to the CLI) while the resource-provider-specific endpoint succeeded with only `Microsoft.Network/virtualNetworks/read`. The RP-specific call is the same RBAC the actual deploy needs, so passing the prereq check guarantees the deploy can also see the resource — no extra ARM-read requirement that's strictly bonus and frequently missing in real environments.
**Implementation already shipped (2026-05-22):**
- Added `Test-VnetExists` to `talent_infra_modules/shared/common.ps1` (sits directly above `Test-VnetSubnetExists` for symmetry).
- Switched the `'vnet'` branch in `Assert-PrerequisitesExist` to call `Test-VnetExists`.
- `Test-ResourceExists` and its `vnet → Microsoft.Network/virtualNetworks` alias are KEPT — they remain valid for any caller invoking the helper directly and for environments where the operator does hold generic ARM read.
- Success/failure log strings (`"VNet $name"` / `"VNet $name not found in RG $vnetRg"`) are unchanged so downstream log scrapers and `AUTH-DISABLED.md` / `DEPLOYMENT-ORDER.md` / `README.md` instructions remain accurate.
**Forward action:** When 02-backend / 03-frontend / 04-data-loading hit a similar RBAC-mismatch symptom for ACR, Container Apps Env, Foundry, Cosmos, Postgres, or Key Vault prereq checks, add the matching `Test-<Thing>Exists` helper (modeled on `Test-VnetExists`) and switch its branch in `Assert-PrerequisitesExist`. Do NOT refactor preemptively — `Test-ResourceExists` is fine for the default greenfield case where the operator has full RG read.
**Non-goals:** This decision does NOT change the public shape of `Assert-PrerequisitesExist`'s `-Checks` parameter or the `Type='vnet'` alias used by callers in `00-container-apps-env/deploy.ps1` (line 182) and `01-postgresql/deploy.ps1` (line 218). Both continue to work; only the internal implementation moved.

### 2026-05-21: Postgres SKU/tier defaults in `talent_infra_modules/01-postgresql/` MUST mirror `talent_infra_v2/`

**By:** Bishop (Deployment Engineer) — at Anil's directive
**What:** `talent_infra_modules/01-postgresql/` postgres SKU defaults must track `talent_infra_v2/` exactly. As of 2026-05-21 the canonical pair is `skuName=Standard_D4ds_v5`, `skuTier=GeneralPurpose` (storage `32 GiB`, version `16`), sourced from `talent_infra_v2/infra/main.parameters.json` lines 86–95.
**Why:** Deploy was failing with `ServerEditionIncompatibleWithSkuSize`. Root cause: the standalone module shipped with `skuName=Standard_B2s` + `skuTier=GeneralPurpose` — an invalid pairing (B-series is **Burstable only**; D-series is GeneralPurpose; E-series is MemoryOptimized). The v2 stack avoided the bug because its `main.parameters.json` overrides the (also-broken) Bicep default with `Standard_D4ds_v5`. The standalone module had no such override.
**Files changed (3):**
- `talent_infra_modules/01-postgresql/deploy.ps1` — param-block defaults (`$SkuName`, `$SkuTier`) and the two `Get-ParameterValue -Default ...` calls now resolve to `Standard_D4ds_v5` / `GeneralPurpose`. Env-var overrides `POSTGRESQL_SKU_NAME` / `POSTGRESQL_SKU_TIER` still win.
- `talent_infra_modules/01-postgresql/infra/main.bicep` — `param skuName` default `Standard_B2s` → `Standard_D4ds_v5`; expanded `@description` to spell out the valid `tier ↔ family` pairings (Burstable=B*, GeneralPurpose=D*ds_v4/v5, MemoryOptimized=E*ds_v4/v5) so the next operator doesn't repeat the mistake.
- `talent_infra_modules/01-postgresql/infra/main.parameters.json` — `skuName` value `Standard_B2s` → `Standard_D4ds_v5`. Added `_comment_sku` field citing the v2 source-of-truth file.

**Files INTENTIONALLY NOT changed:**
- `talent_infra_modules/01-postgresql/infra/modules/postgresql-flexible-server.bicep` (still defaults to `Standard_B2s` on its own param) — `main.bicep:112-113` always passes explicit `skuName`/`skuTier` values into the module, so the submodule default is unreachable. Keeping it untouched preserves verbatim parity with `talent_infra_v2/infra/modules/postgresql-flexible-server.bicep`.
- `talent_infra_v2/` (read-only canonical source; not in scope for this fix).

**Rule going forward:** Any change to the postgres SKU+tier+storage+version in `talent_infra_v2/infra/main.parameters.json` triggers a matching update in `talent_infra_modules/01-postgresql/{deploy.ps1, infra/main.bicep, infra/main.parameters.json}`. Reviewers should flag divergence between the two paths at PR time, not at `Deployment failed` time.

**Validation:**
- `bicep build` on `talent_infra_modules/01-postgresql/infra/main.bicep` → `success=true`, 0 errors, 0 warnings.
- `[System.Management.Automation.Language.Parser]::ParseFile` (pwsh 7) on `deploy.ps1` → zero parse errors, 2455 tokens.
- SKU/tier sanity: `Standard_D4ds_v5` is D-series → `GeneralPurpose` ✓ (valid Azure Database for PostgreSQL Flexible Server pairing).
- Deploy NOT re-run (per workflow: Anil owns deploys).

### 2026-05-21: PowerShell variable naming — no case-insensitive collisions with parameters
**By:** Bishop (Deployment Engineer)
**What:** In all PowerShell scripts under `talent_infra_modules/` (and any sibling toolkit added later), a local variable inside a function MUST NOT have a name that matches a parameter of the same function under case-insensitive comparison. PowerShell treats `$secure` and `$Secure` as the same variable, so the local overwrites the parameter — corrupting typed parameters (e.g., a `[switch]` being assigned a `[SecureString]`) and producing confusing cascade type-coercion errors at the call site. Prefer suffixed local names (`$secureValue`, `$nameStr`, `$promptText`) when the natural name would collide.
**Why:** Concrete regression in `shared/common.ps1::Get-ParameterValue` where `$secure = Read-Host -AsSecureString` shadowed `[switch]$Secure`, breaking the secure-prompt path that all 5 component `deploy.ps1` scripts depend on. One-line discipline prevents an entire class of hard-to-diagnose runtime errors in shared infra helpers.

### 2026-05-21: talent_infra_modules/00-container-apps-env — standalone ACA env deployer
**By:** Bishop (Deployment Engineer)
**Status:** Implemented (recovered by Squad coordinator — Bishop spawn returned silent success; all artifacts verified on filesystem and validated)
**What:** Added new `talent_infra_modules/00-container-apps-env/` component (optional standalone deployer for the Container Apps Environment when it does not already exist). Files: `README.md`, `deploy.ps1`, `infra/main.bicep`, `infra/main.parameters.json`, `infra/modules/container-apps-environment.bicep`, `infra/modules/aca-subnet.bicep`. Cross-cutting updates: `talent_infra_modules/README.md` (added 00 to component table + prerequisites), `talent_infra_modules/DEPLOYMENT-ORDER.md` (added Step 0 — foundational, parallel-with-01-postgresql, blocks 02 + 03), `talent_infra_modules/02-backend/deploy.ps1` and `talent_infra_modules/03-frontend/deploy.ps1` (soft-fallback: when `ContainerAppsEnvName` not provided, read `../00-container-apps-env/.outputs.json`).
**Why:** ACA env was originally listed as a pre-existing prerequisite in the toolkit. Anil needed the toolkit to also be capable of standing up the ACA env on greenfield environments where it does not yet exist — without forcing operators back to the full `talent_infra_v2/` greenfield path.
**Key choices:** (1) Numbered `00` to mark it foundational and parallel-deployable with `01-postgresql` (both must precede `02-backend` / `03-frontend`). (2) Subnet handling lives in `deploy.ps1` as a pre-existing-or-create branch: validates delegation to `Microsoft.App/environments`, soft-lock awareness, CIDR membership; Bicep only receives a resolved `subnetId` (single source of truth for subnet shape). (3) Downstream components (02, 03) gained soft-fallback to read `.outputs.json` from `../00-container-apps-env/` so operators do not have to copy `ContainerAppsEnvName` between commands. (4) No data-plane operations.
**Validation (coordinator-side):** `az bicep build` against `00-container-apps-env/infra/main.bicep` → BICEP OK. PowerShell AST parser against `deploy.ps1` → PS-PARSE OK (zero syntax errors).
**Impact:** Toolkit grew to 5 components (`00-container-apps-env`, `01-postgresql`, `02-backend`, `03-frontend`, `04-data-loading`). Operators with an existing ACA env keep skipping straight to `01`; greenfield-app-tier operators now have a self-contained path through the modules toolkit.

### 2026-05-21: talent_infra_modules toolkit — APPROVED (Lambert review verdict)
**By:** Lambert (Tester)
**Status:** Approved — ship as-is
**What:** Read-only validation of `talent_infra_modules/` (4 component folders + `shared/common.ps1`) and Dallas's `talent_ui/` MSAL-bypass changes. All 6 hazards from `/memories/repo/talentiq-azd-deploy.md` covered: AGE shared_preload_libraries restart, PG Entra-admin re-PUT race (bicep passes empty `entraAdminObjectId`, control-plane CLI registers post-deploy), MCP sidecar shared UAMI with `PGUSER=<backendAppName>-identity`, AcrPull RBAC race (`dependsOn: [acrPullRole]`), no Foundry account re-PUT (only role assignment), `psql` PATH check with install hints. All 3 `main.bicep` files compile; all 5 `.ps1` files parse zero errors; cross-folder `.outputs.json` schema consistent (keys match consumer reads).
**Findings (WARN — non-blocking):** (1) `02-backend/README.md` says `mcpImage` but `.outputs.json` writes `mcpServerImage`; (2) `02-backend/README.md` mentions Docker Desktop local-build option not wired in `deploy.ps1` (no `-UseAcrTasks` switch); (3) `talent_ui/src/App.jsx` uses `eslint-disable react-hooks/rules-of-hooks` for conditional `useMsal()`/`useIsAuthenticated()` — safe because `AUTH_DISABLED` is build-time constant, but a `<AuthShell>` wrapper would be cleaner. All three are doc/style nits; none block merge.
**Impact:** Toolkit is end-to-end coherent. 01 → 02 → 03 → 04 hand off correctly. Bishop and Dallas may address WARN items in a tidy-up commit.

### 2026-05-21: talent_infra_modules/04-data-loading — orchestrator implemented
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Authored `talent_infra_modules/04-data-loading/deploy.ps1` (~510 lines, no Bicep — pure local Python invocation). Flow: read `01-postgresql/.outputs.json` (required) + `02-backend/.outputs.json` (optional) → acquire OSSRDBMS Entra token (`az account get-access-token --resource-type oss-rdbms`) → optional psql `CREATE EXTENSION` for age/vector/pg_trgm/pg_diskann + `LOAD 'age'` + `create_graph()` (wrapped in `DO ... EXCEPTION` block for idempotency) → idempotency gate (Cypher `:Employee` count, prompt unless `-Force`) → `python -m talent_data_pipeline.main` from pipeline dir → opt-in `-NarrowBackendGrants` invokes `talent_infra_v2/scripts/provision_pg_entra_roles.py` with JSON `--principals` array → opt-in `-RestartBackend` discovers active revision via `az containerapp show --query properties.latestRevisionName` and restarts → 15-label vertex count summary.
**Key choices:** (1) `-NarrowBackendGrants` opt-in — broad PG admin grant is the deliberate fallback for networks blocking 5432 (Comcast DPI etc.); auto-narrow would break deployments on every network change. (2) `psql` is hard prerequisite — bootstrap chicken-and-egg: can't use pipeline's `pg_entra.pg_connect()` for extensions step because the package import runs connectivity test presupposing extensions exist. (3) Pipeline ignores `PGHOSTADDR` (`config.py` only reads `PGHOST`) — script warns when `-PgPrivateIp` set; operator must add hosts-file entry. (4) Env-var snapshot/restore in top-level try/finally so PGPASSWORD (real bearer token) never leaks. (5) No `.outputs.json` (terminal step in the chain).
**Impact:** Closes 01 → 02 → 03 → 04 chain. `talent_data_pipeline/`, `provision_pg_entra_roles.py`, and other folders unchanged. psql becomes documented prerequisite for step 4.

### 2026-05-21: Frontend VITE_DISABLE_AUTH build-time MSAL bypass
**By:** Dallas (Frontend Dev)
**Status:** Implemented
**What:** `talent_ui/` now honors `VITE_DISABLE_AUTH=true` at Docker build time. When set: (1) `PublicClientApplication` not constructed; (2) `<App />` not wrapped in `<MsalProvider>` (`main.jsx`); (3) user treated as authenticated with synthetic `{ name: "Demo User", username: "demo@local", homeAccountId: "demo" }`; (4) `getToken()` returns `null`; outbound `fetch` omits `Authorization: Bearer …`; (5) thread-list effect fires on `isAuthenticated && AUTH_DISABLED`. When unset or any other value, MSAL flows exactly as before — production unchanged.
**Files touched:** `Dockerfile` (new `ARG`/`ENV` for `VITE_DISABLE_AUTH`, `VITE_API_BASE`, `VITE_AF_BACKEND_URL`, `VITE_AGENT_NAME`), `src/authConfig.js` (exports `msalConfig=null` when disabled; reads `VITE_MSAL_*` env), `src/main.jsx` (conditional `MsalProvider` wrap), `src/App.jsx` (module-level `AUTH_DISABLED` constant + `DEMO_ACCOUNT`; conditional `useMsal`/`useIsAuthenticated` with `eslint-disable react-hooks/rules-of-hooks` — safe because build-time inlined, DCE removes unused branch; every `!token` bail gated `&& !AUTH_DISABLED`; bearer header replaced with `AUTH_DISABLED ? {} : { Authorization: ... }`), `.env.example`.
**Contract with `03-frontend/deploy.ps1`:** build-arg name MUST be `VITE_DISABLE_AUTH`; check is literal string `"true"` (any other value leaves MSAL active); backend must also have `AZURE_TENANT_ID` unset (`02-backend/deploy.ps1` default) — without backend half, frontend sends unauthenticated requests that production-mode backend would 401.
**Impact:** Bishop — Dockerfile + frontend code match `AUTH-DISABLED.md` contract; `03-frontend/deploy.ps1` can pass `--build-arg VITE_DISABLE_AUTH=true`. Kane — no backend changes needed. Lambert — production `talent_infra_v2/` deployment unchanged (does not set this flag). Re-enabling MSAL later requires only env-var changes, no source edits.

### 2026-05-21: talent_infra_modules/02-backend — Container App + sidecar implemented
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Authored `talent_infra_modules/02-backend/`: `deploy.ps1` (orchestrator), `infra/main.bicep` (one Container App with backend port 8000 external + `mcp-server` sidecar port 3002 intra-pod, one shared UAMI, Foundry `Cognitive Services OpenAI User` role + conditional Cosmos Contributor), `infra/modules/container-app.bicep` (copied from `talent_infra_v2/` with two added outputs `identityClientId`/`identityName`), `infra/main.parameters.json` (ARM defaults), `.acrignore`.
**Key decisions:** (1) **Auth-disable contract honored** — `AZURE_TENANT_ID` is NEVER assigned on either container's env array (verified by grep; appears only in comments). `auth.py` short-circuits to dev mode without it. (2) **Single shared UAMI** — both containers inherit `AZURE_CLIENT_ID` injection from the module; `PGUSER` on both = `${backendAppName}-identity`; MCP reaches backend via `http://localhost:3002/mcp` (pod loopback). (3) **PG registration post-bicep, control plane only** — `az postgres flexible-server microsoft-entra-admin create --type ServicePrincipal --display-name <UAMI-name> --object-id <principalId>`. Display-name MUST equal UAMI name (becomes PG username). Idempotent via `ad-admin list` pre-check on `objectId`/`sid`. (4) **Same-RG constraint** for ACR/Foundry/Cosmos — `deploy.ps1` keeps the ergonomic `*ResourceGroup` params but fails fast if any differ from `ResourceGroup`, pointing operator at `talent_infra_v2/` for cross-RG support. `containerAppsEnvironmentId` passed as full ARM ID. (5) **Role-assignment names use param values** (`backendAppName`, `foundryAccountName`, `cosmosAccountName`) in `guid()`, not module outputs — avoids BCP120. (6) **AcrPull inline in container-app.bicep**, created BEFORE Container App via `dependsOn` to avoid pull-unauthorized startup race. (7) **`postgresqlPrivateFqdn` preferred when `postgresqlPrivateIp` present** in 01-postgresql outputs; falls back to public FQDN when no PE. (8) Cosmos is optional (empty `CosmosAccountName` skips both env vars and role assignment). (9) BackendAppName default is deterministic per `(SubscriptionId, ResourceGroup)` — SHA256 first 5 chars. (10) `-RestartActive` switch resolves active revision via `az containerapp revision list --query "[?properties.active].name | [0]"` and restarts (flushes MCP `Mcp-Session-Id` cache).
**Output schema:** `backendContainerAppName`, `backendContainerAppFqdn`, `backendUamiName`, `backendUamiClientId`, `backendUamiPrincipalId`, `mcpServerImage`, `backendImage`.
**Validation:** `mcp_bicep_build_bicep` success (one cosmetic `use-safe-access` warning preserved from v2 module for parity). PowerShell parse-check zero syntax errors.
**Impact:** 03-frontend reads `backendContainerAppFqdn`; 04-data-loading reads `backendUamiName`/`backendUamiPrincipalId` to narrow broad PG admin grant to schema-scoped grants. Cross-RG ACR/Foundry/Cosmos intentionally not supported in this MVP — `talent_infra_v2/` remains the cross-RG path.

### 2026-05-21: talent_infra_modules/01-postgresql — standalone deployer implemented
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Authored `talent_infra_modules/01-postgresql/`: `deploy.ps1` (orchestrator, dot-sources `../shared/common.ps1`), `infra/main.bicep`, `infra/main.parameters.json`, plus **verbatim copies** of `postgresql-flexible-server.bicep` and `private-endpoint.bicep` from `talent_infra_v2/infra/modules/` into `01-postgresql/infra/modules/`. Per the `do NOT modify the originals; this folder is self-contained` directive, modules were copied byte-for-byte. Future divergence stays local to `talent_infra_modules/`.
**Entra admin registration — control-plane only:** Bicep wiring of `postgresql-flexible-server.bicep` called with `entraAdminObjectId: ''` and `entraAdminPrincipalName: ''`; child resource `Microsoft.DBforPostgreSQL/flexibleServers/administrators` gated by `if (enableEntraAuth && !empty(entraAdminObjectId))` — empty values deliberately skip that resource. All Entra admin writes happen post-deploy: (1) `az ad signed-in-user show` → register deployer as `Type=User`; (2) parse `-UamiPrincipalIds` JSON → register each UAMI as `Type=ServicePrincipal` with `--display-name == entry.name` (UAMI resource name becomes the PG username). Both flows list existing admins first; underlying CLI is also idempotent. Eliminates the `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible` re-PUT race.
**Control-flow choices:** (1) Param resolution layering via `Get-ParameterValue` for strings/`SecureString`; explicit casts for `int`/`bool` env vars. (2) Deterministic server-name fallback `tiqpg<5-hex-chars-of-sha256(subId|rg|location)>` — same RG/region → same name → bicep idempotency. (3) Client IP auto-detect via `api.ipify.org` (5s timeout); skip firewall rule on failure rather than fail deploy. (4) Belt-and-braces restart: after deploy, query `[?isConfigPendingRestart]` and restart if non-empty (without this AGE silently fails on every `cypher()` call). (5) PE private IP discovery mirrors v2 `Get-PostgresqlPrivateEndpointInfo` shape; falls back to `null` in `.outputs.json` when NIC has no IP yet. (6) Password hygiene: `ConvertFrom-SecureStringPlain` once, passed to deploy, then null'd. (7) **NO `psql` / no SQL** — `deploy.ps1` does ZERO data-plane PG ops; every privileged write through Azure control plane (ISP-blocks-5432 footgun avoided).
**Validation:** `mcp_bicep_build_bicep` against `infra/main.bicep`: 0 diagnostics. PowerShell AST parser against `deploy.ps1`: 0 parse errors (2439 tokens). `.outputs.json` schema: `postgresqlServerName`, `postgresqlServerFqdn`, `postgresqlPrivateFqdn`, `postgresqlPrivateIp`, `deployerEntraUpn`, `tenantId`.
**Impact:** 02-backend consumes `postgresqlServerFqdn` + `tenantId`. 04-data-loading consumes `deployerEntraUpn` for Entra-token connect. Strictly additive under `talent_infra_modules/01-postgresql/`.

### 2026-05-21: talent_infra_modules — per-component PowerShell deployment toolkit (architecture)
**By:** Ripley (Lead / Architect)
**Status:** Architecture locked — design accepted by Lambert (verdict above)
**What:** Created top-level `talent_infra_modules/` containing **four independent per-component PowerShell deployment scripts** for the TalentIQ app tier: `01-postgresql/` (PG flex + extensions + Entra admin + optional PE), `02-backend/` (Backend + MCP sidecar Container App + UAMI + role grants), `03-frontend/` (Webapp Container App with `VITE_DISABLE_AUTH=true` build), `04-data-loading/` (`python -m talent_data_pipeline.main` + UAMI narrow grants — no Bicep). Each folder owns `deploy.ps1` + (optionally) `infra/main.bicep` + `infra/main.parameters.json` and emits `.outputs.json` consumed by downstream folders. Shared infra in `shared/common.ps1` (dot-sourced). Toolkit **assumes most Azure infra already exists** (RG, VNet+subnets, ACA env, ACR, Foundry account+project+model deployments, optionally Cosmos) and VERIFIES via `Assert-PrerequisitesExist`, fails fast when missing. Scripts do NOT create infrastructure beyond app tier.
**Why:** (1) Existing demo environments have RG/VNet/ACA/ACR/Foundry already provisioned — forcing through `azd up` either fails or reprovisions things that didn't need to change. (2) Faster iteration loop on single component — e.g. `02-backend/` redeploys backend Container App in < 90 seconds for a tag bump. (3) Demo-mode auth simplification — no app registration churn (SPA redirect URI + admin consent + audience alignment). (4) Standalone documentation per folder.
**Constraints:** NO azd dependency (direct `az` CLI only). NO infra creation beyond app tier. All Bicep per-component (no shared root template). State is file-based (`.outputs.json`).
**Auth-disable contract (demo mode = DEFAULT):** Backend OMITS `AZURE_TENANT_ID` (auth.py lines 86-90 short-circuits to `dev-user`); Frontend uses `VITE_DISABLE_AUTH=true` Docker build arg (REQUIRES UI code change — gates `<MsalProvider>` and `useIsAuthenticated()` on flag — Dallas's responsibility, NOT in scope for `talent_infra_modules/`). NOT bypassed even in demo mode: Backend→PG (Entra), Backend→Foundry (Entra), Backend→Cosmos (Entra), ACR image pulls (Entra). Only inbound user→UI→backend HTTP path is unauthenticated.
**Deployment order:** `01-postgresql → 02-backend → 03-frontend`; `04-data-loading` can run any time after `01`. Skip patterns documented in `DEPLOYMENT-ORDER.md`.
**Boundary with `talent_infra_v2/`:** v2 = full-stack greenfield production (azd, MSAL on, JWT validated). modules = app tier only on pre-existing infra (PS scripts, MSAL off, dev-user passthrough). Both coexist in same repo; top-level `README.md` documents picking the right one.
**Files produced (architecture deliverables):** `talent_infra_modules/{README.md, AUTH-DISABLED.md, DEPLOYMENT-ORDER.md, shared/common.ps1, shared/README.md, 01-postgresql/README.md, 02-backend/README.md, 03-frontend/README.md, 04-data-loading/README.md}`. Bishop received the full contract surface.
**Impact:** Bishop (4 implementation spawns) + Dallas (UI bypass) executed against this contract. Lambert APPROVED the resulting toolkit.

### 2026-05-16: Infra rebuilt to match reference two-phase deployment pattern
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Deleted all existing `talent_infra/` files (except `.azure/`) and rebuilt the entire infrastructure following the `talentiq_requirements/reference_code/azd_deploy/` pattern exactly. Created 21 files: `azure.yaml` with hooks/outputs, `infra/main.bicep` with conditional deploy flags for two-phase deployment, 13 Bicep modules (including new Cosmos DB + Key Vault), 4 hook scripts (pre/postprovision for PS1 and bash). Key changes: two-phase deployment (provision infra first, then build+deploy containers via postprovision hook), deploy flags reset by preprovision/set by postprovision, Docker Desktop detection with ACR remote build fallback, content hashing to skip unchanged builds, PostgreSQL AGE init + data loading flag-gated.
**Why:** Anil requested alignment with the proven `talentiq_requirements/reference_code/azd_deploy/` pattern for production deployment reliability.
**Impact:** All agents — `talent_infra/` is completely new. Lambert's smoke tests should validate against these Bicep outputs. All Bicep compiles clean (1 warning: unused throughput param in serverless Cosmos).

### 2026-05-16: Infrastructure rebuild complete
**By:** Bishop (Deployment Engineer)
**Status:** Implemented
**What:** Rebuilt all 17 `talent_infra/` files from history blueprint after prior passes were lost to disk. Full Bicep IaC validated with zero errors. Architecture unchanged — VNet, 3 Container Apps (frontend public, backend+MCP internal), Cosmos DB + PostgreSQL + Foundry + KV + ACR all with private endpoints/delegated subnets, RBAC-only auth, Entra ID-only on PostgreSQL. Ready for `azd up`.
**Why:** Files from Passes 1-3 did not survive to disk. History.md served as complete blueprint for faithful recreation.
**Impact:** All team members can now reference `talent_infra/` for infrastructure. Lambert's smoke tests should pass against the Bicep outputs unchanged.

### 2026-05-16: Role added as canonical entity to data model
**By:** Brett (Data Generator & Loader)
**Status:** Implemented
**What:** Added `Role` as a first-class graph node (17 roles with name/code/aliases) and `HAS_ROLE` as a 1:1 edge from Employee → Role. Previously, job roles were free-text strings hardcoded in multiple generators.
**Key decisions:**
1. **17 canonical roles** — Unified from three separate hardcoded lists.
2. **`role_name` field on Employee** — Added alongside existing `job_title`.
3. **`HAS_ROLE` edge is 1:1** — Each employee has exactly one role.
4. **ROLES in ENTITY_SOURCES** — Roles get FTS + vector embeddings via entity_search.
5. **AGE property indexes** — `idx_role_name` and `idx_role_code` added.
**Impact:** Kane/MCP agents can now query `MATCH (e:Employee)-[:HAS_ROLE]->(r:Role) WHERE r.code = 'PM'`. Ontology now has 15 node labels (was 14) and 13 edge types (was 12). Backward compatible — `job_title` property unchanged.

### 2026-05-16: Resolve-first query architecture — MCP tool descriptions cleaned
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Updated all MCP tool descriptions to enforce the resolve-first query pattern. `resolve_entities` docstring says "CALL THIS FIRST". `query_using_sql_cypher` mandates `v.code = 'RESOLVED_CODE'` matching. `search_graph` narrowed to employee name lookup only. `vector_search` narrowed to resume/skills semantic matching only. Tool implementations unchanged — only descriptions/docstrings updated.
**Why:** The agent was calling wrong tools for entity lookups (search_graph, vector_search instead of resolve_entities), degrading result quality.
**Impact:** All agents using MCP tools — follow pattern: `resolve_entities → Cypher with .code = 'X'`, only vector_search for semantic resume/skills matching.

### 2026-05-16: Batch embeddings in resolve_entities — performance optimization
**By:** Kane (Backend Dev)
**Status:** Implemented
**What:** Restructured `resolve_entities` into a two-pass architecture: Pass 1 (fast, no HTTP) runs exact-code, exact-name, and FTS checks for ALL queries in a single DB cursor pass. Pass 2 (one HTTP call) batches all unresolved terms into a single Azure OpenAI embeddings API call. Previously ~28 seconds for 47 entities (sequential HTTP per term), now estimated ~3-5 seconds.
**Why:** Sequential embedding calls (~30 × 300ms) dominated resolution latency.
**Impact:** All MCP tool consumers — resolve_entities is significantly faster. Resolution priority, thresholds, and confidence scoring unchanged.

### 2026-05-16: Agent instructions rewritten — resolve-first, no hardcoded rules
**By:** Parker (Data Engineer)
**Status:** Implemented
**What:** Rewrote `TALENT_GRAPH_QUERY_GENERATION_AGENT_v1.md` to enforce clean resolve-first architecture. All hardcoded entity values removed. Instructions teach patterns, not specific values. Workflow: parse → resolve_entities → build Cypher with codes → execute → format. The `resolve_entities` tool is the sole source of truth for entity→code mapping. All 19 AGE Query Rules, RFP Multi-Role Matching Workflow, Response Format, and Graph Ontology sections preserved.
**Why:** Hardcoded entity names and regex patterns in instructions were brittle and caused mismatches.

### 2026-05-22: talent_data_pipeline outer folders are stale refactor artifacts
**By:** Brett (Data Generator & Loader), requested by Anil
**What:** The outer-level `talent_data_pipeline/{loaders,generators,schema}/` folders are dead code left over from a flat-layout → nested-package refactor. Only the nested `talent_data_pipeline/talent_data_pipeline/` package is built and imported.

**Evidence:**
- `pyproject.toml` declares `packages = ["talent_data_pipeline"]` — only the nested package is installable.
- All entry scripts (`main.py`, `validate.py`, `connectivity_test.py`) import exclusively from `talent_data_pipeline.X` (the nested package), never from the flat outer folders.
- The two `loaders/` trees have diverged: the inner versions have checkpoint/resume logic, batched `execute_values`, and recent optimizations that the outer copies lack.

**Recommendation:** Delete the outer `loaders/`, `generators/`, and `schema/` folders. Keep only the nested package. No imports break, no scripts need updating — pure cleanup.

**Risk if left as-is:** Anyone editing the outer files (autocomplete, grep hits, IDE jumps) silently changes dead code while the runtime uses the inner package. Already-diverged copies will keep diverging.

**Action taken (2026-05-22, Brett):** Deleted 13 tracked files under `talent_data_pipeline/{loaders,generators,schema}/` (loaders=5, generators=6, schema=2). Pre-flight import scan across the repo (excluding `.venv`/`__pycache__`/`node_modules`) found zero hits on bare `loaders|generators|schema` imports; post-delete smoke test `from talent_data_pipeline.loaders.{base,fts,graph,vector,entity_search}_loader import *` returned OK. Deletions are unstaged (` D` in git) for Anil to commit when ready. The nested `talent_data_pipeline/talent_data_pipeline/` package is now the SOLE source of truth — no more dual-edit discipline, no more silent divergence.

